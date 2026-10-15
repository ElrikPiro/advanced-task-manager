"""Behavioral coverage for event-derived contexts and their read projections."""
import copy
import datetime
import unittest
from unittest.mock import MagicMock

from src.EffectiveContextResolver import EffectiveContextResolver
from src.TelegramTaskListManager import TelegramTaskListManager
from src.algorithms.GtdAlgorithm import GtdAlgorithm
from src.api.ApiResources import ApiResources
from src.domain.TaskApplicationService import TaskApplicationService
from src.domain.models import AgendaQuery, OperationResult, OperationTarget, TaskView
from src.filters.ActiveTaskFilter import ActiveTaskFilter
from src.filters.ContextPrefixTaskFilter import ContextPrefixTaskFilter
from src.taskmodels.TaskModel import TaskModel
from src.wrappers.TimeManagement import TimePoint


CATEGORIES = [{"prefix": prefix, "description": prefix} for prefix in ("alert", "billable", "work")]


def task(name, context="work", *, raised=None, waited=None, status=" ", start=0, calm="False"):
    return TaskModel(name, context, start, 0, 1, 1, 0, status, calm, "", 0,
                     raised, waited, task_id=name)


class EffectiveContextResolverTest(unittest.TestCase):
    def test_priority_replaces_even_a_better_original_and_returns_full_context(self):
        emitter = task("a", "alert", raised="E")
        receivers = [task("b", "work/desk", waited="E"), task("c", "billable/client", waited="E")]
        contexts = EffectiveContextResolver([emitter, *receivers], CATEGORIES)
        self.assertEqual(contexts.context(emitter), "billable/client")
        self.assertEqual(emitter.getContext(), "alert")
        self.assertEqual(EffectiveContextResolver([emitter, *receivers], list(reversed(CATEGORIES))).context(emitter), "work/desk")

    def test_fallback_completed_unknown_and_exact_events(self):
        emitter = task("a", raised="E")
        receivers = [task("b", "alert", waited="E", status="x"),
                     task("c", "unknown", waited="E"), task("d", "alert", waited="e")]
        self.assertEqual(EffectiveContextResolver([emitter, *receivers], CATEGORIES).context(emitter), "work")
        receivers.append(task("e", "alert", waited="E"))
        emitter.setStatus("x")
        self.assertEqual(EffectiveContextResolver([emitter, *receivers], CATEGORIES).context(emitter), "work")

    def test_stable_ties_overlapping_prefixes_and_multiple_emitters(self):
        a, b = task("a", raised="E"), task("b", raised="E")
        receivers = [task("c", "work/second", waited="E"), task("d", "work/first", waited="E")]
        categories = [{"prefix": "work"}, {"prefix": "work/first"}]
        contexts = EffectiveContextResolver([a, b, *receivers], categories)
        self.assertEqual([contexts.context(t) for t in (a, b)], ["work/second"] * 2)

    def test_self_exclusion_cycles_and_non_transitive_resolution(self):
        a = task("a", "alert", raised="E", waited="E")
        b = task("b", "billable/b", raised="F", waited="E")
        c = task("c", "work/c", raised="E", waited="F")
        contexts = EffectiveContextResolver([a, b, c], CATEGORIES)
        self.assertEqual(contexts.context(a), "billable/b")
        self.assertEqual(contexts.context(b), "work/c")
        self.assertEqual(contexts.context(c), "alert")
        self.assertEqual(contexts.context(copy.deepcopy(a)), "billable/b")
        self.assertEqual(EffectiveContextResolver([a], CATEGORIES).context(a), "alert")

    def test_next_query_reacts_to_changes_without_mutating_captured_values(self):
        a, b = task("a", raised="E"), task("b", "billable/b", waited="E")
        captured = EffectiveContextResolver([a, b], CATEGORIES)
        b.setContext("alert")
        self.assertEqual(captured.context(a), "billable/b")
        self.assertEqual(EffectiveContextResolver([a, b], CATEGORIES).context(a), "alert")
        b.setStatus("x")
        self.assertEqual(EffectiveContextResolver([a, b], CATEGORIES).context(a), "work")
        b.setStatus(" ")
        b.setEventWaited(None)
        self.assertEqual(EffectiveContextResolver([a, b], CATEGORIES).context(a), "work")

    def make_stack(self):
        a = task("emitter", "work", raised="E")
        b = task("receiver", "alert/client", waited="E", start=TimePoint.tomorrow().as_int())
        b._project = "Another project"
        other = task("other", "billable")
        active = ActiveTaskFilter()
        categories = [(c["prefix"], ContextPrefixTaskFilter(active, c["prefix"]), False) for c in CATEGORIES]
        statistics = MagicMock()
        heuristic = MagicMock()
        algorithm = GtdAlgorithm(categories, [], (heuristic, 0), statistics, heuristic)
        manager = TelegramTaskListManager([a, b, other], [("GTD Algorithm", algorithm)], [],
                                          [("All active task filter", active, True), *categories], statistics,
                                          categories=CATEGORIES)
        provider = MagicMock()
        # Plain provider with no indexed/snapshot capabilities.
        provider.getTaskList.return_value = [a, b, other]
        provider.isReady.return_value = True
        provider.getProjectionTaskListSnapshot = None
        provider.getTaskListSnapshot = None
        provider.getTaskById = None
        app = TaskApplicationService(provider, None, statistics, manager, CATEGORIES)
        return a, b, other, manager, app

    def test_list_filter_search_detail_agenda_and_gtd_share_complete_population(self):
        a, b, other, manager, app = self.make_stack()
        api = ApiResources(app)
        views = [TaskView(page_size=1, heuristic=""), TaskView(filters=("alert",), algorithm="", heuristic=""),
                 TaskView(search=("emitter",), heuristic=""), TaskView(filters=("All active task filter",), algorithm="GTD Algorithm", heuristic="")]
        for view in views:
            with self.subTest(view=view):
                entry = app.query_tasks(view).tasks[0]
                self.assertEqual((entry.id, entry.context, entry.originalContext), ("emitter", "alert/client", "work"))
                resource = api.read_tasks(view)["_embedded"]["tasks"][0]
                self.assertEqual((resource["context"], resource["originalContext"]), ("alert/client", "work"))
        self.assertEqual(api.read_task("emitter")["context"], "alert/client")
        self.assertEqual(app.read_task_information("emitter").task.context, "alert/client")
        agenda = api.read_agenda(AgendaQuery(day=TimePoint.today(), heuristic=""))
        self.assertEqual(agenda["_embedded"]["activeUrgentTasks"][0]["context"], "alert/client")
        self.assertEqual(manager.search_tasks(["emitter"]).get_task_list_content().tasks[0].context, "alert/client")
        self.assertEqual(manager.filtered_task_list, [a])
        self.assertEqual(a.getContext(), "work")
        b.setEventWaited(None)
        self.assertEqual(api.read_task("emitter")["context"], "work")

    def test_nested_operation_resources_use_one_complete_population(self):
        a, b, other, manager, app = self.make_stack()
        app._task_provider.getTaskList.reset_mock()
        result = OperationResult("edit-task", OperationTarget("task", "emitter"),
                                 [{"task": copy.deepcopy(a)}, copy.deepcopy(other)])
        document = ApiResources(app)._operation_result_representation(result)
        self.assertEqual(document["value"][0]["task"]["context"], "alert/client")
        self.assertEqual(document["value"][0]["task"]["originalContext"], "work")
        self.assertEqual(app._task_provider.getTaskList.call_count, 1)

    def test_inherited_category_does_not_remove_wait_start_or_calm_constraints(self):
        a, b, other, manager, app = self.make_stack()
        a.setStart(TimePoint(datetime.datetime(2099, 1, 1)))
        self.assertEqual(app.query_tasks(TaskView(filters=("alert",), algorithm="", heuristic="")).tasks, [])
        a.setStart(TimePoint(datetime.datetime(1970, 1, 1)))
        a.setEventWaited("another-event")
        self.assertEqual(app.query_tasks(TaskView(filters=("alert",), algorithm="", heuristic="")).tasks, [])
        a.setEventWaited(None)
        a.setCalm(True)
        self.assertEqual(app.query_tasks(TaskView(filters=("All active task filter",), algorithm="GTD Algorithm", heuristic="")).tasks[0].id, other.getTaskUID())


