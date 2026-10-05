"""Atomic, single-file persistence for UTF-8 application data."""

from __future__ import annotations

import os
import re
import secrets
import stat
import threading
from dataclasses import dataclass
from typing import Callable, Literal


class AtomicWriteError(OSError):
    """A file write failed, with the known state of the destination."""

    def __init__(
        self,
        path: str,
        phase: str,
        effects_state: Literal["none", "unknown"],
        replaced: bool | None,
        cause: BaseException,
    ) -> None:
        super().__init__(f"Atomic write failed during {phase} for {path}: {cause}")
        self.path = path
        self.phase = phase
        self.effects_state = effects_state
        self.replaced = replaced
        self.cause = cause


class AtomicWriteConflictError(AtomicWriteError):
    """The destination changed during every bounded write attempt."""

    def __init__(self, path: str, attempts: int, reason: str = "destination changed") -> None:
        super().__init__(
            path=path,
            phase="compare",
            effects_state="none",
            replaced=False,
            cause=RuntimeError(f"{reason} after {attempts} attempts"),
        )
        self.attempts = attempts
        self.reason = reason


@dataclass(frozen=True)
class _Snapshot:
    content: bytes | None
    mode: int | None
    signature: tuple[int, int, int, int, int, int] | None

    @property
    def exists(self) -> bool:
        return self.content is not None


class _SnapshotChanged(Exception):
    """A path changed while its snapshot was being read."""


