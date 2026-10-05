"""Serialize mutations and retain short-lived operation receipts in memory."""

from __future__ import annotations

import asyncio
import copy
import queue
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Literal, Mapping, TypeVar, cast
from uuid import UUID


T = TypeVar("T")
EffectsState = Literal["none", "partial", "unknown"]
OperationStatus = Literal["pending", "running", "succeeded", "failed"]


class MutationCoordinatorError(RuntimeError):
    """Base class for mutation coordinator errors."""


class MutationCoordinatorClosed(MutationCoordinatorError):
    """The coordinator no longer accepts work."""


class OperationIdConflict(MutationCoordinatorError):
    """An operation ID was admitted previously with a different intent."""

    def __init__(self, operation_id: str) -> None:
        message = (
            f"Operation {operation_id} was already admitted with another"
            " intent"
        )
        super().__init__(message)
        self.operation_id = operation_id


class OperationResultUnavailable(MutationCoordinatorError):
    """No retained receipt is available; this never replays an operation."""

    def __init__(self, operation_id: str) -> None:
        message = (
            f"No retained result is available for operation {operation_id}"
        )
        super().__init__(message)
        self.operation_id = operation_id


class ReentrantOperationWait(MutationCoordinatorError):
    """The worker callback tried to wait for work that only it can run."""

    def __init__(self, operation_id: str) -> None:
        message = (
            f"The active FIFO turn cannot wait for operation {operation_id}"
        )
        super().__init__(message)
        self.operation_id = operation_id


class OperationExecutionError(MutationCoordinatorError):
    """Fallback when an operation exception cannot be safely copied."""

    def __init__(self, failure: OperationFailure) -> None:
        super().__init__(failure.message)
        self.failure = copy.deepcopy(failure)
        self.code = failure.code
        self.details = copy.deepcopy(failure.details)
        self.effects_state = failure.effects_state


@dataclass(frozen=True)
class OperationFailure:
    """A detached description of a failed operation."""

    error_type: str
    message: str
    effects_state: EffectsState
    code: str | None = None
    details: dict[str, object] = field(default_factory=dict)
    context: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationReceipt:
    """A detached point-in-time view of an admitted operation."""

    operation_id: str
    intent: object
    status: OperationStatus
    result: object | None = None
    failure: OperationFailure | None = None


@dataclass
class _OperationEntry:
    operation_id: str
    intent: object
    work: Callable[[object], object]
    done: threading.Event
    status: OperationStatus = "pending"
    result: object | None = None
    failure: OperationFailure | None = None
    exception: BaseException | None = None


@dataclass
class _JobEntry:
    work: Callable[[], object]
    done: threading.Event
    result: object | None = None
    exception: BaseException | None = None


_QueueEntry = _OperationEntry | _JobEntry | None


