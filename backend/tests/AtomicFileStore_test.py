import os
import secrets
import tempfile
import threading
import unittest
from unittest.mock import patch

from src.AtomicFileStore import AtomicFileStore, AtomicWriteConflictError, AtomicWriteError


class FailingFile:
    def __init__(self, wrapped, failure: str):
        self.wrapped = wrapped
        self.failure = failure

    def __enter__(self):
        self.wrapped.__enter__()
        return self

    def __exit__(self, *args):
        return self.wrapped.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def write(self, content):
        if self.failure == "write":
            raise OSError("injected write failure")
        return self.wrapped.write(content)

    def flush(self):
        if self.failure == "flush":
            raise OSError("injected flush failure")
        return self.wrapped.flush()


class TestAtomicFileStore(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.path = os.path.join(self.temp_directory.name, "tasks.json")
        self.store = AtomicFileStore()
        with open(self.path, "wb") as file:
            file.write(b"old content")

    def _read(self):
        with open(self.path, "rb") as file:
            return file.read()

    def test_update_recalculates_against_external_change_before_replacing(self):
        original_stage = self.store._stage
        updater_inputs = []
        stage_count = 0

        def stage_and_change_target(path, content, mode, validator):
            nonlocal stage_count
            temporary_path = original_stage(path, content, mode, validator)
            if stage_count == 0:
                with open(path, "wb") as file:
                    file.write(b"external edit")
            stage_count += 1
            return temporary_path

        def update(current):
            updater_inputs.append(current)
            return current + b" + updated"

        with patch.object(self.store, "_stage", side_effect=stage_and_change_target):
            saved = self.store.update(self.path, update)

        self.assertEqual(updater_inputs, [b"old content", b"external edit"])
        self.assertEqual(saved, b"external edit + updated")
        self.assertEqual(self._read(), saved)

    def test_exhausted_external_conflicts_are_typed_and_leave_latest_file(self):
        original_stage = self.store._stage
        counter = 0

        def stage_and_change_each_time(path, content, mode, validator):
            nonlocal counter
            temporary_path = original_stage(path, content, mode, validator)
            with open(path, "wb") as file:
                file.write(f"external {counter}".encode("utf-8"))
            counter += 1
            return temporary_path

        with patch.object(self.store, "_stage", side_effect=stage_and_change_each_time):
            with self.assertRaises(AtomicWriteConflictError) as raised:
                self.store.update(self.path, lambda current: current + b"!")

        self.assertEqual(raised.exception.effects_state, "none")
        self.assertFalse(raised.exception.replaced)
        self.assertEqual(raised.exception.attempts, 3)
        self.assertEqual(self._read(), b"external 2")

    def test_write_failure_before_replace_reports_no_effect(self):
        original_fdopen = os.fdopen

        def failing_fdopen(descriptor, mode):
            return FailingFile(original_fdopen(descriptor, mode), "write")

        with patch("src.AtomicFileStore.os.fdopen", side_effect=failing_fdopen):
            with self.assertRaises(AtomicWriteError) as raised:
                self.store.write(self.path, b"new content")

        self.assertEqual(raised.exception.phase, "write")
        self.assertEqual(raised.exception.effects_state, "none")
        self.assertFalse(raised.exception.replaced)
        self.assertEqual(self._read(), b"old content")

    def test_flush_failure_before_replace_reports_no_effect(self):
        original_fdopen = os.fdopen

        def failing_fdopen(descriptor, mode):
            return FailingFile(original_fdopen(descriptor, mode), "flush")

        with patch("src.AtomicFileStore.os.fdopen", side_effect=failing_fdopen):
            with self.assertRaises(AtomicWriteError) as raised:
                self.store.write(self.path, b"new content")

        self.assertEqual(raised.exception.phase, "flush")
        self.assertEqual(raised.exception.effects_state, "none")
        self.assertFalse(raised.exception.replaced)
        self.assertEqual(self._read(), b"old content")

    def test_file_fsync_failure_before_replace_reports_no_effect(self):
        with patch("src.AtomicFileStore.os.fsync", side_effect=OSError("injected fsync failure")):
            with self.assertRaises(AtomicWriteError) as raised:
                self.store.write(self.path, b"new content")

        self.assertEqual(raised.exception.phase, "file_fsync")
        self.assertEqual(raised.exception.effects_state, "none")
        self.assertFalse(raised.exception.replaced)
        self.assertEqual(self._read(), b"old content")

    def test_replace_failure_reports_uncertain_effect(self):
        with patch("src.AtomicFileStore.os.replace", side_effect=OSError("injected replace failure")):
            with self.assertRaises(AtomicWriteError) as raised:
                self.store.write(self.path, b"new content")

        self.assertEqual(raised.exception.phase, "replace")
        self.assertEqual(raised.exception.effects_state, "unknown")
        self.assertIsNone(raised.exception.replaced)
        self.assertEqual(self._read(), b"old content")

    def test_directory_fsync_failure_reports_replaced_but_uncertain_durability(self):
        with patch.object(self.store, "_fsync_directory", side_effect=OSError("injected dir fsync failure")):
            with self.assertRaises(AtomicWriteError) as raised:
                self.store.write(self.path, b"new content")

        self.assertEqual(raised.exception.phase, "directory_fsync")
        self.assertEqual(raised.exception.effects_state, "unknown")
        self.assertTrue(raised.exception.replaced)
        self.assertEqual(self._read(), b"new content")

    @unittest.skipUnless(hasattr(os, "fchmod"), "file mode preservation needs fchmod")
    def test_replacement_preserves_existing_permissions(self):
        os.chmod(self.path, 0o640)

        self.store.write(self.path, b"new content")

        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)
        self.assertEqual(self._read(), b"new content")

    def test_concurrent_reader_observes_complete_old_or_new_file(self):
        old = b"old" * 10000
        new = b"new" * 10000
        with open(self.path, "wb") as file:
            file.write(old)

        replace_started = threading.Event()
        allow_replace = threading.Event()
        original_replace = os.replace
        write_errors = []

        def blocked_replace(source, destination):
            replace_started.set()
            if not allow_replace.wait(5):
                raise TimeoutError("test did not release replacement")
            original_replace(source, destination)

        def write_new_content():
            try:
                self.store.write(self.path, new)
            except Exception as error:
                write_errors.append(error)

        with patch("src.AtomicFileStore.os.replace", side_effect=blocked_replace):
            writer = threading.Thread(target=write_new_content)
            writer.start()
            self.assertTrue(replace_started.wait(5))
            self.assertEqual(self._read(), old)
            allow_replace.set()
            writer.join(5)

        self.assertFalse(writer.is_alive())
        self.assertEqual(write_errors, [])
        self.assertEqual(self._read(), new)

    def test_startup_cleanup_removes_only_own_temporary_names(self):
        token = secrets.token_hex(16)
        own_temp = os.path.join(self.temp_directory.name, f".elrik-atomic-{token}.tmp")
        unrelated = os.path.join(self.temp_directory.name, ".elrik-atomic-invalid.tmp")
        outside_directory = tempfile.TemporaryDirectory()
        self.addCleanup(outside_directory.cleanup)
        outside = os.path.join(outside_directory.name, f".elrik-atomic-{secrets.token_hex(16)}.tmp")
        for path in (own_temp, unrelated, outside):
            with open(path, "wb") as file:
                file.write(b"orphan")

        removed = AtomicFileStore.cleanup_temporary_files([self.temp_directory.name])

        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(own_temp))
        self.assertTrue(os.path.exists(unrelated))
        self.assertTrue(os.path.exists(outside))

    def test_long_unicode_target_uses_short_temporary_name(self):
        name_max = os.pathconf(self.temp_directory.name, "PC_NAME_MAX")
        filename = ("界" * 70) + ".md"
        if len(filename.encode("utf-8")) > name_max:
            self.skipTest("filesystem component limit is too small for this target name")
        path = os.path.join(self.temp_directory.name, filename)

        self.store.write(path, "complete text".encode("utf-8"))

        with open(path, "rb") as file:
            self.assertEqual(file.read(), b"complete text")

    def test_create_if_absent_never_overwrites_existing_file(self):
        invalid_existing_data = b"{invalid-json"
        with open(self.path, "wb") as file:
            file.write(invalid_existing_data)

        with patch.object(self.store, "_stage", side_effect=AssertionError("existing file must not be staged")):
            created = self.store.create_if_absent(self.path, b"replacement")

        self.assertFalse(created)
        self.assertEqual(self._read(), invalid_existing_data)


if __name__ == "__main__":
    unittest.main()
