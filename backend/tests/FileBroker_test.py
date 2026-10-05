import unittest
import os
import json
import tempfile
import threading
from unittest.mock import patch, mock_open
from src.FileBroker import FileBroker
from src.Interfaces.IFileBroker import FileRegistry, VaultRegistry
from src.MutationCoordinator import MutationCoordinator


class TestFileBroker(unittest.TestCase):

    def setUp(self):
        self.jsonPath = "/fake/json/path"
        self.appdata = "/fake/appdata/path"
        self.vaultPath = "/fake/vault/path"
        self.fileBroker = FileBroker(
            self.jsonPath,
            self.appdata,
            self.vaultPath
        )

    def test_readFileContent_WhenFileIsFound_ThenReturnFileContent(self):
        with patch("builtins.open", mock_open(read_data="data")) as mock_file:
            readcontent = self.fileBroker.readFileContent(
                FileRegistry.STANDALONE_TASKS_JSON
            )
            self.assertEqual(readcontent, "data")
            filePath = os.path.join(self.jsonPath, "tasks.json")
            mock_file.assert_called_once_with(filePath, "r", encoding="utf-8", newline="")

    def test_readFileContent_WhenFileIsNotFound_ThenReturnDefaultWithoutCreating(self):
        with patch("builtins.open", side_effect=FileNotFoundError) as mock_file:
            readcontent = self.fileBroker.readFileContent(FileRegistry.STANDALONE_TASKS_JSON)
        self.assertEqual(readcontent, '{"tasks": []}')
        self.assertEqual(mock_file.call_count, 1)

    def test_readFileContentJson_WhenFileIsFound_ThenReturnFileContent(self):
        with patch("builtins.open", mock_open(read_data='{"key": "value"}')) as mock_file:
            readcontent = self.fileBroker.readFileContentJson(
                FileRegistry.STANDALONE_TASKS_JSON
            )
            self.assertEqual(readcontent, {"key": "value"})
            filePath = os.path.join(self.jsonPath, "tasks.json")
            mock_file.assert_called_once_with(filePath, "r", encoding="utf-8", newline="")

    def test_readFileContentJson_WhenFileIsNotFound_ThenReturnDefaultWithoutCreating(self):
        with patch("builtins.open", side_effect=FileNotFoundError) as mock_file:
            readcontent = self.fileBroker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)
        self.assertEqual(readcontent, {"tasks": []})
        self.assertEqual(mock_file.call_count, 1)

    def test_getFilePath_returns_the_configured_path(self):
        self.assertEqual(
            self.fileBroker.getFilePath(FileRegistry.STANDALONE_TASKS_JSON),
            os.path.join(self.jsonPath, "tasks.json"),
        )

    def test_repeated_id_key_is_rejected_without_changing_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"))
            path = os.path.join(directory, "tasks.json")
            invalid_content = '{"tasks": [{"description": "Bad", "id": "first", "id": "second"}]}'
            with open(path, "w", encoding="utf-8") as file:
                file.write(invalid_content)

            with self.assertRaisesRegex(ValueError, "more than once"):
                broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)

            with open(path, encoding="utf-8") as file:
                self.assertEqual(file.read(), invalid_content)

    def test_readStatisticsFileContentJson_WhenFileIsMissing_ThenReturnSafeDefaultWithoutCreating(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = self.fileBroker.readStatisticsFileContentJson()
        self.assertEqual(result, {"log": []})

    def test_initializeFileContent_createsDefaultExplicitlyAndIsIdempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, os.path.join(directory, "app"), os.path.join(directory, "vault"))
            broker.initializeFileContent(FileRegistry.OBSIDIAN_TASKS_JSON)
            path = os.path.join(directory, "app", "obsidian", "tareas.json")
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding="utf-8") as file:
                self.assertEqual(file.read(), '{"tasks": []}')

            with open(path, "w", encoding="utf-8") as file:
                file.write('{"tasks": [{"description": "keep"}]}')
            broker.initializeFileContent(FileRegistry.OBSIDIAN_TASKS_JSON)
            with open(path, encoding="utf-8") as file:
                self.assertEqual(file.read(), '{"tasks": [{"description": "keep"}]}')

    def test_repeatedMissingReadsLeaveFilesystemUnchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            json_path = os.path.join(directory, "json")
            appdata = os.path.join(directory, "appdata")
            vault_path = os.path.join(directory, "vault")
            broker = FileBroker(json_path, appdata, vault_path)
            before = sorted(
                os.path.join(root, name)
                for root, _, names in os.walk(directory)
                for name in names
            )

            for _ in range(2):
                self.assertEqual(broker.readFileContent(FileRegistry.STANDALONE_TASKS_JSON), '{"tasks": []}')
                self.assertEqual(broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON), {"tasks": []})
                self.assertEqual(broker.readFileContentJson(FileRegistry.OBSIDIAN_TASKS_JSON), {"tasks": []})
                self.assertEqual(broker.readFileContentJson(FileRegistry.LAST_RECEIVED_FILE), {"tasks": []})
                self.assertEqual(broker.readStatisticsFileContentJson(), {"log": []})
                self.assertEqual(broker.getVaultFiles(VaultRegistry.OBSIDIAN), [])
                with self.assertRaises(FileNotFoundError):
                    broker.getVaultFileLines(VaultRegistry.OBSIDIAN, "absent.md")

            after = sorted(
                os.path.join(root, name)
                for root, _, names in os.walk(directory)
                for name in names
            )
            self.assertEqual(after, before)
            self.assertFalse(os.path.exists(json_path))
            self.assertFalse(os.path.exists(appdata))
            self.assertFalse(os.path.exists(vault_path))

    def test_storage_mutations_join_shared_turn_and_run_inline_when_nested(self):
        with tempfile.TemporaryDirectory() as directory:
            vault_path = os.path.join(directory, "vault")
            coordinator = MutationCoordinator()
            broker = FileBroker(directory, os.path.join(directory, "app"), vault_path, coordinator)
            try:
                def complete_storage_turn() -> None:
                    broker.writeFileContent(FileRegistry.LAST_RECEIVED_FILE, '{"tasks": []}')
                    broker.updateFileContentJson(
                        FileRegistry.STANDALONE_TASKS_JSON,
                        lambda current: {**current, "marker": "task"},
                    )
                    broker.initializeFileContent(FileRegistry.STATISTICS_JSON)
                    broker.writeVaultFileLines(VaultRegistry.OBSIDIAN, "project.md", ["# Project\n"])
                    broker.updateVaultFileLines(
                        VaultRegistry.OBSIDIAN,
                        "project.md",
                        lambda lines: lines + ["- [ ] Next action\n"],
                    )

                coordinator.run_job(complete_storage_turn)
                self.assertEqual(broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)["marker"], "task")
                self.assertEqual(
                    broker.getVaultFileLines(VaultRegistry.OBSIDIAN, "project.md"),
                    ["# Project\n", "- [ ] Next action\n"],
                )
                self.assertEqual(broker.readStatisticsFileContentJson(), {"log": []})
            finally:
                coordinator.close(wait=True)

    def test_storage_write_waits_behind_an_admitted_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = MutationCoordinator()
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"), coordinator)
            turn_started = threading.Event()
            release_turn = threading.Event()
            writer_started = threading.Event()
            writer_finished = threading.Event()

            def hold_turn() -> None:
                turn_started.set()
                if not release_turn.wait(2):
                    raise TimeoutError("test did not release queued storage turn")

            def blocking_writer() -> None:
                writer_started.set()
                broker.writeFileContent(FileRegistry.STANDALONE_TASKS_JSON, '{"tasks": []}')
                writer_finished.set()

            coordinator_thread = threading.Thread(target=lambda: coordinator.run_job(hold_turn))
            writer_thread = threading.Thread(target=blocking_writer)
            try:
                coordinator_thread.start()
                self.assertTrue(turn_started.wait(1))
                writer_thread.start()
                self.assertTrue(writer_started.wait(1))
                self.assertFalse(writer_finished.wait(0.05))
                release_turn.set()
                coordinator_thread.join(2)
                writer_thread.join(2)
                self.assertFalse(coordinator_thread.is_alive())
                self.assertFalse(writer_thread.is_alive())
                self.assertTrue(writer_finished.is_set())
            finally:
                release_turn.set()
                coordinator_thread.join(2)
                writer_thread.join(2)
                coordinator.close(wait=True)

    def test_invalidJsonIsRaisedAndNeverReplaced(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"))
            path = os.path.join(directory, "tasks.json")
            invalid_content = "{invalid-json"
            with open(path, "w", encoding="utf-8") as file:
                file.write(invalid_content)
            with open(path, "rb") as file:
                before = file.read()

            for _ in range(2):
                with self.assertRaises(json.JSONDecodeError):
                    broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON)

            with open(path, "rb") as file:
                self.assertEqual(file.read(), before)

    def test_invalidUtf8CannotBeSilentlyRewrittenByTextUpdate(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"))
            path = os.path.join(directory, "tasks.json")
            invalid_content = b'{"tasks": [\xff]}'
            with open(path, "wb") as file:
                file.write(invalid_content)

            with self.assertRaises(UnicodeDecodeError):
                broker.updateFileContent(FileRegistry.STANDALONE_TASKS_JSON, lambda current: current + " ")

            with open(path, "rb") as file:
                self.assertEqual(file.read(), invalid_content)

    def test_updateFileContentJsonReturnsTheSavedFullDocument(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"))
            path = os.path.join(directory, "tasks.json")
            with open(path, "w", encoding="utf-8") as file:
                file.write('{"tasks": [], "metadata": {"keep": true}}')

            saved = broker.updateFileContentJson(
                FileRegistry.STANDALONE_TASKS_JSON,
                lambda document: document.update({"updated": True}) or document,
            )

            self.assertEqual(saved["metadata"], {"keep": True})
            self.assertTrue(saved["updated"])
            self.assertEqual(broker.readFileContentJson(FileRegistry.STANDALONE_TASKS_JSON), saved)

    def test_rawTextWriteToJsonRegistryRejectsInvalidJsonWithoutReplacingTarget(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"))
            path = os.path.join(directory, "tasks.json")
            valid_content = '{"tasks": [], "metadata": "keep"}'
            with open(path, "w", encoding="utf-8") as file:
                file.write(valid_content)

            with self.assertRaises(json.JSONDecodeError):
                broker.writeFileContent(FileRegistry.STANDALONE_TASKS_JSON, "not json")

            with open(path, encoding="utf-8") as file:
                self.assertEqual(file.read(), valid_content)

    def test_jsonUpdateRejectsNonStandardNumericConstantsInSource(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"))
            path = os.path.join(directory, "tasks.json")
            for constant in ("NaN", "Infinity", "-Infinity"):
                invalid_source = f'{{"tasks": [], "value": {constant}}}'
                with open(path, "w", encoding="utf-8") as file:
                    file.write(invalid_source)

                with self.assertRaisesRegex(ValueError, "non-finite JSON number"):
                    broker.updateFileContentJson(FileRegistry.STANDALONE_TASKS_JSON, lambda document: document)

                with open(path, encoding="utf-8") as file:
                    self.assertEqual(file.read(), invalid_source)

    def test_jsonUpdateRejectsNonFiniteResultWithoutReplacingTarget(self):
        with tempfile.TemporaryDirectory() as directory:
            broker = FileBroker(directory, directory, os.path.join(directory, "vault"))
            path = os.path.join(directory, "tasks.json")
            original = '{"tasks": []}'
            with open(path, "w", encoding="utf-8") as file:
                file.write(original)

            def add_non_finite(document):
                document["value"] = float("inf")
                return document

            with self.assertRaisesRegex(ValueError, "Out of range float values"):
                broker.updateFileContentJson(FileRegistry.STANDALONE_TASKS_JSON, add_non_finite)

            with open(path, encoding="utf-8") as file:
                self.assertEqual(file.read(), original)

    @patch("os.walk")
    @patch("os.path.getmtime")
    def test_getVaultFiles_WhenFilesExist_ThenReturnFilePathsAndModificationTimes(self, mock_getmtime, mock_walk):
        fakePath = self.vaultPath
        mock_walk.return_value = [
            (fakePath, ("subdir",), ("file1.txt", "file2.txt")),
            (os.path.join(fakePath, "subdir"), (), ("file3.txt",))
        ]
        mock_getmtime.side_effect = [1000.0, 2000.0, 3000.0]

        expected_files = [
            (os.path.join("file1.txt"), 1000.0),
            (os.path.join("file2.txt"), 2000.0),
            (os.path.join("subdir", "file3.txt"), 3000.0)
        ]

        files = self.fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)
        self.assertEqual(files, expected_files)

    @patch("os.walk")
    def test_getVaultFiles_WhenNoFilesExist_ThenReturnEmptyList(self, mock_walk):
        mock_walk.return_value = []

        files = self.fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)
        self.assertEqual(files, [])

    @patch("os.walk")
    @patch("os.path.getmtime")
    def test_getVaultFiles_skipsFilesRemovedAfterDirectoryEnumeration(self, mock_getmtime, mock_walk):
        mock_walk.return_value = [(self.vaultPath, (), ("present.md", "removed.md"))]
        mock_getmtime.side_effect = [1000.0, FileNotFoundError]

        files = self.fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)

        self.assertEqual(files, [("present.md", 1000.0)])

    def test_getVaultFiles_ignoresTemporaryFilesWhileAWriteIsStaged(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = os.path.join(directory, "vault")
            os.makedirs(vault)
            broker = FileBroker(directory, directory, vault)
            path = os.path.join(vault, "note.md")
            replacement_started = threading.Event()
            allow_replace = threading.Event()
            original_replace = os.replace
            errors = []

            def blocked_replace(source, destination):
                replacement_started.set()
                if not allow_replace.wait(5):
                    raise TimeoutError("test did not release replacement")
                original_replace(source, destination)

            def write_note():
                try:
                    broker.writeVaultFileLines(VaultRegistry.OBSIDIAN, "note.md", ["complete\n"])
                except Exception as error:
                    errors.append(error)

            with patch("src.AtomicFileStore.os.replace", side_effect=blocked_replace):
                writer = threading.Thread(target=write_note)
                writer.start()
                self.assertTrue(replacement_started.wait(5))
                self.assertEqual(broker.getVaultFiles(VaultRegistry.OBSIDIAN), [])
                allow_replace.set()
                writer.join(5)

            self.assertFalse(writer.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual([path for path, _ in broker.getVaultFiles(VaultRegistry.OBSIDIAN)], ["note.md"])

    @patch("builtins.open", new_callable=mock_open, read_data="line1\nline2\nline3\n")
    def test_getVaultFileLines_WhenFileExists_ThenReturnFileLines(self, mock_file):
        lines = self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, "testfile.md")
        self.assertEqual(lines, ["line1\n", "line2\n", "line3\n"])
        filePath = os.path.join(self.vaultPath, "testfile.md")
        mock_file.assert_called_once_with(filePath, "r", encoding="utf-8", newline="")

    @patch("builtins.open", side_effect=FileNotFoundError)
    def test_getVaultFileLines_WhenFileDoesNotExist_ThenRaiseFileNotFoundError(self, mock_file):
        with self.assertRaises(FileNotFoundError):
            self.fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, "nonexistentfile.md")
        filePath = os.path.join(self.vaultPath, "nonexistentfile.md")
        mock_file.assert_called_once_with(filePath, "r", encoding="utf-8", newline="")


if __name__ == "__main__":
    unittest.main()
