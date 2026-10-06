from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import re
import math
from threading import Event, Lock, RLock, Thread, current_thread
from types import MappingProxyType
from typing import Callable, Generic, Iterator, Mapping, TypeVar, cast

from src.Utils import ProjectJsonListType, TaskDiscoveryPolicies, TaskJsonListType, TaskJsonType
from ..wrappers.TimeManagement import TimePoint
from ..Interfaces.ITaskJsonProvider import ITaskJsonProvider, VALID_PROJECT_STATUS
from ..Interfaces.IFileBroker import IFileBroker, VaultRegistry
from ..taskmodels.TaskIdentity import fallback_task_id, validate_task_id
from ..taskproviders.TaskIdentityErrors import (
    AmbiguousTaskIdentityError,
    InvalidTaskIdentityError,
    MissingTaskIdentityError,
)
from ..MutationCoordinator import MutationCoordinator


FileFingerprint = float | tuple[int, int, int, int]
_FrozenFields = tuple[tuple[str, str], ...]
_Value = TypeVar("_Value")


@dataclass(frozen=True)
class _OverlayMapping(Mapping[str, _Value], Generic[_Value]):
    """Small immutable write overlay over a generation mapping.

    A confirmed one-note write must not copy the vault-wide file or ID maps. The
    background full refresh periodically folds these overlays into a new base.
    """

    _base: Mapping[str, _Value] = field(init=False, repr=False)
    _updates: Mapping[str, _Value] = field(init=False, repr=False)
    _length: int = field(init=False, repr=False)

    def __init__(self, base: Mapping[str, _Value], updates: Mapping[str, _Value]):
        merged_updates = dict(updates)
        while isinstance(base, _OverlayMapping):
            overlay = cast(_OverlayMapping[_Value], base)
            for key, value in overlay._updates.items():
                merged_updates.setdefault(key, value)
            base = overlay._base
        immutable_updates = MappingProxyType(merged_updates)
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_updates", immutable_updates)
        object.__setattr__(
            self,
            "_length",
            len(base) + sum(1 for key in immutable_updates if key not in base),
        )

    def __getitem__(self, key: str) -> _Value:
        if key in self._updates:
            return self._updates[key]
        return self._base[key]

    def __iter__(self) -> Iterator[str]:
        for key in self._updates:
            yield key
        for key in self._base:
            if key not in self._updates:
                yield key

    def __len__(self) -> int:
        return self._length


@dataclass(frozen=True)
class _AggregateRows:
    """Frozen aggregate rows with bounded per-file deltas between full scans."""

    base: tuple[_FrozenFields, ...]
    overrides: Mapping[str, tuple[_FrozenFields, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    path_field: str = "file"
    file_order: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    file_row_counts: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))

    def __iter__(self) -> Iterator[_FrozenFields]:
        if not self.overrides:
            yield from self.base
            return
        replaced_files = self.overrides
        ordered_overrides = sorted(
            replaced_files,
            key=lambda path: (self.file_order.get(path, len(self.file_order)), path),
        )
        override_index = 0
        for row in self.base:
            row_file = dict(row).get(self.path_field, "")
            row_order = self.file_order.get(row_file, len(self.file_order))
            while override_index < len(ordered_overrides):
                path = ordered_overrides[override_index]
                path_order = self.file_order.get(path, len(self.file_order))
                if path_order > row_order:
                    break
                yield from replaced_files[path]
                override_index += 1
            if row_file not in replaced_files:
                yield row
        while override_index < len(ordered_overrides):
            yield from replaced_files[ordered_overrides[override_index]]
            override_index += 1

    @classmethod
    def from_files(
        cls,
        files: Mapping[str, _FileSnapshot],
        field_name: str,
        file_order: Mapping[str, int] | None = None,
    ) -> "_AggregateRows":
        rows: list[_FrozenFields] = []
        counts: dict[str, int] = {}
        if file_order is None:
            file_order = MappingProxyType({path: index for index, path in enumerate(files)})
        for relative_path, file_snapshot in files.items():
            rows.extend(getattr(file_snapshot, field_name))
            row_count = len(getattr(file_snapshot, field_name))
            if row_count:
                counts[relative_path] = row_count
        return cls(
            tuple(rows),
            path_field="path" if field_name == "projects" else "file",
            file_order=file_order,
            file_row_counts=MappingProxyType(counts),
        )

    def replace_file(self, relative_path: str, rows: tuple[_FrozenFields, ...]) -> "_AggregateRows":
        previous_count = self.file_row_counts.get(relative_path, 0)
        if not previous_count and not rows:
            return self
        updates = dict(self.overrides)
        updates[relative_path] = rows
        counts = dict(self.file_row_counts)
        if rows:
            counts[relative_path] = len(rows)
        else:
            counts.pop(relative_path, None)
        base = self.base
        if len(updates) > 128:
            compacted = _AggregateRows(
                base,
                MappingProxyType(updates),
                self.path_field,
                self.file_order,
                MappingProxyType(counts),
            )
            base = tuple(compacted)
            updates = {}
        return _AggregateRows(
            base,
            MappingProxyType(updates),
            self.path_field,
            self.file_order,
            MappingProxyType(counts),
        )


class SnapshotNotReadyError(RuntimeError):
    """No complete vault generation has been published yet."""

    code = "snapshot-not-ready"


class SnapshotRefreshRequiredError(RuntimeError):
    """A snapshot-derived action needs a fresh generation before it can proceed."""

    code = "snapshot-refresh-required"