class EffectiveContextPersistenceTest(unittest.TestCase):
    def test_reads_and_edits_preserve_original_context_in_both_storage_formats(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import ApplicationReadIntegration_test as reads
        from src.FileBroker import FileBroker
        from src.Utils import TaskDiscoveryPolicies
        from src.domain.errors import ValidationError
        from src.domain.models import OperationTarget
        from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import ObsidianVaultTaskJsonProvider
        from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
        from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
        from src.taskproviders.TaskProvider import TaskProvider

        helper = reads.ApplicationReadIntegrationTest()
        for storage in ("json", "obsidian"):
            with self.subTest(storage=storage), helper._fixed_clock(), TemporaryDirectory() as temporary:
                root = Path(temporary)
                data, vault = root / "data", root / "vault"
                data.mkdir()
                vault.mkdir()
                if storage == "json":
                    rows = []
                    for name, context, raised, waited in (("emitter", "work", "E", None),
                                                          ("receiver", "alert", None, "E")):
                        row = helper._base_task(description=name, context=context, start=0, due=0, waited=waited)
                        row.update(id=name, raised=raised)
                        rows.append(row)
                    (data / "tasks.json").write_text(json.dumps({"tasks": rows, "projects": []}))
                else:
                    (vault / "Tasks.md").write_text(
                        "# Tasks\n"
                        "- [ ] emitter [track::work] [starts::2020-01-01] [due::2020-01-02] "
                        "[severity::1] [remaining_cost::1] [invested::0] [calm::false] [raised::E] [id::emitter]\n"
                        "- [ ] receiver [track::alert] [starts::2099-01-01] [due::2099-01-02] "
                        "[severity::1] [remaining_cost::1] [invested::0] [calm::false] [waited::E] [id::receiver]\n"
                    )
                broker = FileBroker(str(data), str(root / "appdata"), str(vault))
                if storage == "json":
                    provider = TaskProvider(TaskJsonProvider(broker), broker, disableThreading=True)
                    refresh = lambda: None
                else:
                    source = ObsidianVaultTaskJsonProvider(
                        broker, TaskDiscoveryPolicies("0", "0", "inbox", ["alert", "work", "home", "inbox"]),
                        auto_start=False,
                    )
                    source.refresh()
                    provider = ObsidianTaskProvider(source, broker, disableThreading=True)
                    refresh = source.refresh
                app, manager, statistics, algorithms = helper._create_query_stack(broker, provider)
                statistics.initialize()
                api = ApiResources(app)
                original = helper._snapshot(root)
                document = api.read_task("emitter")
                self.assertEqual((document["context"], document["originalContext"]), ("alert", "work"))
                self.assertEqual(helper._snapshot(root), original)
                app.edit_task("emitter", {"description": "Edited emitter"})
                refresh()
                self.assertEqual(app.read_task("emitter").getContext(), "work")
                self.assertEqual(api.read_task("emitter")["context"], "alert")
                app.edit_task("emitter", {"context": "home"})
                refresh()
                self.assertEqual(app.read_task("emitter").getContext(), "home")
                self.assertEqual(api.read_task("emitter")["context"], "alert")
                with self.assertRaises(ValidationError):
                    app.edit_task("emitter", {"originalContext": "work"})
                app.edit_task("receiver", {"context": "work/receiver"})
                refresh()
                self.assertEqual(api.read_task("emitter")["context"], "work/receiver")
                app.execute_operation("raise-event", OperationTarget("event", "E"), {})
                refresh()
                self.assertEqual(api.read_task("emitter")["context"], "home")
                app.edit_task("receiver", {"waited": "E"})
                refresh()
                self.assertEqual(api.read_task("emitter")["context"], "work/receiver")
                app.execute_operation("complete-task", OperationTarget("task", "receiver"), {})
                refresh()
                self.assertEqual(api.read_task("emitter")["context"], "home")