class AtomicFileStore:
    """Write complete files by preparing beside the target and replacing it.

    Updates run under a per-path process lock. The snapshot is checked again
    immediately before publication, but editors that do not share this lock
    can still write in the small interval between that comparison and replace.
    """

    MAX_ATTEMPTS = 3
    _TEMP_NAME = re.compile(r"^\.elrik-atomic-[0-9a-f]{32}\.tmp$")
    _locks: dict[str, threading.RLock] = {}
    _locks_guard = threading.Lock()

    @classmethod
    def _lock_for(cls, path: str) -> threading.RLock:
        normalized = os.path.normcase(os.path.abspath(path))
        with cls._locks_guard:
            lock = cls._locks.get(normalized)
            if lock is None:
                lock = threading.RLock()
                cls._locks[normalized] = lock
            return lock

    @staticmethod
    def _signature(file_stat: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            file_stat.st_dev,
            file_stat.st_ino,
            file_stat.st_size,
            file_stat.st_mtime_ns,
            file_stat.st_ctime_ns,
            stat.S_IMODE(file_stat.st_mode),
        )

    @classmethod
    def _read_snapshot(cls, path: str) -> _Snapshot:
        try:
            file = open(path, "rb")
        except FileNotFoundError:
            return _Snapshot(None, None, None)

        with file:
            before = os.fstat(file.fileno())
            content = file.read()
            after = os.fstat(file.fileno())

        try:
            path_stat = os.stat(path)
        except FileNotFoundError as error:
            raise _SnapshotChanged from error

        before_signature = cls._signature(before)
        after_signature = cls._signature(after)
        path_signature = cls._signature(path_stat)
        if before_signature != after_signature:
            raise _SnapshotChanged
        if (after.st_dev, after.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise _SnapshotChanged
        if after_signature != path_signature:
            raise _SnapshotChanged
        return _Snapshot(content, stat.S_IMODE(after.st_mode), after_signature)

    @staticmethod
    def _same_snapshot(left: _Snapshot, right: _Snapshot) -> bool:
        return all((
            left.content == right.content,
            left.mode == right.mode,
            left.signature == right.signature,
        ))

    @staticmethod
    def _temp_path(directory: str) -> str:
        return os.path.join(
            directory,
            f".elrik-atomic-{secrets.token_hex(16)}.tmp",
        )

    @classmethod
    def is_temporary_file_name(cls, filename: str) -> bool:
        """Return whether a basename belongs to this store's reserved namespace."""
        return cls._TEMP_NAME.fullmatch(filename) is not None

    @staticmethod
    def _remove_temp(temp_path: str | None) -> None:
        if temp_path is None:
            return
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        except OSError:
            # A leftover with our strict name is safe to remove on next startup.
            pass

    @staticmethod
    def _fsync_directory(directory: str) -> None:
        if os.name != "posix":
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _stage(
        path: str,
        content: bytes,
        mode: int | None,
        validator: Callable[[bytes], None] | None,
    ) -> str:
        directory = os.path.dirname(os.path.abspath(path))
        temp_path = AtomicFileStore._temp_path(directory)
        descriptor = -1
        phase = "temporary_create"
        try:
            descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            phase = "write"
            file = os.fdopen(descriptor, "wb")
            descriptor = -1
            with file:
                written = file.write(content)
                if written != len(content):
                    raise OSError("short write to temporary file")
                phase = "permissions"
                if mode is not None and hasattr(os, "fchmod"):
                    os.fchmod(file.fileno(), mode)
                phase = "flush"
                file.flush()
                phase = "file_fsync"
                os.fsync(file.fileno())

            phase = "temporary_validate"
            with open(temp_path, "rb") as staged:
                staged_content = staged.read()
            if staged_content != content:
                raise OSError("temporary file content differs from the prepared content")
            if validator is not None:
                validator(staged_content)
            return temp_path
        except Exception as error:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            AtomicFileStore._remove_temp(temp_path)
            raise _StageFailure(phase, error) from error

    def update(
        self,
        path: str,
        updater: Callable[[bytes | None], bytes],
        default: bytes | None = None,
        validator: Callable[[bytes], None] | None = None,
    ) -> bytes:
        """Recalculate against current bytes and publish a complete file.

        The updater can run up to three times when an outside editor changes
        the destination during preparation. It should therefore be pure.
        """
        absolute_path = os.path.abspath(path)
        with self._lock_for(absolute_path):
            initial_existence: bool | None = None
            for attempt in range(1, self.MAX_ATTEMPTS + 1):
                try:
                    snapshot = self._read_snapshot(absolute_path)
                except _SnapshotChanged:
                    continue
                except OSError as error:
                    raise AtomicWriteError(absolute_path, "read", "none", False, error) from error

                if initial_existence is None:
                    initial_existence = snapshot.exists
                current = snapshot.content if snapshot.exists else default
                content = updater(current)
                if not isinstance(content, bytes):
                    raise TypeError("Atomic file updater must return bytes")
                if validator is not None:
                    validator(content)

                directory = os.path.dirname(absolute_path)
                try:
                    os.makedirs(directory, exist_ok=True)
                except OSError as error:
                    raise AtomicWriteError(absolute_path, "directory_create", "none", False, error) from error

                try:
                    temp_path = self._stage(absolute_path, content, snapshot.mode, validator)
                except _StageFailure as failure:
                    if isinstance(failure.cause, OSError):
                        raise AtomicWriteError(
                            absolute_path,
                            failure.phase,
                            "none",
                            False,
                            failure.cause,
                        ) from failure.cause
                    raise failure.cause

                try:
                    current_snapshot = self._read_snapshot(absolute_path)
                except _SnapshotChanged:
                    self._remove_temp(temp_path)
                    continue
                except OSError as error:
                    self._remove_temp(temp_path)
                    raise AtomicWriteError(absolute_path, "compare", "none", False, error) from error

                if not self._same_snapshot(snapshot, current_snapshot):
                    self._remove_temp(temp_path)
                    if initial_existence and not current_snapshot.exists:
                        raise AtomicWriteConflictError(absolute_path, attempt, "destination disappeared")
                    if attempt == self.MAX_ATTEMPTS:
                        raise AtomicWriteConflictError(absolute_path, attempt)
                    continue

                try:
                    os.replace(temp_path, absolute_path)
                except Exception as error:
                    self._remove_temp(temp_path)
                    raise AtomicWriteError(absolute_path, "replace", "unknown", None, error) from error

                try:
                    self._fsync_directory(directory)
                except Exception as error:
                    raise AtomicWriteError(absolute_path, "directory_fsync", "unknown", True, error) from error
                return content

            raise AtomicWriteConflictError(absolute_path, self.MAX_ATTEMPTS)

    def write(
        self,
        path: str,
        content: bytes,
        validator: Callable[[bytes], None] | None = None,
    ) -> bytes:
        """Publish caller-provided complete content through the same primitive."""
        return self.update(path, lambda _current: content, validator=validator)

    def create_if_absent(
        self,
        path: str,
        content: bytes,
        validator: Callable[[bytes], None] | None = None,
    ) -> bool:
        """Publish a new file atomically without replacing an existing path."""
        absolute_path = os.path.abspath(path)
        with self._lock_for(absolute_path):
            if os.path.lexists(absolute_path):
                return False
            try:
                os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
            except OSError as error:
                raise AtomicWriteError(absolute_path, "directory_create", "none", False, error) from error

            if validator is not None:
                validator(content)
            try:
                temp_path = self._stage(absolute_path, content, None, validator)
            except _StageFailure as failure:
                if isinstance(failure.cause, OSError):
                    raise AtomicWriteError(
                        absolute_path,
                        failure.phase,
                        "none",
                        False,
                        failure.cause,
                    ) from failure.cause
                raise failure.cause

            try:
                os.link(temp_path, absolute_path)
            except FileExistsError:
                self._remove_temp(temp_path)
                return False
            except Exception as error:
                self._remove_temp(temp_path)
                raise AtomicWriteError(absolute_path, "publish", "unknown", None, error) from error

            self._remove_temp(temp_path)
            try:
                self._fsync_directory(os.path.dirname(absolute_path))
            except Exception as error:
                raise AtomicWriteError(absolute_path, "directory_fsync", "unknown", True, error) from error
            return True

    @classmethod
    def cleanup_temporary_files(cls, directories: list[str]) -> int:
        """Remove only regular, unpublished temporaries with this store's name."""
        roots = sorted({os.path.abspath(directory) for directory in directories if directory})
        removed = 0
        visited: set[str] = set()
        for root in roots:
            if not os.path.isdir(root):
                continue
            for current, child_directories, filenames in os.walk(root, followlinks=False):
                normalized_current = os.path.normcase(os.path.abspath(current))
                if normalized_current in visited:
                    child_directories[:] = []
                    continue
                visited.add(normalized_current)
                child_directories[:] = [
                    name for name in child_directories
                    if not os.path.islink(os.path.join(current, name))
                ]
                for filename in filenames:
                    if not cls.is_temporary_file_name(filename):
                        continue
                    candidate = os.path.join(current, filename)
                    try:
                        candidate_stat = os.lstat(candidate)
                        if not stat.S_ISREG(candidate_stat.st_mode):
                            continue
                        if candidate_stat.st_nlink > 1:
                            # A linked target may already have been published by create_if_absent.
                            continue
                        os.unlink(candidate)
                        removed += 1
                    except FileNotFoundError:
                        pass
        return removed


class _StageFailure(Exception):
    def __init__(self, phase: str, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.phase = phase
        self.cause = cause