class _RefreshCancelled(Exception):
    """Internal signal used when the service is stopping during a vault scan."""


@dataclass(frozen=True)
class _IndexedTask:
    task_id: str
    file: str
    line: int
    task: _FrozenFields | None
    metadata: str
    parse_fault: str | None = None


@dataclass(frozen=True)
class TaskLocation:
    """A detached location and parse state for one Markdown task identity."""

    task_id: str
    file: str
    line: int
    parse_fault: str | None = None


@dataclass(frozen=True)
class _FileSnapshot:
    signature: FileFingerprint | None
    tasks: tuple[_FrozenFields, ...]
    projects: tuple[_FrozenFields, ...]
    identities: tuple[_IndexedTask, ...]
    metadata_by_line: Mapping[int, str]
    identity_faults: tuple[str, ...] = ()


@dataclass(frozen=True)
class _VaultGeneration:
    number: int
    built_at: str
    local_day: str
    files: Mapping[str, _FileSnapshot]
    task_index: Mapping[str, tuple[_IndexedTask, ...]]
    tasks: _AggregateRows
    projects: _AggregateRows
    identity_fault: bool
    identity_fault_count: int
    needs_refresh: bool = False


@dataclass(frozen=True)
class VaultReadSnapshot:
    """Immutable handle to one complete, detached vault generation."""

    _generation: _VaultGeneration = field(repr=False, compare=False)

    @property
    def generation(self) -> int:
        return self._generation.number

    @property
    def built_at(self) -> str:
        return self._generation.built_at

    @property
    def local_day(self) -> str:
        return self._generation.local_day

    def getJson(self) -> TaskJsonType:
        if self._generation.identity_fault:
            raise InvalidTaskIdentityError("A Markdown task declares an invalid identifier")
        return {
            "tasks": [_thaw(row) for row in self._generation.tasks],
            "projects": [_thaw(row) for row in self._generation.projects],
        }

    def getTasks(self, include_completed: bool = True) -> list[dict[str, str]]:
        if self._generation.identity_fault:
            raise InvalidTaskIdentityError("A Markdown task declares an invalid identifier")
        tasks: list[dict[str, str]] = []
        for row in self._generation.tasks:
            task = _thaw(row)
            if include_completed or task.get("status") != "x":
                tasks.append(task)
        return tasks

    def getTaskLocations(self, task_id: str) -> tuple[TaskLocation, ...]:
        if self._generation.identity_fault:
            raise InvalidTaskIdentityError("A Markdown task declares an invalid identifier")
        try:
            validated_id = validate_task_id(task_id)
        except InvalidTaskIdentityError:
            return ()
        return tuple(
            TaskLocation(entry.task_id, entry.file, entry.line, entry.parse_fault)
            for entry in self._generation.task_index.get(validated_id, ())
        )

    def getTaskById(self, task_id: str) -> dict[str, str]:
        if self._generation.identity_fault:
            raise InvalidTaskIdentityError("A Markdown task declares an invalid identifier")
        locations = self._generation.task_index.get(validate_task_id(task_id), ())
        if not locations:
            if self._generation.needs_refresh:
                raise SnapshotRefreshRequiredError("The task identity index needs refresh")
            raise MissingTaskIdentityError("No current Markdown task matches the requested identifier")
        if len(locations) > 1:
            raise AmbiguousTaskIdentityError("More than one current Markdown task matches the requested identifier")
        task = locations[0]
        if task.parse_fault == "refresh-required":
            raise SnapshotRefreshRequiredError("The task identity index needs refresh")
        if task.parse_fault is not None or task.task is None:
            raise InvalidTaskIdentityError("The indexed Markdown task has invalid task data and needs refresh")
        return _thaw(task.task)

    def getTaskMetadata(self, task: Mapping[str, str]) -> str:
        file = task.get("file")
        try:
            line = int(task.get("line", "-1"))
        except (TypeError, ValueError):
            return ""
        file_snapshot = self._generation.files.get(str(file))
        if file_snapshot is None:
            return ""
        return file_snapshot.metadata_by_line.get(line, "")


def _freeze(row: Mapping[str, str]) -> _FrozenFields:
    return tuple((key, value) for key, value in row.items())


def _thaw(row: _FrozenFields) -> dict[str, str]:
    return dict(row)


@dataclass(frozen=True)
class _TaskIdentityFileSnapshot:
    signature: FileFingerprint
    rows: tuple[tuple[str, int], ...]
    fault: str | None = None


