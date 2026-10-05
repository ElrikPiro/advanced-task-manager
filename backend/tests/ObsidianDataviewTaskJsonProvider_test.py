import unittest
from unittest.mock import MagicMock

from src.Interfaces.IFileBroker import FileRegistry, IFileBroker, VaultRegistry
from src.taskjsonproviders.ObsidianDataviewTaskJsonProvider import ObsidianDataviewTaskJsonProvider
from src.taskproviders.TaskIdentityErrors import InvalidTaskIdentityError


class TestObsidianDataviewTaskJsonProvider(unittest.TestCase):
    def setUp(self):
        self.file_broker = MagicMock(spec=IFileBroker)
        self.provider = ObsidianDataviewTaskJsonProvider(self.file_broker)
        self.file_broker.readFileContentJson.return_value = {
            "tasks": [
                {
                    "taskText": "Task",
                    "track": "work",
                    "starts": "1",
                    "due": "2",
                    "severity": "1",
                    "total_cost": "1",
                    "effort_invested": "0",
                    "status": " ",
                    "file": "tasks.md",
                    "line": "2",
                    "calm": "false",
                }
            ]
        }

    def test_getJson_reads_the_current_identity_from_the_vault_line(self):
        self.file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.file_broker.getVaultFileLines.return_value = [
            "---\n",
            "---\n",
            "- [ ] Task [track::work] [id::stored-id]\n",
        ]

        result = self.provider.getJson()

        self.assertEqual(result["tasks"][0]["id"], "stored-id")
        self.file_broker.getVaultFiles.assert_called_once_with(VaultRegistry.OBSIDIAN)
        self.file_broker.getVaultFileLines.assert_called_once_with(VaultRegistry.OBSIDIAN, "tasks.md")
        self.file_broker.writeVaultFileLines.assert_not_called()
        self.file_broker.writeFileContentJson.assert_not_called()

    def test_getJson_rejects_a_snapshot_id_that_conflicts_with_the_vault(self):
        self.file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.file_broker.getVaultFileLines.return_value = [
            "# Header\n",
            "# Metadata\n",
            "- [ ] Task [track::work] [id::stored-id]\n",
            "- [ ] Other task [track::work] [id::snapshot-id]\n",
        ]
        self.file_broker.readFileContentJson.return_value["tasks"][0]["id"] = "snapshot-id"

        with self.assertRaises(InvalidTaskIdentityError):
            self.provider.getJson()

    def test_getJson_rejects_an_empty_identity_in_the_snapshot(self):
        self.file_broker.getVaultFiles.return_value = []
        self.file_broker.readFileContentJson.return_value["tasks"][0]["id"] = "  "

        with self.assertRaises(InvalidTaskIdentityError):
            self.provider.getJson()


if __name__ == "__main__":
    unittest.main()
