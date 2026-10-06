import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock, patch
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import (
    ObsidianVaultTaskJsonProvider,
    SnapshotRefreshRequiredError,
)
from src.Interfaces.IFileBroker import IFileBroker, VaultRegistry
from src.wrappers.TimeManagement import TimePoint
from src.Utils import TaskDiscoveryPolicies
from src.taskmodels.TaskIdentity import fallback_task_id
from src.taskproviders.TaskIdentityErrors import AmbiguousTaskIdentityError, InvalidTaskIdentityError


class TestObsidianVaultTaskJsonProvider(unittest.TestCase):

    def setUp(self):
        self.mock_file_broker = MagicMock(spec=IFileBroker)
        self.policies = TaskDiscoveryPolicies(
            context_missing_policy="0",
            date_missing_policy="0",
            default_context="inbox",
            categories_prefixes=["work"]
        )
        self.provider = ObsidianVaultTaskJsonProvider(
            self.mock_file_broker,
            self.policies,
            auto_start=False,
            disableThreading=True,
        )

        def update_vault_lines(registry, path, updater):
            current = list(self.mock_file_broker.getVaultFileLines(registry, path))
            updated = updater(current)
            self.mock_file_broker.writeVaultFileLines(registry, path, list(updated))
            self.mock_file_broker.getVaultFileLines.return_value = list(updated)
            return list(updated)

        self.mock_file_broker.updateVaultFileLines.side_effect = update_vault_lines

    def test_empty_vault_returns_empty_task_and_project_lists(self):
        self.mock_file_broker.getVaultFiles.return_value = []
        result = self.provider.getJson()
        self.assertEqual(result, {"tasks": [], "projects": []})
        self.mock_file_broker.getVaultFiles.assert_called_once_with(VaultRegistry.OBSIDIAN)

    def test_default_refresh_is_async_and_first_read_is_explicitly_not_ready(self):
        read_started = Event()
        release_read = Event()
        published = Event()
        refresh_completed = Event()
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: (read_started.set(), release_read.wait(5), [])[2]
        provider = ObsidianVaultTaskJsonProvider(
            self.mock_file_broker,
            self.policies,
        )
        provider.registerSnapshotUpdatedCallback(published.set)
        provider.registerRefreshCompletedCallback(refresh_completed.set)
        try:
            with self.assertRaisesRegex(Exception, "still loading"):
                provider.getJson()
            self.assertTrue(read_started.wait(5))
            self.assertFalse(provider.isReady())
            release_read.set()
            self.assertTrue(published.wait(5))
            self.assertTrue(refresh_completed.wait(5))
            self.assertTrue(provider.isReady())
            self.assertEqual(provider.getJson(), {"tasks": [], "projects": []})
        finally:
            release_read.set()
            provider.stop()

    def test_concurrent_refresh_requests_share_the_in_flight_scan(self):
        read_started = Event()
        release_read = Event()
        published = Event()
        inventories = 0

        def inventory(_):
            nonlocal inventories
            inventories += 1
            if inventories == 1:
                read_started.set()
                release_read.wait(5)
            return []

        self.mock_file_broker.getVaultFiles.side_effect = inventory
        provider = ObsidianVaultTaskJsonProvider(self.mock_file_broker, self.policies)
        provider.registerSnapshotUpdatedCallback(published.set)
        try:
            self.assertTrue(read_started.wait(5))
            for _ in range(20):
                provider.requestRefresh()
            release_read.set()
            self.assertTrue(published.wait(5))
            self.assertEqual(inventories, 1)
        finally:
            release_read.set()
            provider.stop()

    def test_refresh_completed_callback_ignores_local_patches_and_failed_scans(self):
        self.mock_file_broker.getVaultFiles.return_value = []
        provider = ObsidianVaultTaskJsonProvider(
            self.mock_file_broker,
            self.policies,
            auto_start=False,
            disableThreading=True,
        )
        notifications: list[str] = []
        provider.registerRefreshCompletedCallback(lambda: notifications.append("refresh"))
        try:
            self.assertTrue(provider.refresh())
            self.assertEqual(notifications, ["refresh"])

            provider.publishConfirmedFile(
                "local.md",
                ["- [ ] Local patch [track::work] [id::local-patch]\n"],
            )
            self.assertEqual(notifications, ["refresh"])

            self.mock_file_broker.getVaultFiles.side_effect = OSError("scan failed")
            with self.assertRaisesRegex(OSError, "scan failed"):
                provider.refresh()
            self.assertEqual(notifications, ["refresh"])

            self.mock_file_broker.getVaultFiles.side_effect = None
            self.mock_file_broker.getVaultFiles.return_value = []
            self.assertTrue(provider.refresh())
            self.assertEqual(notifications, ["refresh", "refresh"])
        finally:
            provider.stop()

    def test_stop_during_file_read_is_bounded_and_scan_cannot_publish(self):
        read_started = Event()
        release_read = Event()
        published = Event()
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 1.0)]

        def read_lines(_, __):
            read_started.set()
            release_read.wait(5)
            return ["- [ ] Late [track::work] [id::late-task]\n"]

        self.mock_file_broker.getVaultFileLines.side_effect = read_lines
        provider = ObsidianVaultTaskJsonProvider(self.mock_file_broker, self.policies)
        provider.registerSnapshotUpdatedCallback(published.set)
        self.assertTrue(read_started.wait(5))
        provider.stop(timeout=0.01)
        self.assertFalse(provider.isReady())
        release_read.set()
        provider.stop(timeout=2)
        self.assertFalse(published.is_set())
        self.assertFalse(provider.isReady())

    def test_repeated_local_patches_keep_overlays_flat_and_old_handles_stable(self):
        contents = ["- [ ] Title 0 [track::work] [id::stable-id]\n"]
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 1.0)]
        self.mock_file_broker.getVaultFileLines.side_effect = lambda _, __: list(contents)
        provider = ObsidianVaultTaskJsonProvider(
            self.mock_file_broker,
            self.policies,
            auto_start=False,
            disableThreading=True,
        )
        original = provider.getReadSnapshot()

        for index in range(1, 1102):
            contents[:] = [f"- [ ] Title {index} [track::work] [id::stable-id]\n"]
            provider.publishConfirmedFile("tasks.md", contents)

        current = provider.getReadSnapshot()
        self.assertEqual(current.getTaskById("stable-id")["taskText"], "Title 1101")
        self.assertEqual(original.getTaskById("stable-id")["taskText"], "Title 0")
        self.assertGreater(current.generation, original.generation)

    def test_local_patch_preserves_existing_vault_task_order(self):
        contents = {
            "z-first.md": ["- [ ] First [track::work] [id::first-id]\n"],
            "a-second.md": ["- [ ] Second [track::work] [id::second-id]\n"],
        }
        self.mock_file_broker.getVaultFiles.return_value = [
            ("z-first.md", 1.0),
            ("a-second.md", 2.0),
        ]
        self.mock_file_broker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])
        provider = ObsidianVaultTaskJsonProvider(
            self.mock_file_broker,
            self.policies,
            auto_start=False,
            disableThreading=True,
        )
        self.assertEqual(
            [row["id"] for row in provider.getJson()["tasks"]],
            ["first-id", "second-id"],
        )

        contents["z-first.md"] = ["- [ ] First updated [track::work] [id::first-id]\n"]
        provider.publishConfirmedFile("z-first.md", contents["z-first.md"])

        self.assertEqual(
            [row["id"] for row in provider.getJson()["tasks"]],
            ["first-id", "second-id"],
        )

    def test_getJson_reuses_unchanged_file_parse_without_discovery(self):
        self.mock_file_broker.getVaultFiles.return_value = [("test.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = ["---", "---"]
        self.provider.getJson()

        self.mock_file_broker.getVaultFileLines.reset_mock()
        self.provider.getJson()
        self.mock_file_broker.getVaultFileLines.assert_not_called()

    def test_getJson_cache_tracks_inventory_mtime_and_returns_detached_results(self):
        files = [("one.md", 100.0), ("two.md", 100.0)]
        contents = {
            "one.md": ["---", "project: open", "---", "- [ ] One [track::work]"],
            "two.md": ["---", "project: open", "---", "- [x] Two [track::work]"],
            "three.md": ["- [ ] Three [track::work]"],
        }
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)
        self.mock_file_broker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])

        first = self.provider.getJson()
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 2)
        self.assertEqual([task["taskText"] for task in first["tasks"]], ["One", "Two"])
        self.assertEqual(first["tasks"][1]["status"], "x")
        self.assertEqual([project["path"] for project in first["projects"]], ["one.md", "two.md"])
        first["tasks"][0]["taskText"] = "poisoned caller result"
        first["projects"][0]["status"] = "held"

        self.mock_file_broker.getVaultFileLines.reset_mock()
        self.mock_file_broker.getVaultFiles.reset_mock()
        unchanged = self.provider.getJson()
        self.mock_file_broker.getVaultFiles.assert_not_called()
        self.mock_file_broker.getVaultFileLines.assert_not_called()
        self.assertEqual(unchanged["tasks"][0]["taskText"], "One")
        self.assertEqual(unchanged["projects"][0]["status"], "open")

        contents["one.md"] = ["---", "project: closed", "---", "- [x] One [track::work]"]
        files = [("one.md", 101.0), ("three.md", 100.0)]
        self.mock_file_broker.getVaultFiles.reset_mock()
        self.provider.refresh()
        changed = self.provider.getJson()
        self.assertEqual(
            [call.args[1] for call in self.mock_file_broker.getVaultFileLines.call_args_list],
            ["one.md", "three.md"],
        )
        self.mock_file_broker.getVaultFiles.assert_called_once_with(VaultRegistry.OBSIDIAN)
        self.assertEqual([task["taskText"] for task in changed["tasks"]], ["One", "Three"])
        self.assertEqual(changed["tasks"][0]["status"], "x")
        self.assertEqual(changed["projects"], [{"name": "one", "status": "closed", "path": "one.md"}])

        # A rename is a new path even when the replacement has the old mtime;
        # deleted paths disappear from the snapshot and unchanged paths reuse
        # their parsed values.
        contents["renamed.md"] = ["---", "project: open", "---", "- [x] Renamed [track::work]"]
        files = [("one.md", 101.0), ("renamed.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.reset_mock()
        self.mock_file_broker.getVaultFiles.reset_mock()
        self.provider.refresh()
        renamed = self.provider.getJson()
        self.assertEqual(
            [call.args[1] for call in self.mock_file_broker.getVaultFileLines.call_args_list],
            ["renamed.md"],
        )
        self.mock_file_broker.getVaultFiles.assert_called_once_with(VaultRegistry.OBSIDIAN)
        self.assertEqual([task["taskText"] for task in renamed["tasks"]], ["One", "Renamed"])
        self.assertEqual(renamed["tasks"][1]["status"], "x")
        self.assertEqual(
            [(project["path"], project["status"]) for project in renamed["projects"]],
            [("one.md", "closed"), ("renamed.md", "open")],
        )

    def test_identity_snapshot_reuses_parse_and_keeps_invalid_metadata_ids_reserved(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "- [ ] Valid task [track::work] [id::valid-id]",
            "- [x] Invalid task [track::work] [severity::bad] [id::reserved-id]",
        ]

        parsed = self.provider.getJson()
        self.assertEqual([task["id"] for task in parsed["tasks"]], ["valid-id"])
        self.mock_file_broker.getVaultFileLines.reset_mock()

        identities = self.provider.getTaskIdentitySnapshot()

        self.assertEqual(
            identities,
            [
                {"id": "valid-id", "file": "tasks.md", "line": 0},
                {"id": "reserved-id", "file": "tasks.md", "line": 1},
            ],
        )
        self.mock_file_broker.getVaultFiles.assert_called_with(VaultRegistry.OBSIDIAN)
        self.mock_file_broker.getVaultFileLines.assert_not_called()

    def test_identity_snapshot_reloads_only_changed_and_added_files(self):
        files = [("one.md", 100.0), ("two.md", 100.0)]
        contents = {
            "one.md": ["- [ ] One [track::work] [id::one]"],
            "two.md": ["- [ ] Two [track::work] [id::two]"],
            "three.md": ["- [x] Three [track::work] [id::three]"],
        }
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)
        self.mock_file_broker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])
        self.provider.getJson()

        contents["two.md"] = ["- [ ] Two updated [track::work] [id::two-updated]"]
        files[:] = [("two.md", 101.0), ("three.md", 102.0)]
        self.mock_file_broker.getVaultFileLines.reset_mock()
        self.provider.refresh()

        identities = self.provider.getTaskIdentitySnapshot()

        self.assertEqual(
            identities,
            [
                {"id": "two-updated", "file": "two.md", "line": 0},
                {"id": "three", "file": "three.md", "line": 0},
            ],
        )
        self.assertEqual(
            [call.args[1] for call in self.mock_file_broker.getVaultFileLines.call_args_list],
            ["two.md", "three.md"],
        )

    def test_getJson_refreshes_default_dates_when_local_day_changes(self):
        self.mock_file_broker.getVaultFiles.return_value = [("today.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = ["- [ ] Today [track::work]"]
        first_day = TimePoint.from_string("2026-10-06")
        next_day = TimePoint.from_string("2026-10-07")

        with patch.object(TimePoint, "today", return_value=first_day):
            first = self.provider.getJson()
        with patch.object(TimePoint, "today", return_value=next_day):
            self.provider.refresh()
            next_snapshot = self.provider.getJson()

        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 2)
        self.assertEqual(first["tasks"][0]["starts"], str(first_day.as_int()))
        self.assertEqual(first["tasks"][0]["due"], str(first_day.as_int()))
        self.assertEqual(next_snapshot["tasks"][0]["starts"], str(next_day.as_int()))
        self.assertEqual(next_snapshot["tasks"][0]["due"], str(next_day.as_int()))

    def test_failed_changed_file_read_does_not_publish_partial_snapshot(self):
        files = [("tasks.md", 100.0)]
        contents = ["- [ ] Original [track::work]"]
        fail_read = False
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)

        def read_lines(_, path):
            if fail_read:
                raise OSError("temporary read failure")
            return list(contents)

        self.mock_file_broker.getVaultFileLines.side_effect = read_lines
        original = self.provider.getJson()
        self.assertEqual(original["tasks"][0]["taskText"], "Original")

        files = [("tasks.md", 101.0)]
        contents[:] = ["- [ ] Updated [track::work]"]
        fail_read = True
        with self.assertRaisesRegex(OSError, "temporary read failure"):
            self.provider.refresh()
        self.assertEqual(self.provider.getJson()["tasks"][0]["taskText"], "Original")

        fail_read = False
        self.provider.refresh()
        recovered = self.provider.getJson()
        self.assertEqual(recovered["tasks"][0]["taskText"], "Updated")
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 3)

    def test_refresh_started_before_local_commit_cannot_publish_over_it(self):
        contents = ["- [ ] Before [track::work]"]
        read_started = Event()
        release_read = Event()
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]

        def read_lines(_, __):
            snapshot = list(contents)
            read_started.set()
            if not release_read.wait(timeout=5):
                raise TimeoutError("test read barrier timed out")
            return snapshot

        self.mock_file_broker.getVaultFileLines.side_effect = read_lines
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending_read = executor.submit(self.provider.refresh)
            self.assertTrue(read_started.wait(timeout=5))
            contents[:] = ["- [ ] After [track::work]"]
            self.provider.publishConfirmedFile("tasks.md", contents)
            release_read.set()
            published = pending_read.result(timeout=5)

        self.assertFalse(published)
        fresh_result = self.provider.getJson()
        self.assertEqual(fresh_result["tasks"][0]["taskText"], "After")
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 2)

    def test_discovery_generates_initial_action_then_reuses_warm_snapshot(self):
        files = [("project.md", 100.0)]
        contents = {"project.md": ["---", "project: open", "track: work", "---", "# Project"]}
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)
        self.mock_file_broker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])

        def update_lines(_, path, updater):
            updated = updater(list(contents[path]))
            contents[path] = list(updated)
            files[:] = [(current_path, mtime + 1.0 if current_path == path else mtime) for current_path, mtime in files]
            return list(updated)

        self.mock_file_broker.updateVaultFileLines.side_effect = update_lines

        first = self.provider.discover()
        self.assertEqual(
            [task["taskText"] for task in first["tasks"]],
            ["Define next action"],
        )
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 2)

        self.mock_file_broker.getVaultFileLines.reset_mock()
        second = self.provider.discover()
        self.assertEqual([task["taskText"] for task in second["tasks"]], ["Define next action"])
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 1)

        self.mock_file_broker.getVaultFiles.reset_mock()
        self.mock_file_broker.getVaultFileLines.reset_mock()
        third = self.provider.discover()
        self.assertEqual([task["taskText"] for task in third["tasks"]], ["Define next action"])
        self.mock_file_broker.getVaultFiles.assert_not_called()
        self.assertEqual(self.mock_file_broker.getVaultFileLines.call_count, 1)

    def test_failed_discovery_is_retried_and_changed_project_still_gets_action(self):
        files = [("existing.md", 100.0), ("new.md", 200.0)]
        contents = {
            "existing.md": [
                "---", "project: open", "track: work", "---",
                "- [ ] Existing [track::work]",
            ],
            "new.md": ["---", "project: closed", "track: work", "---", "# New project"],
        }
        fail_new_project_read = False
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)

        def read_lines(_, path):
            if path == "new.md" and fail_new_project_read:
                raise OSError("temporary project read failure")
            return list(contents[path])

        def update_lines(_, path, updater):
            updated = updater(list(contents[path]))
            contents[path] = list(updated)
            files[:] = [(current_path, mtime + 1.0 if current_path == path else mtime) for current_path, mtime in files]
            return list(updated)

        self.mock_file_broker.getVaultFileLines.side_effect = read_lines
        self.mock_file_broker.updateVaultFileLines.side_effect = update_lines
        self.provider.discover()

        contents["new.md"] = ["---", "project: open", "track: work", "---", "# New project"]
        files[:] = [(path, mtime + 1.0 if path == "new.md" else mtime) for path, mtime in files]
        self.provider.refresh()  # The next completed refresh publishes external changes.
        fail_new_project_read = True
        with self.assertRaisesRegex(OSError, "temporary project read failure"):
            self.provider.discover()

        fail_new_project_read = False
        self.mock_file_broker.getVaultFileLines.reset_mock()
        retried = self.provider.discover()

        self.assertTrue(any(task["file"] == "new.md" and task["taskText"] == "Define next action" for task in retried["tasks"]))
        self.assertGreater(self.mock_file_broker.getVaultFileLines.call_count, 0)

    def test_external_project_added_during_discovery_is_reconciled_next_time(self):
        files = [("existing.md", 100.0)]
        contents = {
            "existing.md": [
                "---", "project: open", "track: work", "---",
                "- [ ] Existing [track::work]",
            ],
            "new.md": ["---", "project: open", "track: work", "---", "# New project"],
        }
        external_change_added = False
        self.mock_file_broker.getVaultFiles.side_effect = lambda _: list(files)

        def read_lines(_, path):
            nonlocal external_change_added
            if path == "existing.md" and not external_change_added:
                files.append(("new.md", 200.0))
                external_change_added = True
            return list(contents[path])

        def update_lines(_, path, updater):
            updated = updater(list(contents[path]))
            contents[path] = list(updated)
            files[:] = [(current_path, mtime + 1.0 if current_path == path else mtime) for current_path, mtime in files]
            return list(updated)

        self.mock_file_broker.getVaultFileLines.side_effect = read_lines
        self.mock_file_broker.updateVaultFileLines.side_effect = update_lines

        self.provider.discover()
        self.provider.refresh()
        retried = self.provider.discover()

        self.assertTrue(any(task["file"] == "new.md" and task["taskText"] == "Define next action" for task in retried["tasks"]))

    def test_async_discovery_signals_retry_when_a_writer_invalidates_its_plan(self):
        project_lines = ["---\n", "project: open\n", "---\n", "# Empty project\n"]
        self.mock_file_broker.getVaultFiles.return_value = [("project.md", 1.0)]
        self.mock_file_broker.getVaultFileLines.return_value = list(project_lines)
        provider = ObsidianVaultTaskJsonProvider(
            self.mock_file_broker,
            self.policies,
            auto_start=False,
        )
        try:
            provider.refresh()
            self.mock_file_broker.getVaultFileLines.reset_mock()

            def invalidate_plan(_, __):
                provider.publishConfirmedFile(
                    "outside.md",
                    ["- [ ] Concurrent task [track::work] [id::concurrent-task]\n"],
                )
                return list(project_lines)

            self.mock_file_broker.getVaultFileLines.side_effect = invalidate_plan
            with patch.object(provider, "requestRefresh") as request_refresh:
                with self.assertRaises(SnapshotRefreshRequiredError):
                    provider.discover()

            request_refresh.assert_called_once_with()
            self.mock_file_broker.updateVaultFileLines.assert_not_called()
        finally:
            provider.stop()

    def test_discovery_never_pairs_old_generation_with_epoch_of_unpublished_commit(self):
        project_lines = [
            "---\n",
            "project: open\n",
            "---\n",
            "- [ ] Existing action [track::work] [id::existing-action]\n",
        ]
        self.mock_file_broker.getVaultFiles.return_value = [("project.md", 1.0)]
        self.mock_file_broker.getVaultFileLines.return_value = list(project_lines)
        provider = ObsidianVaultTaskJsonProvider(
            self.mock_file_broker,
            self.policies,
            auto_start=False,
        )
        build_started = Event()
        release_build = Event()
        try:
            provider.refresh()
            original_build_file_snapshot = getattr(
                provider,
                "_ObsidianVaultTaskJsonProvider__build_file_snapshot",
            )

            def block_commit_materialization(relative_path, lines, signature, *, cancel_if_stopping=False):
                if relative_path == "outside.md":
                    build_started.set()
                    if not release_build.wait(timeout=5):
                        raise TimeoutError("test commit materialization barrier timed out")
                return original_build_file_snapshot(
                    relative_path,
                    lines,
                    signature,
                    cancel_if_stopping=cancel_if_stopping,
                )

            with patch.object(
                provider,
                "_ObsidianVaultTaskJsonProvider__build_file_snapshot",
                side_effect=block_commit_materialization,
            ), ThreadPoolExecutor(max_workers=1) as executor:
                pending_commit = executor.submit(
                    provider.publishConfirmedFile,
                    "outside.md",
                    ["- [ ] Concurrent task [track::work] [id::concurrent-task]\n"],
                )
                self.assertTrue(build_started.wait(timeout=5))
                with patch.object(provider, "requestRefresh") as request_refresh:
                    with self.assertRaises(SnapshotRefreshRequiredError):
                        provider.discover()
                request_refresh.assert_called_once_with()
                release_build.set()
                pending_commit.result(timeout=5)

            self.assertEqual(
                [task["id"] for task in provider.getReadSnapshot().getTasks()],
                ["existing-action", "concurrent-task"],
            )
        finally:
            release_build.set()
            provider.stop()

    def test_async_discovery_checks_writer_epoch_when_no_maintenance_is_needed(self):
        project_lines = [
            "---\n",
            "project: open\n",
            "---\n",
            "- [ ] Existing action [track::work] [id::existing-action]\n",
        ]
        self.mock_file_broker.getVaultFiles.return_value = [("project.md", 1.0)]
        self.mock_file_broker.getVaultFileLines.return_value = list(project_lines)
        provider = ObsidianVaultTaskJsonProvider(
            self.mock_file_broker,
            self.policies,
            auto_start=False,
        )
        try:
            provider.refresh()
            self.mock_file_broker.getVaultFileLines.reset_mock()

            def invalidate_plan(_, __):
                provider.publishConfirmedFile(
                    "outside.md",
                    ["- [ ] Concurrent task [track::work] [id::concurrent-task]\n"],
                )
                return list(project_lines)

            self.mock_file_broker.getVaultFileLines.side_effect = invalidate_plan
            with patch.object(provider, "requestRefresh") as request_refresh:
                with self.assertRaises(SnapshotRefreshRequiredError):
                    provider.discover()

            request_refresh.assert_called_once_with()
            self.mock_file_broker.updateVaultFileLines.assert_not_called()
        finally:
            provider.stop()

    def test_discovery_waits_for_refresh_when_a_commit_outcome_is_uncertain(self):
        project_lines = ["---\n", "project: open\n", "---\n", "# Empty project\n"]
        self.mock_file_broker.getVaultFiles.return_value = [("project.md", 1.0)]
        self.mock_file_broker.getVaultFileLines.return_value = list(project_lines)
        provider = ObsidianVaultTaskJsonProvider(
            self.mock_file_broker,
            self.policies,
            auto_start=False,
        )
        try:
            provider.refresh()
            self.mock_file_broker.getVaultFileLines.reset_mock()
            commit_listener = getattr(
                provider,
                "_ObsidianVaultTaskJsonProvider__on_vault_file_commit",
            )
            commit_listener("project.md", None, None)
            self.assertTrue(provider.getRefreshStatus()["needs_refresh"])

            with patch.object(provider, "requestRefresh") as request_refresh:
                with self.assertRaises(SnapshotRefreshRequiredError):
                    provider.discover()

            request_refresh.assert_called_once_with()
            self.mock_file_broker.getVaultFileLines.assert_not_called()
            self.mock_file_broker.updateVaultFileLines.assert_not_called()
        finally:
            provider.stop()

    def test_discovery_stops_preparing_between_project_reads(self):
        contents = {
            "first.md": ["---\n", "project: open\n", "---\n", "# First\n"],
            "second.md": ["---\n", "project: open\n", "---\n", "# Second\n"],
        }
        self.mock_file_broker.getVaultFiles.return_value = [
            ("first.md", 1.0),
            ("second.md", 2.0),
        ]
        self.mock_file_broker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])
        provider = ObsidianVaultTaskJsonProvider(
            self.mock_file_broker,
            self.policies,
            auto_start=False,
        )
        try:
            provider.refresh()
            self.mock_file_broker.getVaultFileLines.reset_mock()
            paths_read: list[str] = []

            def stop_after_first_read(_, path):
                paths_read.append(path)
                if len(paths_read) == 1:
                    provider.stop(timeout=0)
                return list(contents[path])

            self.mock_file_broker.getVaultFileLines.side_effect = stop_after_first_read
            provider.discover()

            self.assertEqual(paths_read, ["first.md"])
            self.mock_file_broker.updateVaultFileLines.assert_not_called()
        finally:
            provider.stop()

    def test_process_task_file_with_project_header(self):
        self.mock_file_broker.getVaultFiles.return_value = [("project.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "project: open",
            "---",
            "# Project Title"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["projects"]), 1)
        self.assertEqual(result["projects"][0]["name"], "project")
        self.assertEqual(result["projects"][0]["status"], "open")
        self.assertEqual(result["projects"][0]["path"], "project.md")

        # Reading parses the project but leaves next-action reconciliation to discover().
        self.assertEqual(len(result["tasks"]), 0)
        self.mock_file_broker.writeVaultFileLines.assert_not_called()

    def test_discover_persists_next_action_for_open_empty_project(self):
        files = [("project.md", 100.0)]
        contents = {"project.md": ["---\n", "project: open\n", "---\n", "# Project Title\n"]}
        self.mock_file_broker.getVaultFiles.return_value = files
        self.mock_file_broker.getVaultFileLines.side_effect = lambda registry, path: list(contents[path])

        def write_file(registry, path, lines):
            contents[path] = list(lines)

        self.mock_file_broker.writeVaultFileLines.side_effect = write_file

        result = self.provider.discover()

        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["taskText"], "Define next action")
        self.assertEqual(result["tasks"][0]["track"], "work")
        self.assertIn("Define next action", "".join(contents["project.md"]))
        self.assertIn(f"[id::{fallback_task_id('Define next action', 'project.md', 4)}]", contents["project.md"][4])
        self.mock_file_broker.updateVaultFileLines.assert_called_once()
        self.mock_file_broker.writeVaultFileLines.assert_called_once()

    def test_discover_rejects_a_generated_identifier_already_in_the_vault(self):
        duplicate_id = fallback_task_id("Define next action", "project.md", 4)
        files = [("project.md", 100.0), ("other.md", 200.0)]
        contents = {
            "project.md": ["---\n", "project: open\n", "---\n", "# Project\n"],
            "other.md": [f"- [ ] Existing [track::work] [id::{duplicate_id}]\n"],
        }
        self.mock_file_broker.getVaultFiles.return_value = files
        self.mock_file_broker.getVaultFileLines.side_effect = lambda _, path: list(contents[path])

        with self.assertRaises(AmbiguousTaskIdentityError):
            self.provider.discover()

        self.mock_file_broker.updateVaultFileLines.assert_not_called()
        self.mock_file_broker.writeVaultFileLines.assert_not_called()

    def test_process_task_with_metadata(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "---",
            "- [ ] Complete report [track::work] [start::2023-12-31] [due::2023-12-31] [severity::3] [remaining_cost::2] [invested::1]"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 1)
        task = result["tasks"][0]
        self.assertEqual(task["taskText"], "Complete report")
        self.assertEqual(task["due"], str(TimePoint.from_string("2023-12-31").as_int()))
        self.assertEqual(task["severity"], "3.0")
        self.assertEqual(task["remaining_cost"], "2")
        self.assertEqual(task["invested"], "1")
        self.assertEqual(task["total_cost"], "1.0")

    def test_invalid_task_is_skipped(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "---",
            "- [ ] Invalid task without track tag"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 0)

    def test_file_header_values_applied_to_tasks(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "severity: 5",
            "starts: 2023-01-01",
            "---",
            "- [ ] Task with header values [track::work]"
        ]

        result = self.provider.getJson()
        task = result["tasks"][0]
        self.assertEqual(task["severity"], "5.0")
        self.assertEqual(task["starts"], str(TimePoint.from_string("2023-01-01").as_int()))

    def test_file_header_accepts_double_colon_and_preserves_value_colons(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---\n",
            "project:: open\n",
            "track:: work\n",
            "severity:: 2\n",
            "remaining_cost:: 4\n",
            "invested:: 1\n",
            "starts: 2023-12-31T23:45\n",
            "source: https://example.test/a:b\n",
            "---\n",
            "- [ ] Task [due::2024-01-01]\n",
        ]

        result = self.provider.getJson()
        task = result["tasks"][0]

        self.assertEqual(task["track"], "work")
        self.assertEqual(task["severity"], "2.0")
        self.assertEqual(task["remaining_cost"], "4")
        self.assertEqual(task["invested"], "1")
        self.assertEqual(task["total_cost"], "3.0")
        self.assertEqual(task["starts"], str(TimePoint.from_string("2023-12-31T23:45").as_int()))
        self.assertEqual(task["source"], "https://example.test/a:b")
        self.assertEqual(result["projects"], [{"name": "tasks", "status": "open", "path": "tasks.md"}])

    def test_frontmatter_datetime_keeps_hour_and_minute_colons(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---\n",
            "project: open\n",
            "starts: 2023-12-31T23:45\n",
            "due: 2024-01-01T01:15\n",
            "---\n",
            "- [ ] Task [track::work]\n"
        ]

        task = self.provider.getJson()["tasks"][0]
        self.assertEqual(task["starts"], str(TimePoint.from_string("2023-12-31T23:45").as_int()))
        self.assertEqual(task["due"], str(TimePoint.from_string("2024-01-01T01:15").as_int()))

    def test_completed_checkbox_is_parsed_for_complete_task_queries(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---\n",
            "---\n",
            "- [x] Finished [track::work]\n"
        ]

        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["status"], "x")

    def test_task_line_identity_is_read_as_an_opaque_value(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---\n",
            "---\n",
            "- [ ] Task [track::work] [id::opaque/id:7] [extra:: keep]\n",
        ]

        task = self.provider.getJson()["tasks"][0]

        self.assertEqual(task["id"], "opaque/id:7")

    def test_empty_task_line_identity_is_rejected(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "- [ ] Task [track::work] [id::   ]\n",
        ]

        with self.assertRaises(InvalidTaskIdentityError):
            self.provider.getJson()

    def test_conflicting_task_line_identities_are_rejected(self):
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "- [ ] Task [track::work] [id::first] [id::second]\n",
        ]

        with self.assertRaises(InvalidTaskIdentityError):
            self.provider.getJson()

    def test_update_existing_task(self):
        # First call to add a task
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "- [ ] Task 1 [track::work]"
        ]
        self.provider.getJson()

        # Second call to update the same task
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 200.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "- [ ] Task 1 updated [track::work]"
        ]

        self.provider.refresh()
        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["taskText"], "Task 1 updated")

    def test_read_failure_during_file_processing_is_propagated(self):
        self.mock_file_broker.getVaultFiles.return_value = [("valid.md", 100.0), ("invalid.md", 200.0)]

        def mock_get_file_lines(registry, path):
            if path == "valid.md":
                return ["- [ ] Valid task [track::work]"]
            else:
                raise Exception("Test error")

        self.mock_file_broker.getVaultFileLines.side_effect = mock_get_file_lines

        # A failed read must not be reported as a successful partial/empty view.
        with self.assertRaisesRegex(Exception, "Test error"):
            self.provider.getJson()

    def test_saveJson_does_nothing(self):
        # saveJson should be a no-op
        self.provider.saveJson({"tasks": []})
        # No assertions needed as the method doesn't do anything

    def test_update_or_append_task_functionality(self):
        # Test that __update_or_append_task correctly updates or appends tasks
        # Create a task first
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 100.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "---",
            "- [ ] Task 1 [track::work] [severity::2]"
        ]

        self.provider.refresh()
        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["tasks"][0]["taskText"], "Task 1")
        self.assertEqual(result["tasks"][0]["severity"], "2.0")

        # Now add a new task with a different line and update the existing one
        self.mock_file_broker.getVaultFiles.return_value = [("tasks.md", 200.0)]
        self.mock_file_broker.getVaultFileLines.return_value = [
            "---",
            "---",
            "- [ ] Task 1 updated [track::work] [severity::3]",
            "- [ ] Task 2 [track::work]"
        ]

        self.provider.refresh()
        result = self.provider.getJson()
        self.assertEqual(len(result["tasks"]), 2)

        # Tasks should be ordered based on their order in the file
        self.assertEqual(result["tasks"][0]["taskText"], "Task 1 updated")
        self.assertEqual(result["tasks"][0]["severity"], "3.0")
        self.assertEqual(result["tasks"][1]["taskText"], "Task 2")


if __name__ == "__main__":
    unittest.main()