class ObsidianVaultTaskJsonProvider(ITaskJsonProvider):

    _TASK_LINE = re.compile(r"^\s*-\s+\[([ xX])\]\s*(.*)$")
    _TASK_METADATA = re.compile(r"\[([^\]:]+)::\s*([^\]]*)\]")

    def __init__(
        self,
        fileBroker: IFileBroker,
        policies: TaskDiscoveryPolicies,
        mutation_coordinator: MutationCoordinator | None = None,
        *,
        auto_start: bool = True,
        disableThreading: bool = False,
    ):
        self.__fileBroker = fileBroker
        self.__policies = policies
        self.__snapshot_lock = RLock()
        self.__refresh_lock = Lock()
        self.__refresh_event = Event()
        self.__stop_event = Event()
        self.__worker: Thread | None = None
        self.__has_commit_listener = False
        self.__disable_threading = disableThreading
        self.__started = False
        self.__generation: _VaultGeneration | None = None
        self.__writer_epoch = 0
        self.__pending_commit_publications = 0
        self.__last_success: str | None = None
        self.__last_error: str | None = None
        self.__last_commit_errors: dict[str, str] = {}
        self.__last_notification_error: str | None = None
        self.__refreshing = False
        self.__snapshot_callbacks: list[Callable[[], None]] = []
        self.__refresh_callbacks: list[Callable[[], None]] = []
        self.__last_inventory: tuple[tuple[str, FileFingerprint], ...] | None = None
        self.__last_cache_day: str | None = None
        self.__file_snapshots: dict[str, tuple[FileFingerprint, TaskJsonType]] = {}
        self.__identity_file_snapshots: dict[str, _TaskIdentityFileSnapshot] = {}
        self.__last_reconciled_inventory: tuple[tuple[str, FileFingerprint], ...] | None = None
        self.__last_reconciled_day: str | None = None
        self.mutation_coordinator = mutation_coordinator
        if self.mutation_coordinator is None:
            inherited_coordinator = getattr(fileBroker, "mutation_coordinator", None)
            if isinstance(inherited_coordinator, MutationCoordinator):
                self.mutation_coordinator = inherited_coordinator

        register_listener = getattr(fileBroker, "registerVaultFileCommitListener", None)
        if callable(register_listener):
            register_listener(self.__on_vault_file_commit)
            self.__has_commit_listener = True
        if auto_start:
            self.start()

    def start(self) -> None:
        """Start the coalesced background refresh loop without waiting for discovery."""
        with self.__snapshot_lock:
            if self.__started:
                return
            self.__started = True
        if self.__disable_threading:
            self.refresh()
            return
        self.__worker = Thread(
            target=self.__refresh_loop,
            name="ElrikPiroVaultRefresh",
            daemon=True,
        )
        self.__worker.start()
        self.requestRefresh()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the background loop and wait a bounded time for its worker."""
        self.__stop_event.set()
        self.__refresh_event.set()
        worker = self.__worker
        if worker is not None and worker is not current_thread():
            worker.join(timeout=max(0.0, timeout))

    def dispose(self) -> None:
        self.stop()

    def requestRefresh(self) -> None:
        """Request one background refresh; concurrent requests are coalesced."""
        if self.__disable_threading:
            return
        with self.__snapshot_lock:
            if self.__stop_event.is_set() or self.__refreshing:
                return
            if not self.__started:
                should_start = True
            else:
                should_start = False
                self.__refresh_event.set()
        if should_start:
            self.start()

    def registerSnapshotUpdatedCallback(self, callback: Callable[[], None]) -> None:
        if callback not in self.__snapshot_callbacks:
            self.__snapshot_callbacks.append(callback)

    def registerRefreshCompletedCallback(self, callback: Callable[[], None]) -> None:
        """Register a callback for complete successful vault refreshes only."""
        if callback not in self.__refresh_callbacks:
            self.__refresh_callbacks.append(callback)

    def publishConfirmedFile(self, relative_path: str, lines: list[str]) -> None:
        """Publish a confirmed file in lightweight brokers without commit hooks."""
        self.__on_vault_file_commit(relative_path, lines, 0.0)

    def refresh(self) -> bool:
        """Build and publish a generation synchronously, mainly for explicit startup/tests."""
        if not self.__refresh_lock.acquire(blocking=False):
            return False
        with self.__snapshot_lock:
            self.__refreshing = True
            self.__refresh_event.clear()
        return self.__refresh_with_acquired_lock()

    def __refresh_with_acquired_lock(self) -> bool:
        try:
            return self.__build_and_publish_generation()
        except _RefreshCancelled:
            return False
        except Exception as error:
            with self.__snapshot_lock:
                self.__last_error = f"Refresh failed ({type(error).__name__})"
            raise
        finally:
            with self.__snapshot_lock:
                self.__refreshing = False
            self.__refresh_lock.release()

    def isReady(self) -> bool:
        with self.__snapshot_lock:
            return self.__generation is not None

    def getRefreshStatus(self) -> dict[str, object]:
        with self.__snapshot_lock:
            generation = self.__generation
            age: float | None = None
            if generation is not None:
                try:
                    built_at = datetime.datetime.fromisoformat(generation.built_at)
                    age = max(0.0, (datetime.datetime.now(built_at.tzinfo) - built_at).total_seconds())
                except (TypeError, ValueError):
                    age = None
            return {
                "ready": generation is not None,
                "generation": generation.number if generation is not None else None,
                "built_at": generation.built_at if generation is not None else None,
                "local_day": generation.local_day if generation is not None else None,
                "snapshot_age_seconds": age,
                "needs_refresh": generation.needs_refresh if generation is not None else True,
                "refreshing": self.__refreshing,
                "last_success": self.__last_success,
                "last_error": self.__last_error,
                "last_commit_error": next(iter(self.__last_commit_errors.values()), None),
                "last_notification_error": self.__last_notification_error,
            }

    def getReadSnapshot(self) -> VaultReadSnapshot:
        with self.__snapshot_lock:
            generation = self.__generation
        if generation is None:
            if self.__disable_threading:
                self.refresh()
                with self.__snapshot_lock:
                    generation = self.__generation
            else:
                self.requestRefresh()
        if generation is None:
            raise SnapshotNotReadyError("The task snapshot is still loading")
        return VaultReadSnapshot(generation)

    def getJson(self) -> TaskJsonType:
        """Return a detached last-good snapshot without touching the vault."""
        return self.getReadSnapshot().getJson()

    def __getJsonSnapshot(
        self,
    ) -> tuple[TaskJsonType, tuple[tuple[str, FileFingerprint], ...], str]:
        self.refresh()
        generation = self.getReadSnapshot()
        return generation.getJson(), tuple(self.__last_inventory or ()), generation.local_day

    def __refresh_loop(self) -> None:
        while not self.__stop_event.is_set():
            now = datetime.datetime.now().astimezone()
            next_day = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
            timeout = max(0.1, min(10.0, (next_day - now).total_seconds()))
            self.__refresh_event.wait(timeout)
            if self.__stop_event.is_set():
                break
            if not self.__refresh_lock.acquire(blocking=False):
                continue
            with self.__snapshot_lock:
                if self.__stop_event.is_set():
                    self.__refresh_lock.release()
                    break
                self.__refreshing = True
                self.__refresh_event.clear()
            try:
                self.__refresh_with_acquired_lock()
            except Exception:
                # Status records a sanitized failure; the previous generation remains available.
                continue

    def __build_and_publish_generation(self) -> bool:
        if self.__stop_event.is_set():
            return False
        with self.__snapshot_lock:
            start_epoch = self.__writer_epoch
            previous = self.__generation
        local_day = str(TimePoint.today())
        inventory = tuple(self.__get_vault_markdown_inventory())
        if self.__stop_event.is_set():
            return False
        reusable = previous.files if previous is not None else {}
        next_files: dict[str, _FileSnapshot] = {}
        for relative_path, signature in inventory:
            if self.__stop_event.is_set():
                return False
            previous_file = reusable.get(relative_path)
            if previous_file is not None and previous is not None and previous_file.signature == signature and previous.local_day == local_day:
                next_files[relative_path] = previous_file
                continue
            lines = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, relative_path)
            next_files[relative_path] = self.__build_file_snapshot(
                relative_path,
                lines,
                signature,
                cancel_if_stopping=True,
            )

        now = datetime.datetime.now().astimezone().isoformat()
        next_generation = self.__make_generation(
            next_files,
            (previous.number + 1) if previous is not None else 1,
            now,
            local_day,
            needs_refresh=False,
        )
        with self.__snapshot_lock:
            if self.__stop_event.is_set():
                return False
            if start_epoch != self.__writer_epoch:
                self.__refresh_event.set()
                return False
            self.__generation = next_generation
            self.__last_inventory = inventory
            self.__last_cache_day = local_day
            self.__last_success = now
            self.__last_error = None
            self.__last_commit_errors.clear()
            self.__last_reconciled_inventory = None
            self.__last_reconciled_day = None
            if local_day != str(TimePoint.today()):
                self.__refresh_event.set()
        self.__notify_snapshot_updated()
        self.__notify_refresh_completed()
        return True

    def __notify_snapshot_updated(self) -> None:
        for callback in tuple(self.__snapshot_callbacks):
            try:
                callback()
            except Exception as error:
                with self.__snapshot_lock:
                    self.__last_notification_error = f"Snapshot notification failed ({type(error).__name__})"

    def __notify_refresh_completed(self) -> None:
        """Notify maintenance consumers after publishing a full generation."""
        for callback in tuple(self.__refresh_callbacks):
            try:
                callback()
            except Exception as error:
                with self.__snapshot_lock:
                    self.__last_notification_error = (
                        f"Refresh notification failed ({type(error).__name__})"
                    )

    def __make_generation(
        self,
        files: dict[str, _FileSnapshot],
        number: int,
        built_at: str,
        local_day: str,
        *,
        needs_refresh: bool = False,
    ) -> _VaultGeneration:
        index: dict[str, list[_IndexedTask]] = {}
        identity_fault_count = 0
        for file_snapshot in files.values():
            identity_fault_count += bool(file_snapshot.identity_faults)
            for identity in file_snapshot.identities:
                index.setdefault(identity.task_id, []).append(identity)
        frozen_index = MappingProxyType({key: tuple(value) for key, value in index.items()})
        file_order = MappingProxyType({path: index for index, path in enumerate(files)})
        return _VaultGeneration(
            number,
            built_at,
            local_day,
            MappingProxyType(dict(files)),
            frozen_index,
            _AggregateRows.from_files(files, "tasks", file_order),
            _AggregateRows.from_files(files, "projects", file_order),
            identity_fault_count > 0,
            identity_fault_count,
            needs_refresh,
        )

    def __on_vault_file_commit(
        self,
        relative_path: str,
        lines: list[str] | None,
        signature: FileFingerprint | None,
    ) -> None:
        if self.__stop_event.is_set():
            return
        normalized_path = relative_path.replace("\\", "/")
        with self.__snapshot_lock:
            self.__writer_epoch += 1
            self.__pending_commit_publications += 1
            self.__last_reconciled_inventory = None
            self.__last_reconciled_day = None
        try:
            self.__publish_vault_file_commit(normalized_path, lines, signature)
        finally:
            with self.__snapshot_lock:
                self.__pending_commit_publications -= 1

    def __publish_vault_file_commit(
        self,
        normalized_path: str,
        lines: list[str] | None,
        signature: FileFingerprint | None,
    ) -> None:
        needs_refresh = lines is None or signature is None
        if needs_refresh:
            updated_file = None
        else:
            assert lines is not None and signature is not None
            try:
                updated_file = self.__build_file_snapshot(normalized_path, lines, signature)
            except Exception as error:
                updated_file = None
                needs_refresh = True
                with self.__snapshot_lock:
                    self.__last_commit_errors[normalized_path] = f"Committed file requires refresh ({type(error).__name__})"
        with self.__snapshot_lock:
            if self.__stop_event.is_set():
                return
            current = self.__generation
            if current is not None:
                if updated_file is None:
                    published_file = self.__invalidated_file_snapshot(
                        normalized_path,
                        current.files.get(normalized_path),
                    )
                else:
                    published_file = updated_file

                previous_file = current.files.get(normalized_path)
                index_updates: dict[str, tuple[_IndexedTask, ...]] = {}
                impacted_ids = {
                    item.task_id for item in previous_file.identities
                } if previous_file is not None else set()
                impacted_ids.update(item.task_id for item in published_file.identities)
                for task_id in impacted_ids:
                    retained = tuple(
                        entry for entry in current.task_index.get(task_id, ())
                        if entry.file != normalized_path
                    )
                    added = tuple(
                        entry for entry in published_file.identities
                        if entry.task_id == task_id
                    )
                    index_updates[task_id] = retained + added

                identity_fault_count = current.identity_fault_count
                if previous_file is not None and previous_file.identity_faults:
                    identity_fault_count -= 1
                if published_file.identity_faults:
                    identity_fault_count += 1
                identity_fault = identity_fault_count > 0
                generation = _VaultGeneration(
                    current.number + 1,
                    current.built_at,
                    current.local_day,
                    _OverlayMapping(current.files, {normalized_path: published_file}),
                    _OverlayMapping(current.task_index, index_updates),
                    current.tasks.replace_file(normalized_path, published_file.tasks),
                    current.projects.replace_file(normalized_path, published_file.projects),
                    identity_fault,
                    identity_fault_count,
                    current.needs_refresh or needs_refresh,
                )
                self.__generation = generation
                if updated_file is None:
                    self.__last_commit_errors.setdefault(
                        normalized_path,
                        "A committed Markdown file needs refresh",
                    )
                else:
                    self.__last_commit_errors.pop(normalized_path, None)
                notified = True
            else:
                notified = False
        if notified:
            self.__notify_snapshot_updated()
        if needs_refresh:
            self.__schedule_refresh_followup()

    def __capture_discovery_baseline(self) -> tuple[VaultReadSnapshot, int]:
        """Capture a generation and its writer epoch as one stable baseline."""
        with self.__snapshot_lock:
            generation = self.__generation
            writer_epoch = self.__writer_epoch
            commit_in_flight = self.__pending_commit_publications > 0
        if generation is None:
            self.requestRefresh()
            raise SnapshotNotReadyError("The task snapshot is still loading")
        if commit_in_flight:
            self.requestRefresh()
            raise SnapshotRefreshRequiredError(
                "A committed Markdown file is still being published to the task snapshot"
            )
        return VaultReadSnapshot(generation), writer_epoch

    def __schedule_refresh_followup(self) -> None:
        if self.__stop_event.is_set() or self.__disable_threading:
            return
        with self.__snapshot_lock:
            self.__refresh_event.set()

    @staticmethod
    def __invalidated_file_snapshot(
        relative_path: str,
        previous: _FileSnapshot | None,
    ) -> _FileSnapshot:
        identities = tuple(
            _IndexedTask(item.task_id, relative_path, item.line, None, item.metadata, "refresh-required")
            for item in (previous.identities if previous is not None else ())
        )
        faults = previous.identity_faults if previous is not None else ()
        return _FileSnapshot(
            None,
            previous.tasks if previous is not None else (),
            previous.projects if previous is not None else (),
            identities,
            previous.metadata_by_line if previous is not None else MappingProxyType({}),
            faults,
        )

    def __get_vault_markdown_inventory(self) -> list[tuple[str, FileFingerprint]]:
        cancellable_inventory = getattr(self.__fileBroker, "getVaultFilesCancellable", None)
        if callable(cancellable_inventory):
            files = cancellable_inventory(VaultRegistry.OBSIDIAN, self.__stop_event.is_set)
        else:
            files = self.__fileBroker.getVaultFiles(VaultRegistry.OBSIDIAN)
        signatures_value = getattr(files, "_signatures", None)
        signatures = signatures_value if isinstance(signatures_value, dict) else {}
        inventory: list[tuple[str, FileFingerprint]] = []
        for relative_path, mtime in files:
            if self.__stop_event.is_set():
                break
            if not relative_path.lower().endswith(".md"):
                continue
            signature = signatures.get(relative_path, mtime)
            inventory.append((relative_path, signature))
        return inventory

    def __invalidate_cached_file(self, relative_path: str) -> None:
        """Compatibility hook: schedule a background reconcile without stale I/O."""
        with self.__snapshot_lock:
            self.__last_reconciled_inventory = None
            self.__last_reconciled_day = None
        self.requestRefresh()

    def invalidateCachedFile(self, relative_path: str) -> None:
        """Invalidate parsed task and identity data after a Markdown write."""
        self.__invalidate_cached_file(relative_path)

    def getTaskIdentitySnapshot(
        self,
        skip_file: str | None = None,
    ) -> list[dict[str, str | int]]:
        """Return IDs from the published generation without scanning the vault."""
        generation = self.getReadSnapshot()._generation
        locations: list[dict[str, str | int]] = []
        skip_normalized = skip_file.replace("\\", "/") if skip_file is not None else None
        first_fault: str | None = None
        for relative_path, snapshot in generation.files.items():
            if relative_path.replace("\\", "/") == skip_normalized:
                continue
            if first_fault is None and snapshot.identity_faults:
                first_fault = snapshot.identity_faults[0]
            locations.extend(
                {"id": identity.task_id, "file": relative_path, "line": identity.line}
                for identity in snapshot.identities
            )

        if first_fault == "conflicting-ids":
            raise InvalidTaskIdentityError("A Markdown task declares conflicting identifiers")
        if first_fault == "invalid-id":
            raise InvalidTaskIdentityError("Task ID must be a non-empty string")
        return locations

    def getTaskLocations(self, task_id: str) -> tuple[TaskLocation, ...]:
        return self.getReadSnapshot().getTaskLocations(task_id)

    def getTaskById(self, task_id: str) -> dict[str, str]:
        return self.getReadSnapshot().getTaskById(task_id)

    def __build_file_snapshot(
        self,
        relative_path: str,
        lines: list[str],
        signature: FileFingerprint | None,
        *,
        cancel_if_stopping: bool = False,
    ) -> _FileSnapshot:
        normalized_path = relative_path.replace("\\", "/")
        header = self.__getFileHeader(lines)
        projects: tuple[_FrozenFields, ...] = ()
        if "project" in header and header["project"] in VALID_PROJECT_STATUS:
            file_name = normalized_path.split("/")[-1].rsplit(".md", 1)[0]
            projects = (_freeze({"name": file_name, "status": header["project"], "path": relative_path}),)

        parsed_tasks: list[_FrozenFields] = []
        indexed: list[_IndexedTask] = []
        metadata_by_line: dict[int, str] = {}
        faults: list[str] = []
        for line_number, line in enumerate(lines):
            if cancel_if_stopping and self.__stop_event.is_set():
                raise _RefreshCancelled()
            if self._TASK_LINE.match(line) is None:
                continue
            metadata_by_line[line_number] = "".join(lines[max(line_number, 0):min(line_number + 5, len(lines))])
            body_match = self._TASK_LINE.match(line)
            if body_match is None:
                continue
            body = body_match.group(2)
            metadata = list(self._TASK_METADATA.finditer(body))
            text = body[:metadata[0].start()].strip() if metadata else body.strip()
            declared_ids: list[str] = []
            identity_fault: str | None = None
            for item in metadata:
                if item.group(1).strip() != "id":
                    continue
                try:
                    declared_ids.append(validate_task_id(item.group(2).strip()))
                except InvalidTaskIdentityError:
                    identity_fault = "invalid-id"
            if len(set(declared_ids)) > 1:
                identity_fault = "conflicting-ids"
            task_ids = list(dict.fromkeys(declared_ids))
            if not task_ids and identity_fault is None:
                task_ids = [fallback_task_id(text, normalized_path, line_number)]
            if identity_fault is not None:
                faults.append(identity_fault)

            task_row: _FrozenFields | None = None
            parse_fault = identity_fault
            try:
                task_data = self.__getTaskDictFromLine(line, relative_path, line_number, header)
            except InvalidTaskIdentityError:
                task_data = None
                parse_fault = parse_fault or "invalid-id"
            if task_data is not None:
                if task_data.get("valid") == "True":
                    task_data.pop("valid", None)
                    parsed_tasks.append(_freeze(task_data))
                    task_row = _freeze(task_data)
                elif parse_fault is None:
                    parse_fault = "invalid-task-data"
            for task_id in task_ids:
                indexed.append(_IndexedTask(
                    task_id,
                    normalized_path,
                    line_number,
                    task_row,
                    metadata_by_line[line_number],
                    parse_fault,
                ))

        return _FileSnapshot(
            signature,
            tuple(parsed_tasks),
            projects,
            tuple(indexed),
            MappingProxyType(metadata_by_line),
            tuple(faults),
        )

    def __identity_snapshot_from_lines(
        self,
        lines: list[str],
        relative_path: str,
        mtime: FileFingerprint,
    ) -> _TaskIdentityFileSnapshot:
        rows: list[tuple[str, int]] = []
        normalized_path = relative_path.replace("\\", "/")
        for line_number, line in enumerate(lines):
            match = self._TASK_LINE.match(line)
            if match is None:
                continue
            body = match.group(2)
            metadata = list(self._TASK_METADATA.finditer(body))
            text = body[:metadata[0].start()].strip() if metadata else body.strip()
            declared_ids: list[str] = []
            for item in metadata:
                if item.group(1).strip() != "id":
                    continue
                task_id = item.group(2).strip()
                if not task_id:
                    return _TaskIdentityFileSnapshot(mtime, tuple(rows), "invalid-id")
                declared_ids.append(validate_task_id(task_id))
            if len(set(declared_ids)) > 1:
                return _TaskIdentityFileSnapshot(mtime, tuple(rows), "conflicting-ids")
            task_id = declared_ids[0] if declared_ids else fallback_task_id(text, normalized_path, line_number)
            rows.append((task_id, line_number))
        return _TaskIdentityFileSnapshot(mtime, tuple(rows))

    def parseTaskFile(self, relative_path: str, lines: list[str]) -> list[dict[str, str]]:
        """Parse one supplied Markdown snapshot without performing file I/O."""
        task_list: TaskJsonListType = []
        file_header = self.__getFileHeader(lines)
        for line_number, line in self.__getFileTaskLines(lines, file_header):
            task = self.__getTaskDictFromLine(line, relative_path, line_number, file_header)
            if task["valid"] == "True":
                self.__update_or_append_task(task, task_list)
        return task_list

    def discover(self) -> TaskJsonType:
        """Prepare project maintenance from one generation and yield per note commit."""
        if self.__stop_event.is_set():
            return self.getJson()
        if not self.isReady():
            if self.__disable_threading:
                self.refresh()
            else:
                self.requestRefresh()
                raise SnapshotNotReadyError("The task snapshot is still loading")
        for attempt in range(2):
            snapshot, expected_epoch = self.__capture_discovery_baseline()
            generation = snapshot._generation
            if generation.needs_refresh:
                if self.__disable_threading and attempt == 0:
                    self.refresh()
                    continue
                if not self.__disable_threading:
                    self.requestRefresh()
                raise SnapshotRefreshRequiredError(
                    "The published vault generation needs refresh before project maintenance"
                )
            known_ids = set(generation.task_index)
            actions: list[tuple[str, int, str, str]] = []
            for project in snapshot.getJson().get("projects", []):
                if self.__stop_event.is_set():
                    return snapshot.getJson()
                if project.get("status") != "open":
                    continue
                relative_path = project.get("path", "")
                if not relative_path:
                    continue
                lines = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, relative_path)
                if self.__getFileHeader(lines).get("project") != "open":
                    continue
                if any(self.__is_open_task_line(line) for line in lines):
                    continue
                line_number = len(lines)
                task_text = "Define next action"
                task_id = fallback_task_id(task_text, relative_path.replace("\\", "/"), line_number)
                if task_id in known_ids:
                    raise AmbiguousTaskIdentityError("The prepared Markdown task identifier is already in use")
                known_ids.add(task_id)
                context = self.__getFallbackPolicy()
                task_line = f"- [ ] {task_text} [track::{context}] [id::{task_id}]\n"
                actions.append((relative_path, line_number, task_id, task_line))

            stale_plan = False
            for relative_path, line_number, task_id, task_line in actions:
                if self.__stop_event.is_set():
                    return snapshot.getJson()

                def commit_target() -> bool:
                    nonlocal expected_epoch
                    if self.__stop_event.is_set() or (
                        self.__get_writer_epoch() != expected_epoch
                    ):
                        return False
                    did_append = False

                    def prepare(current_lines: list[str]) -> list[str]:
                        nonlocal did_append
                        updated = list(current_lines)
                        if self.__getFileHeader(updated).get("project") != "open":
                            return updated
                        if any(self.__is_open_task_line(line) for line in updated):
                            return updated
                        if len(updated) != line_number:
                            return updated
                        local_ids = self.__task_ids_from_lines(updated, relative_path)
                        if task_id in local_ids:
                            raise AmbiguousTaskIdentityError("The prepared Markdown task identifier is already in use")
                        if updated and not updated[-1].endswith(("\n", "\r")):
                            updated[-1] += "\n"
                        updated.append(task_line)
                        did_append = True
                        return updated

                    committed = self.__fileBroker.updateVaultFileLines(
                        VaultRegistry.OBSIDIAN,
                        relative_path,
                        prepare,
                    )
                    if did_append and not self.__has_commit_listener:
                        self.__on_vault_file_commit(relative_path, committed, 0.0)
                    expected_epoch = self.__get_writer_epoch()
                    return did_append

                appended = (
                    self.mutation_coordinator.run_or_inline(commit_target)
                    if self.mutation_coordinator is not None
                    else commit_target()
                )
                if not appended:
                    stale_plan = True
                    break
            if not stale_plan and self.__get_writer_epoch() != expected_epoch:
                stale_plan = True
            if not stale_plan:
                return self.getJson()
            if self.__disable_threading and attempt == 0:
                self.refresh()
                continue
            if not self.__disable_threading:
                self.requestRefresh()
            raise SnapshotRefreshRequiredError(
                "The project maintenance plan became stale and needs refresh"
            )
        return self.getJson()

    def __get_writer_epoch(self) -> int:
        with self.__snapshot_lock:
            return self.__writer_epoch

    def __task_ids_from_lines(self, lines: list[str], relative_path: str) -> set[str]:
        identities: set[str] = set()
        normalized_path = relative_path.replace("\\", "/")
        for line_number, line in enumerate(lines):
            match = self._TASK_LINE.match(line)
            if match is None:
                continue
            body = match.group(2)
            metadata = list(self._TASK_METADATA.finditer(body))
            text = body[:metadata[0].start()].strip() if metadata else body.strip()
            declared_ids = [
                validate_task_id(item.group(2).strip())
                for item in metadata
                if item.group(1).strip() == "id"
            ]
            if len(set(declared_ids)) > 1:
                raise InvalidTaskIdentityError("A Markdown task declares conflicting identifiers")
            identities.add(declared_ids[0] if declared_ids else fallback_task_id(text, normalized_path, line_number))
        return identities

    @staticmethod
    def _task_id(task: dict[str, str]) -> str:
        if "id" in task:
            return validate_task_id(task["id"])
        return fallback_task_id(
            task["taskText"],
            task["file"].replace("\\", "/"),
            int(task["line"]),
        )

    def __process_task_file(
        self,
        file: tuple[str, FileFingerprint],
        task_list: TaskJsonListType,
        project_list: ProjectJsonListType,
        fileContent: list[str] | None = None,
    ) -> _TaskIdentityFileSnapshot:
        if fileContent is None:
            fileContent = self.__fileBroker.getVaultFileLines(VaultRegistry.OBSIDIAN, file[0])
        identity_snapshot = self.__identity_snapshot_from_lines(fileContent, file[0], file[1])
        fileHeader = self.__getFileHeader(fileContent)
        taskLines = self.__getFileTaskLines(fileContent, fileHeader)

        if "project" in fileHeader and fileHeader["project"] in VALID_PROJECT_STATUS:
            fileName = file[0].replace("\\", "/").split("/")[-1].rsplit(".md", 1)[0]
            status = fileHeader["project"]
            project_list.append({
                "name": fileName,
                "status": status,
                "path": file[0]
            })

        for lineNum, line in taskLines:
            taskDict = self.__getTaskDictFromLine(line, file[0], lineNum, fileHeader)
            if taskDict["valid"] == "False":
                continue
            self.__update_or_append_task(taskDict, task_list)
        return identity_snapshot

    def __is_open_task_line(self, line: str) -> bool:
        match = self._TASK_LINE.match(line)
        return match is not None and match.group(1) == " "

    def __update_or_append_task(self, taskDict: dict[str, str], task_list: TaskJsonListType) -> None:
        found = False
        for i in range(len(task_list)):
            if task_list[i]["file"] == taskDict["file"] and task_list[i]["line"] == taskDict["line"]:
                task_list[i] = taskDict
                found = True
                break
        if not found:
            task_list.append(taskDict)

    def saveJson(self, json: TaskJsonType) -> None:
        # Markdown is edited through task/project operations, not bulk JSON.
        pass

    def __getFileHeader(self, file: list[str]) -> dict[str, str]:
        header: dict[str, str] = {}
        inHeader = False
        for line in file:
            if line.strip() == "---":
                if inHeader:
                    break
                inHeader = True
                continue

            if inHeader:
                key, separator, value = line.partition(":")
                if separator:
                    if value.startswith(":"):
                        value = value[1:]
                    header[key.strip()] = value.strip()
        return header

    def __getFileTaskLines(self, file: list[str], fileHeader: dict[str, str]) -> list[tuple[int, str]]:
        return [
            (line_number, line)
            for line_number, line in enumerate(file)
            if self._TASK_LINE.match(line) is not None
        ]

    def __getDefaultTaskDict(self) -> dict[str, str]:
        return {
            "taskText": "",
            "starts": str(TimePoint.today()),
            "due": str(TimePoint.today()),
            "severity": "1",
            "remaining_cost": "1",
            "invested": "0",
            "status": " ",
            "file": "",
            "line": "0",
            "calm": "false"
        }

    def __getTaskDictFromLine(self, line: str, file: str, lineNum: int, fileHeader: dict[str, str]) -> dict[str, str]:
        taskDict = self.__getDefaultTaskDict()
        taskDict["file"] = file
        taskDict["line"] = str(lineNum)

        checkbox = self._TASK_LINE.match(line)
        if checkbox is None:
            taskDict["valid"] = "False"
            return taskDict

        taskDict["status"] = "x" if checkbox.group(1).lower() == "x" else " "
        textAfterCheckbox = checkbox.group(2)
        firstMetadata = self._TASK_METADATA.search(textAfterCheckbox)
        taskDict["taskText"] = textAfterCheckbox[:firstMetadata.start()].strip() if firstMetadata else textAfterCheckbox.strip()

        # Frontmatter supplies defaults; explicit task metadata then overrides it.
        for key, value in fileHeader.items():
            taskDict[key] = value
        # Task identity is defined by a tag on the task line, never by file-wide metadata.
        taskDict.pop("id", None)

        declared_ids: list[str] = []
        for match in self._TASK_METADATA.finditer(textAfterCheckbox):
            key = match.group(1).strip()
            value = match.group(2).strip()
            if key == "id":
                declared_ids.append(validate_task_id(value))
            else:
                taskDict[key] = value
        if declared_ids:
            if len(set(declared_ids)) > 1:
                raise InvalidTaskIdentityError("A Markdown task declares conflicting identifiers")
            taskDict["id"] = declared_ids[0]

        try:
            taskDict["starts"] = self.__apply_date_policy(taskDict["starts"])
            taskDict["due"] = self.__apply_date_policy(taskDict["due"])
            taskDict["track"] = self.__apply_track_policy(taskDict.get("track"))
            severity = float(taskDict["severity"])
            remaining_cost = float(taskDict["remaining_cost"])
            invested = float(taskDict["invested"])
            total_cost = remaining_cost - invested
            if not all(math.isfinite(value) for value in (severity, remaining_cost, invested, total_cost)):
                raise ValueError("Task numeric metadata must be finite")
            taskDict["severity"] = str(severity)
            taskDict["total_cost"] = str(total_cost)
            taskDict["effort_invested"] = taskDict["invested"]
            taskDict["valid"] = "True"
        except ValueError:
            print("Invalid task metadata was skipped; diagnostic details are suppressed.")
            taskDict["valid"] = "False"

        return taskDict

    def __apply_date_policy(self, date: str) -> str:
        try:
            return str(TimePoint.from_string(date).as_int())
        except ValueError:
            if self.__policies.date_missing_policy == "1":
                return str(TimePoint.today().as_int())
            raise ValueError(f"Invalid date format: {date}. Expected format is YYYY-MM-DD or YYYY-MM-DDTHH:MM")

    def __apply_track_policy(self, track: str | None) -> str:
        def is_prefix_of(prefix: str | None) -> bool:
            return any(isinstance(prefix, str) and prefix.startswith(context) for context in self.__policies.categories_prefixes)

        if not is_prefix_of(track):
            if self.__policies.context_missing_policy == "1":
                return self.__policies.default_context
            raise ValueError("Track tag is missing and no default value is set.")

        assert isinstance(track, str)
        return track

    def __getFallbackPolicy(self) -> str | None:
        if self.__policies.default_context in self.__policies.categories_prefixes:
            return self.__policies.default_context
        return self.__policies.categories_prefixes[0] if self.__policies.categories_prefixes else None