class MutationCoordinator:
    """Run internal mutations in one FIFO turn and expose volatile receipts.

    Callers authenticate and validate request structure before calling this
    coordinator. Operation callbacks receive a private copy of the immutable
    admission snapshot, and their return value is copied before it is retained.
    Callbacks submitted recursively from the worker execute inline as part of
    its current turn, which avoids a callback waiting behind itself.
    """

    RECEIPT_LIMIT = 1024
    ASYNC_WAIT_INTERVAL_SECONDS = 0.01

    def __init__(self) -> None:
        self._queue: queue.Queue[_QueueEntry] = queue.Queue()
        self._lock = threading.RLock()
        self._entries: dict[str, _OperationEntry] = {}
        self._finished: OrderedDict[str, None] = OrderedDict()
        self._closed = False
        self._worker = threading.Thread(
            target=self._work_loop,
            name="ElrikPiroMutationCoordinator",
            daemon=True,
        )
        self._worker.start()

    @staticmethod
    def _normalize_operation_id(operation_id: str | UUID) -> str:
        try:
            return str(UUID(str(operation_id)))
        except (ValueError, AttributeError, TypeError) as error:
            raise ValueError("operation_id must be a UUID") from error

    @staticmethod
    def _snapshot(value: object) -> object:
        try:
            return copy.deepcopy(value)
        except Exception as error:
            message = "Mutation data must be independently copyable"
            raise TypeError(message) from error

    @staticmethod
    def _copy_exception(error: BaseException) -> BaseException:
        try:
            copied = None
            for exception_type in type(error).__mro__[1:]:
                allocator = exception_type.__dict__.get("__new__")
                if allocator is None or exception_type.__module__ != "builtins":
                    continue
                try:
                    copied = allocator(type(error))
                    break
                except TypeError:
                    continue
            if copied is None:
                copied = BaseException.__new__(type(error))
            BaseException.__init__(copied, *copy.deepcopy(error.args))
            for name, value in getattr(error, "__dict__", {}).items():
                setattr(copied, name, copy.deepcopy(value))
            for exception_type in type(error).__mro__:
                slots = getattr(exception_type, "__slots__", ())
                if isinstance(slots, str):
                    slots = (slots,)
                for name in slots:
                    if name not in ("__dict__", "__weakref__") and hasattr(error, name):
                        copied_value = copy.deepcopy(getattr(error, name))
                        setattr(copied, name, copied_value)
            copied.__traceback__ = None
            copied.__cause__ = None
            copied.__context__ = None
            return copied
        except Exception:
            failure = MutationCoordinator._failure_for(error)
            return OperationExecutionError(failure)

    @classmethod
    def _failure_for(cls, error: BaseException) -> OperationFailure:
        effects_state = cls._error_attribute(error, "effects_state", "unknown")
        if effects_state not in ("none", "partial", "unknown"):
            effects_state = "unknown"
        effects_state = cast(EffectsState, effects_state)

        error_details = cls._error_attribute(error, "details", {})
        if isinstance(error_details, Mapping):
            try:
                details = cls._snapshot(dict(error_details))
            except TypeError:
                details = {}
        else:
            details = {}

        context: dict[str, object] = {}
        for name in ("path", "phase", "replaced", "attempts", "reason"):
            value = cls._error_attribute(error, name)
            if value is not None and isinstance(
                value, (str, bool, int, float)
            ):
                context[name] = value
            elif value is None and cls._has_error_attribute(error, name):
                context[name] = None

        code = cls._error_attribute(error, "code")
        if not isinstance(code, str):
            code = None
        try:
            message = str(error)
        except Exception:
            message = type(error).__name__
        return OperationFailure(
            error_type=f"{type(error).__module__}.{type(error).__qualname__}",
            message=message,
            effects_state=effects_state,
            code=code,
            details=cast(dict[str, object], details),
            context=context,
        )

    @staticmethod
    def _error_attribute(
        error: BaseException,
        name: str,
        default: object = None,
    ) -> object:
        try:
            return getattr(error, name, default)
        except Exception:
            return default

    @staticmethod
    def _has_error_attribute(error: BaseException, name: str) -> bool:
        try:
            return hasattr(error, name)
        except Exception:
            return False

    def _is_worker_thread(self) -> bool:
        return threading.current_thread() is self._worker

    def run_job(self, work: Callable[[], T]) -> T:
        """Run an internal FIFO job without creating an operation receipt."""
        if self._is_worker_thread():
            return work()

        job = _JobEntry(work=work, done=threading.Event())
        with self._lock:
            if self._closed:
                message = "Mutation coordinator is closed"
                raise MutationCoordinatorClosed(message)
            self._queue.put(job)
        return cast(T, self._wait_job(job))

    def run_or_inline(self, work: Callable[[], T]) -> T:
        """Run inline in the worker's turn, otherwise enqueue."""
        return self.run_job(work)

    async def run_job_async(self, work: Callable[[], T]) -> T:
        """Enqueue before yielding; cancelling the wait cannot remove it."""
        if self._is_worker_thread():
            return work()
        job = _JobEntry(work=work, done=threading.Event())
        with self._lock:
            if self._closed:
                message = "Mutation coordinator is closed"
                raise MutationCoordinatorClosed(message)
            self._queue.put(job)
        return cast(T, await self._wait_job_async(job))

    def run_operation(
        self,
        operation_id: str | UUID,
        intent: object,
        work: Callable[[object], T],
    ) -> T:
        """Admit or recognize an operation, returning a detached final result.

        The operation ID must be a UUID. Reusing an ID with an equal intent
        waits for or returns the recorded outcome. Reusing it with a different
        intent raises :class:`OperationIdConflict` without running it.
        """
        entry, admitted = self._admit_operation(operation_id, intent, work)
        if admitted and self._is_worker_thread():
            self._execute_operation(entry)
        elif self._is_worker_thread() and not entry.done.is_set():
            raise ReentrantOperationWait(entry.operation_id)
        return cast(T, self._wait_operation(entry))

    async def run_operation_async(
        self,
        operation_id: str | UUID,
        intent: object,
        work: Callable[[object], T],
    ) -> T:
        """Admit before yielding; cancelling the waiter cannot cancel it."""
        entry, admitted = self._admit_operation(operation_id, intent, work)
        if admitted and self._is_worker_thread():
            self._execute_operation(entry)
            return cast(T, self._wait_operation(entry))
        if self._is_worker_thread() and not entry.done.is_set():
            raise ReentrantOperationWait(entry.operation_id)
        return cast(T, await self._wait_operation_async(entry))

    def _admit_operation(
        self,
        operation_id: str | UUID,
        intent: object,
        work: Callable[[object], T],
    ) -> tuple[_OperationEntry, bool]:
        normalized_id = self._normalize_operation_id(operation_id)
        intent_snapshot = self._snapshot(intent)
        with self._lock:
            existing = self._entries.get(normalized_id)
            if existing is not None:
                if existing.intent != intent_snapshot:
                    raise OperationIdConflict(normalized_id)
                return existing, False
            if self._closed:
                message = "Mutation coordinator is closed"
                raise MutationCoordinatorClosed(message)
            entry = _OperationEntry(
                operation_id=normalized_id,
                intent=intent_snapshot,
                work=work,
                done=threading.Event(),
            )
            self._entries[normalized_id] = entry
            if not self._is_worker_thread():
                self._queue.put(entry)
            return entry, True

    def _execute_operation(self, entry: _OperationEntry) -> None:
        with self._lock:
            entry.status = "running"
        try:
            callback_intent = self._snapshot(entry.intent)
            result = entry.work(callback_intent)
            result_snapshot = self._snapshot(result)
        except BaseException as error:
            failure = self._failure_for(error)
            exception_snapshot = self._copy_exception(error)
            with self._lock:
                entry.exception = exception_snapshot
                entry.failure = failure
                entry.status = "failed"
                self._finish_operation(entry)
            return

        with self._lock:
            entry.result = result_snapshot
            entry.status = "succeeded"
            self._finish_operation(entry)

    def _finish_operation(self, entry: _OperationEntry) -> None:
        self._finished[entry.operation_id] = None
        self._finished.move_to_end(entry.operation_id)
        while len(self._finished) > self.RECEIPT_LIMIT:
            expired_id, _ = self._finished.popitem(last=False)
            expired = self._entries.get(expired_id)
            if expired is not None and expired.status in (
                "succeeded",
                "failed",
            ):
                del self._entries[expired_id]
        entry.done.set()

    def _wait_job(self, job: _JobEntry) -> object:
        job.done.wait()
        if job.exception is not None:
            raise self._copy_exception(job.exception)
        return job.result

    def _wait_operation(self, entry: _OperationEntry) -> object:
        entry.done.wait()
        if entry.exception is not None:
            raise self._copy_exception(entry.exception)
        return self._snapshot(entry.result)

    async def _wait_job_async(self, job: _JobEntry) -> object:
        while not job.done.is_set():
            await asyncio.sleep(self.ASYNC_WAIT_INTERVAL_SECONDS)
        return self._wait_job(job)

    async def _wait_operation_async(self, entry: _OperationEntry) -> object:
        while not entry.done.is_set():
            await asyncio.sleep(self.ASYNC_WAIT_INTERVAL_SECONDS)
        return self._wait_operation(entry)

    def get_receipt(self, operation_id: str | UUID) -> OperationReceipt:
        """Return a detached receipt without starting or repeating work."""
        normalized_id = self._normalize_operation_id(operation_id)
        with self._lock:
            entry = self._entries.get(normalized_id)
            if entry is None:
                raise OperationResultUnavailable(normalized_id)
            return OperationReceipt(
                operation_id=entry.operation_id,
                intent=self._snapshot(entry.intent),
                status=entry.status,
                result=(
                    self._snapshot(entry.result)
                    if entry.status == "succeeded"
                    else None
                ),
                failure=copy.deepcopy(entry.failure),
            )

    def _work_loop(self) -> None:
        while True:
            entry = self._queue.get()
            try:
                if entry is None:
                    return
                if isinstance(entry, _OperationEntry):
                    self._execute_operation(entry)
                else:
                    try:
                        entry.result = entry.work()
                    except BaseException as error:
                        entry.exception = error
                    finally:
                        entry.done.set()
            finally:
                self._queue.task_done()

    def close(self, wait: bool = True) -> None:
        """Drain accepted jobs before stopping the worker."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._queue.put(None)
        if wait and not self._is_worker_thread():
            self._worker.join()
