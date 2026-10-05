"""Exercise the notification history against real local files and FIFO writes."""

from __future__ import annotations

import datetime
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID

from src.FileBroker import FileBroker
from src.Interfaces.IFileBroker import FileRegistry
from src.MutationCoordinator import MutationCoordinator
from src.NotificationHistoryStore import (
    InvalidNotificationHistoryError,
    NotificationHistoryStore,
    NotificationHistoryUnavailableError,
    NotificationHistoryWriteError,
)


TOKEN = "notification-history-test-secret"
TIMESTAMP = datetime.datetime(2026, 10, 5, 10, 30, tzinfo=datetime.timezone.utc)


class NotificationHistoryStoreIntegrationTest(unittest.TestCase):
    """Check durable history, concurrent access, and uncertain atomic writes."""

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.coordinator = MutationCoordinator()
        self.broker = FileBroker(
            str(self.data),
            str(self.root / "appdata"),
            str(self.root / "vault"),
            self.coordinator,
        )
        self.history_path = Path(
            self.broker.getFilePath(FileRegistry.NOTIFICATIONS_JSON)
        )
        self.store = NotificationHistoryStore(
            self.broker,
            self.coordinator,
            TOKEN,
        )

    def tearDown(self) -> None:
        self.coordinator.close()
        self.temporary.cleanup()

    def test_missing_reads_and_appends_do_not_create_history(self) -> None:
        self.assertFalse(self.history_path.exists())

        with self.assertRaises(NotificationHistoryUnavailableError):
            self.store.read()
        with self.assertRaises(NotificationHistoryUnavailableError):
            self.store.append("cannot create from a read path", timestamp=TIMESTAMP)
        with self.assertRaises(NotificationHistoryUnavailableError):
            self.store.renew_history_id()

        self.assertFalse(self.history_path.exists())

        created = self.store.initialize()
        self.assertEqual(created.next_sequence, 1)
        self.assertTrue(self.history_path.is_file())

    def test_restart_and_intact_restore_preserve_identity_and_counter(self) -> None:
        initial = self.store.initialize()
        first = self.store.append("same text", timestamp=TIMESTAMP)
        intact_bytes = self.history_path.read_bytes()
        intact_stat = self.history_path.stat()
        second = self.store.append("same text", timestamp=TIMESTAMP)

        restarted = NotificationHistoryStore(
            self.broker,
            self.coordinator,
            TOKEN,
        )
        reopened = restarted.initialize()
        self.assertEqual(reopened.history_id, initial.history_id)
        self.assertEqual(reopened.next_sequence, 3)
        self.assertEqual([entry.id for entry in reopened.entries], [first.id, second.id])

        self.broker.writeFileContent(
            FileRegistry.NOTIFICATIONS_JSON,
            intact_bytes.decode("utf-8"),
        )
        restored = restarted.initialize()
        self.assertEqual(restored.history_id, initial.history_id)
        self.assertEqual(restored.next_sequence, 2)
        self.assertEqual([entry.id for entry in restored.entries], [first.id])

        renewed = restarted.renew_history_id()
        self.assertNotEqual(renewed.history_id, initial.history_id)
        self.assertEqual(renewed.next_sequence, 2)
        self.assertEqual(len(renewed.entries), 1)
        self.assertEqual(renewed.entries[0].sequence, first.sequence)
        self.assertEqual(renewed.entries[0].id, f"{renewed.history_id}:1")
        self.assertEqual(renewed.entries[0].text, first.text)
        after_restore = restarted.append("after explicit renewal", timestamp=TIMESTAMP)
        self.assertEqual(after_restore.sequence, 2)
        self.assertEqual(after_restore.id, f"{renewed.history_id}:2")
        UUID(renewed.history_id)

        # Re-opening an intact history validates it without rewriting its bytes.
        before_reopen = self.history_path.read_bytes()
        before_mtime = self.history_path.stat().st_mtime_ns
        reopened_again = restarted.initialize()
        self.assertEqual(reopened_again.history_id, renewed.history_id)
        self.assertEqual(self.history_path.read_bytes(), before_reopen)
        self.assertEqual(self.history_path.stat().st_mtime_ns, before_mtime)
        self.assertEqual(intact_stat.st_size, len(intact_bytes))

        self.history_path.unlink()
        with self.assertRaises(NotificationHistoryUnavailableError):
            restarted.read()
        self.assertFalse(self.history_path.exists())
        regenerated = restarted.initialize()
        self.assertNotEqual(regenerated.history_id, renewed.history_id)
        self.assertEqual(regenerated.next_sequence, 1)
        self.assertEqual(regenerated.entries, ())

    def test_retention_trims_only_when_history_exceeds_1024(self) -> None:
        self.store.initialize()
        for index in range(1024):
            self.store.append(f"notice-{index}", timestamp=TIMESTAMP)

        before_trim = self.store.read()
        self.assertEqual(before_trim.next_sequence, 1025)
        self.assertEqual(before_trim.discarded_through, 0)
        self.assertEqual(len(before_trim.entries), 1024)
        self.assertEqual(before_trim.entries[0].sequence, 1)
        self.assertEqual(before_trim.entries[-1].sequence, 1024)

        self.store.append("notice-1024", timestamp=TIMESTAMP)
        trimmed = self.store.read()
        self.assertEqual(trimmed.next_sequence, 1026)
        self.assertEqual(trimmed.discarded_through, 1)
        self.assertEqual(len(trimmed.entries), 1024)
        self.assertEqual(trimmed.entries[0].sequence, 2)
        self.assertEqual(trimmed.entries[-1].sequence, 1025)

    def test_concurrent_appends_and_readers_observe_complete_ordered_snapshots(self) -> None:
        self.store.initialize()
        worker_count = 8
        start = threading.Barrier(worker_count)
        writers_started = threading.Event()
        observed: list[list[tuple[str, int, int]]] = []
        observed_lock = threading.Lock()

        def append(index: int) -> str:
            start.wait(timeout=5)
            writers_started.set()
            return self.store.append(f"parallel-{index}", timestamp=TIMESTAMP).id

        def read_repeatedly() -> list[tuple[str, int, int]]:
            start.wait(timeout=5)
            self.assertTrue(writers_started.wait(timeout=5))
            snapshots: list[tuple[str, int, int]] = []
            for _ in range(50):
                snapshot = self.store.read()
                entries = snapshot.entries
                sequences = [entry.sequence for entry in entries]
                self.assertEqual(sequences, list(range(1, snapshot.next_sequence)))
                self.assertTrue(
                    all(entry.id == f"{snapshot.history_id}:{entry.sequence}" for entry in entries)
                )
                snapshots.append((snapshot.history_id, snapshot.next_sequence, len(entries)))
            return snapshots

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(append, index) for index in range(6)]
            futures.extend(executor.submit(read_repeatedly) for _ in range(2))
            results = [future.result(timeout=30) for future in futures]

        appended_ids = results[:6]
        self.assertEqual(len(set(appended_ids)), 6)
        for reader_results in results[6:]:
            self.assertEqual(len(reader_results), 50)
            with observed_lock:
                observed.extend(reader_results)
        self.assertTrue(observed)

        final = self.store.read()
        self.assertEqual(final.next_sequence, 7)
        self.assertEqual(len(final.entries), 6)
        self.assertEqual({entry.id for entry in final.entries}, set(appended_ids))

    def test_pre_replace_failure_keeps_bytes_and_does_not_consume_sequence(self) -> None:
        self.store.initialize()
        before = self.history_path.read_bytes()

        with patch(
            "src.AtomicFileStore.os.fsync",
            side_effect=OSError("temporary file sync failed"),
        ):
            with self.assertRaises(NotificationHistoryWriteError) as raised:
                self.store.append("not saved", timestamp=TIMESTAMP)

        self.assertEqual(raised.exception.effects_state, "none")
        self.assertEqual(self.history_path.read_bytes(), before)
        self.assertEqual(self.store.read().next_sequence, 1)

        saved = self.store.append("saved after failure", timestamp=TIMESTAMP)
        self.assertEqual(saved.sequence, 1)

    def test_post_replace_failure_is_unknown_and_next_append_reads_saved_sequence(self) -> None:
        empty = self.store.initialize()

        with patch.object(
            self.store._atomic_file_store,
            "_fsync_directory",
            side_effect=OSError("directory sync failed after replacement"),
        ):
            with self.assertRaises(NotificationHistoryWriteError) as raised:
                self.store.append("published before sync failure", timestamp=TIMESTAMP)

        self.assertEqual(raised.exception.effects_state, "unknown")
        self.assertEqual(raised.exception.phase, "directory_fsync")

        restarted = NotificationHistoryStore(
            self.broker,
            self.coordinator,
            TOKEN,
        )
        visible = restarted.read()
        self.assertEqual(visible.history_id, empty.history_id)
        self.assertEqual(visible.next_sequence, 2)
        self.assertEqual([entry.sequence for entry in visible.entries], [1])

        following = restarted.append("next sequence after uncertain write", timestamp=TIMESTAMP)
        self.assertEqual(following.sequence, 2)
        self.assertEqual(following.id, f"{empty.history_id}:2")

    def test_invalid_history_is_reported_without_changing_original_bytes(self) -> None:
        invalid_files = (
            b'{"schemaVersion":1,',
            b'{"schemaVersion":1,"historyId":"bad","nextSequence":1,'
            b'"discardedThrough":0,"entries":[]}',
        )
        for invalid_bytes in invalid_files:
            with self.subTest(invalid=invalid_bytes):
                self.history_path.write_bytes(invalid_bytes)
                before_stat = self.history_path.stat()

                with self.assertRaises(InvalidNotificationHistoryError):
                    self.store.initialize()
                with self.assertRaises(InvalidNotificationHistoryError):
                    self.store.read()

                self.assertEqual(self.history_path.read_bytes(), invalid_bytes)
                self.assertEqual(self.history_path.stat().st_mtime_ns, before_stat.st_mtime_ns)

    def test_sanitization_redacts_exact_token_and_preserves_literal_marker(self) -> None:
        self.store.initialize()
        text = f"message contains {TOKEN} and the literal [redactado] marker"
        entry = self.store.append(text, timestamp=TIMESTAMP)
        self.assertEqual(
            entry.text,
            "message contains [redactado] and the literal [redactado] marker",
        )
        self.assertNotIn(TOKEN.encode("utf-8"), self.history_path.read_bytes())

        marker_store = NotificationHistoryStore(
            self.broker,
            self.coordinator,
            "[redactado]",
        )
        marker_entry = marker_store.append("literal [redactado] remains visible", timestamp=TIMESTAMP)
        self.assertEqual(marker_entry.text, "literal [redactado] remains visible")


if __name__ == "__main__":
    unittest.main()
