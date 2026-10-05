"""Persistent notification history behavior."""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest
from datetime import timedelta, timezone
from unittest.mock import patch
from uuid import UUID

from src.FileBroker import FileBroker
from src.MutationCoordinator import MutationCoordinator
from src.NotificationHistoryStore import (
    InvalidNotificationHistoryError,
    NotificationHistoryStore,
    NotificationHistoryUnavailableError,
    NotificationHistoryWriteError,
)


class NotificationHistoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.coordinator = MutationCoordinator()
        self.addCleanup(self.coordinator.close)
        self.file_broker = FileBroker(
            self.temp_directory.name,
            self.temp_directory.name,
            self.temp_directory.name,
            self.coordinator,
        )
        self.store = NotificationHistoryStore(
            self.file_broker,
            self.coordinator,
            "test-secret",
        )

    def test_read_missing_is_pure_and_initialize_creates_fresh_identity(self) -> None:
        path = self.store.path
        with self.assertRaises(NotificationHistoryUnavailableError):
            self.store.read()
        self.assertFalse(os.path.exists(path))

        initial = self.store.initialize()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(initial, self.store.initialize())

        self.store.append("saved")
        os.unlink(path)
        with self.assertRaises(NotificationHistoryUnavailableError):
            self.store.read()
        self.assertFalse(os.path.exists(path))

        recreated = self.store.initialize()
        self.assertNotEqual(initial.history_id, recreated.history_id)
        self.assertEqual(1, recreated.next_sequence)
        self.assertEqual((), recreated.entries)

    def test_append_persists_offset_and_sanitizes_secrets(self) -> None:
        self.store.initialize()
        timestamp = datetime.datetime(
            2026, 3, 29, 3, 30, tzinfo=timezone(timedelta(hours=2))
        )
        text = (
            "Entrega lista con [redactado]; token=test-secret; "
            "Authorization: Bearer credential-value\n"
            "URL https://example.test/item?access_token=hidden"
        )

        first = self.store.append(text, timestamp=timestamp)
        second = self.store.append(text, timestamp=timestamp)
        snapshot = self.store.read()

        self.assertEqual(1, first.sequence)
        self.assertEqual(2, second.sequence)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(timestamp.isoformat(), first.timestamp)
        self.assertEqual(3, snapshot.next_sequence)
        self.assertIn("[redactado]", first.text)
        self.assertNotIn("test-secret", first.text)
        self.assertNotIn("credential-value", first.text)
        self.assertNotIn("example.test", first.text)

    def test_read_sanitizes_restored_text_without_changing_file(self) -> None:
        initialized = self.store.initialize().to_dict()
        initialized["entries"] = [{
            "id": f"{initialized['historyId']}:1",
            "sequence": 1,
            "timestamp": "2026-03-29T03:30:00+02:00",
            "text": "restored token=test-secret",
        }]
        initialized["nextSequence"] = 2
        raw = json.dumps(initialized, separators=(",", ":")).encode("utf-8")
        with open(self.store.path, "wb") as history_file:
            history_file.write(raw)
        before = os.stat(self.store.path)

        snapshot = self.store.read()
        after = os.stat(self.store.path)

        self.assertEqual("restored token=[redactado]", snapshot.entries[0].text)
        self.assertEqual(raw, self._read_bytes())
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)

    def test_restart_keeps_identity_and_sequence_and_renew_reidentifies_entries(self) -> None:
        original = self.store.initialize()
        self.store.append("same text")
        self.store.append("same text")
        restarted = NotificationHistoryStore(
            self.file_broker,
            self.coordinator,
            "test-secret",
        )

        before_renewal = restarted.read()
        renewed = restarted.renew_history_id()
        after_append = restarted.append("same text")

        self.assertEqual(original.history_id, before_renewal.history_id)
        self.assertNotEqual(before_renewal.history_id, renewed.history_id)
        self.assertEqual(before_renewal.next_sequence, renewed.next_sequence)
        self.assertEqual(before_renewal.discarded_through, renewed.discarded_through)
        self.assertEqual([1, 2], [entry.sequence for entry in renewed.entries])
        self.assertTrue(all(
            entry.id.startswith(f"{renewed.history_id}:")
            for entry in renewed.entries
        ))
        self.assertEqual(3, after_append.sequence)
        self.assertTrue(after_append.id.startswith(f"{renewed.history_id}:"))
        self.assertEqual(str(UUID(renewed.history_id)), renewed.history_id)

    def test_invalid_existing_file_is_preserved_on_initialize_and_read(self) -> None:
        path = self.store.path
        raw = b'{"schemaVersion":1.0,"historyId":"invalid"}'
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as history_file:
            history_file.write(raw)

        with self.assertRaises(InvalidNotificationHistoryError):
            self.store.initialize()
        with self.assertRaises(InvalidNotificationHistoryError):
            self.store.read()
        self.assertEqual(raw, self._read_bytes())

    def test_atomic_failures_report_known_and_unknown_effects(self) -> None:
        self.store.initialize()
        before_write = self._read_bytes()
        with patch(
            "src.AtomicFileStore.os.replace",
            side_effect=OSError("private path and token=test-secret"),
        ):
            with self.assertRaises(NotificationHistoryWriteError) as before:
                self.store.append("not confirmed")

        self.assertEqual("unknown", before.exception.effects_state)
        self.assertEqual("replace", before.exception.phase)
        self.assertIsNone(before.exception.write_replaced)
        self.assertEqual(before_write, self._read_bytes())

        with patch.object(
            self.store._atomic_file_store,
            "_fsync_directory",
            side_effect=OSError("private path and token=test-secret"),
        ):
            with self.assertRaises(NotificationHistoryWriteError) as after:
                self.store.append("published but unconfirmed")

        self.assertEqual("unknown", after.exception.effects_state)
        self.assertEqual("directory_fsync", after.exception.phase)
        self.assertTrue(after.exception.write_replaced)
        self.assertEqual(
            "published but unconfirmed",
            self.store.read().entries[-1].text,
        )

    def test_history_retains_only_the_latest_1024_entries(self) -> None:
        initialized = self.store.initialize()
        history = {
            "schemaVersion": 1,
            "historyId": initialized.history_id,
            "nextSequence": 1025,
            "discardedThrough": 0,
            "entries": [
                {
                    "id": f"{initialized.history_id}:{sequence}",
                    "sequence": sequence,
                    "timestamp": "2026-03-29T03:30:00+02:00",
                    "text": f"notice {sequence}",
                }
                for sequence in range(1, 1025)
            ],
        }
        with open(self.store.path, "w", encoding="utf-8") as history_file:
            json.dump(history, history_file, separators=(",", ":"))

        entry = self.store.append("notice 1025")

        snapshot = self.store.read()
        self.assertEqual(1025, entry.sequence)
        self.assertEqual(initialized.history_id, snapshot.history_id)
        self.assertEqual(1026, snapshot.next_sequence)
        self.assertEqual(1, snapshot.discarded_through)
        self.assertEqual(1024, len(snapshot.entries))
        self.assertEqual(2, snapshot.entries[0].sequence)
        self.assertEqual(1025, snapshot.entries[-1].sequence)

    def _read_bytes(self) -> bytes:
        with open(self.store.path, "rb") as history_file:
            return history_file.read()


if __name__ == "__main__":
    unittest.main()
