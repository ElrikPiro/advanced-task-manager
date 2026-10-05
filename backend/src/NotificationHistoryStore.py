"""Persistent, non-destructive history for user-visible notifications."""

from __future__ import annotations

import datetime
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from src.AtomicFileStore import AtomicFileStore, AtomicWriteError
from src.Interfaces.IFileBroker import FileRegistry, IFileBroker
from src.MutationCoordinator import MutationCoordinator


_SCHEMA_VERSION = 1
_ENTRY_LIMIT = 1024
_REDACTION_MARKER = "[redactado]"
_ABSOLUTE_URL = re.compile(r"(?i)\b(?:https?|wss?)://[^\s<>\"']+")
_URL_QUERY = re.compile(r"\?[^\s<>\"']*")
_AUTHORIZATION_HEADER = re.compile(r"(?im)^.*\bauthorization\s*[:=].*$")
_BEARER_CREDENTIAL = re.compile(r"(?i)(\bBearer[ \t]+)[^\s,;]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:authorization|http[_-]?token|telegram[_-]?bot[_-]?token|"
    r"access[_-]?token|refresh[_-]?token|api[_-]?key|token|password|secret)"
    r"[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_CONFIG_ASSIGNMENT = re.compile(
    r"(?im)^\s*[\"']?(?:APP_MODE|JSON_PATH|HTTP_URL|HTTP_PORT|HTTP_API_PREFIX|"
    r"HTTP_TLS_CERT_CHAIN_PATH|HTTP_TLS_PRIVATE_KEY_PATH)[\"']?\s*[:=]"
)
_CONFIG_PATH = re.compile(r"(?i)(?:[A-Za-z]:[\\/]|/)[^\s\"']*config\.json\b")
_TRACEBACK = re.compile(r"(?is)Traceback \(most recent call last\):|^\s*File .+, line \d+")
_EXCEPTION_PREFIX = re.compile(r"(?i)^\s*[A-Za-z_][\w.]*(?:Error|Exception|Failure):")
_ISO_OFFSET_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)$"
)

EffectsState = Literal["none", "unknown"]


class NotificationHistoryError(RuntimeError):
    """Base error with safe, structured information for service adapters."""

    code = "notification-history-unavailable"

    def __init__(
        self,
        message: str,
        *,
        effects_state: EffectsState = "none",
        phase: str | None = None,
        write_replaced: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.effects_state = effects_state
        self.phase = phase
        self.write_replaced = write_replaced


class NotificationHistoryUnavailableError(NotificationHistoryError):
    """The history file is absent or cannot be read."""

    code = "notification-history-unavailable"

    def __init__(self) -> None:
        super().__init__("Notification history is unavailable")


class InvalidNotificationHistoryError(NotificationHistoryError):
    """The stored history is invalid and has been left untouched."""

    code = "notification-history-invalid"

    def __init__(self) -> None:
        super().__init__("Notification history is invalid")


class NotificationHistoryWriteError(NotificationHistoryError):
    """A complete history snapshot could not be confirmed as saved."""

    code = "notification-history-write-failed"

    def __init__(self, error: AtomicWriteError) -> None:
        effects_state: EffectsState = (
            "unknown" if error.effects_state == "unknown" else "none"
        )
        super().__init__(
            "Notification history could not be saved",
            effects_state=effects_state,
            phase=error.phase,
            write_replaced=error.replaced,
        )


class InvalidNotificationError(ValueError):
    """A notification cannot be added to the history."""


@dataclass(frozen=True)
class NotificationEntry:
    """One immutable notification in the retained history."""

    id: str
    sequence: int
    timestamp: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "text": self.text,
        }


@dataclass(frozen=True)
class NotificationHistorySnapshot:
    """An immutable point-in-time view of the complete retained history."""

    history_id: str
    next_sequence: int
    discarded_through: int
    entries: tuple[NotificationEntry, ...]
    schema_version: int = _SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "historyId": self.history_id,
            "nextSequence": self.next_sequence,
            "discardedThrough": self.discarded_through,
            "entries": [entry.to_dict() for entry in self.entries],
        }


class NotificationHistoryStore:
    """Store notifications as validated, atomic snapshots under the data path."""

    def __init__(
        self,
        file_broker: IFileBroker,
        mutation_coordinator: MutationCoordinator,
        token: str,
        atomic_file_store: AtomicFileStore | None = None,
    ) -> None:
        if not isinstance(token, str):
            raise TypeError("Notification history token must be text")
        broker_coordinator = getattr(file_broker, "mutation_coordinator", None)
        if broker_coordinator is not mutation_coordinator:
            raise ValueError("Notification history must share the file broker coordinator")
        self.path = file_broker.getFilePath(FileRegistry.NOTIFICATIONS_JSON)
        self._mutation_coordinator = mutation_coordinator
        self._token = token
        self._atomic_file_store = atomic_file_store or AtomicFileStore()

    def initialize(self) -> NotificationHistorySnapshot:
        """Create a new empty history only when startup explicitly requests it."""
        return cast(
            NotificationHistorySnapshot,
            self._mutation_coordinator.run_or_inline(self._initialize),
        )

    def read(self) -> NotificationHistorySnapshot:
        """Read a fresh complete snapshot without creating or changing the file."""
        raw = self._read_bytes()
        if raw is None:
            raise NotificationHistoryUnavailableError()
        return self._decode_snapshot(raw)

    def append(
        self,
        text: str,
        *,
        timestamp: datetime.datetime | None = None,
    ) -> NotificationEntry:
        """Persist one sanitized notification before returning its identity."""
        if not isinstance(text, str):
            raise InvalidNotificationError("Notification text must be text")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in text):
            raise InvalidNotificationError("Notification text must contain valid Unicode")
        timestamp_text = self._timestamp_text(timestamp)
        safe_text = self._sanitize_text(text)
        return cast(
            NotificationEntry,
            self._mutation_coordinator.run_or_inline(
                lambda: self._append(safe_text, timestamp_text)
            ),
        )

    def renew_history_id(self) -> NotificationHistorySnapshot:
        """Renew history identity while preserving entries and counters."""
        return cast(
            NotificationHistorySnapshot,
            self._mutation_coordinator.run_or_inline(self._renew_history_id),
        )

    def _initialize(self) -> NotificationHistorySnapshot:
        initial = NotificationHistorySnapshot(
            history_id=str(uuid4()),
            next_sequence=1,
            discarded_through=0,
            entries=(),
        )
        try:
            self._atomic_file_store.create_if_absent(
                self.path,
                self._encode_snapshot(initial),
                self._validate_bytes,
            )
        except AtomicWriteError as error:
            raise NotificationHistoryWriteError(error) from None
        return self.read()

    def _append(self, text: str, timestamp: str) -> NotificationEntry:
        def update(current: bytes | None) -> bytes:
            if current is None:
                raise NotificationHistoryUnavailableError()
            snapshot = self._decode_snapshot(current)
            sequence = snapshot.next_sequence
            created_entry = NotificationEntry(
                id=f"{snapshot.history_id}:{sequence}",
                sequence=sequence,
                timestamp=timestamp,
                text=text,
            )
            entries = list(snapshot.entries) + [created_entry]
            discarded_through = snapshot.discarded_through
            if len(entries) > _ENTRY_LIMIT:
                discarded_through = entries[-_ENTRY_LIMIT - 1].sequence
                entries = entries[-_ENTRY_LIMIT:]
            updated = NotificationHistorySnapshot(
                history_id=snapshot.history_id,
                next_sequence=sequence + 1,
                discarded_through=discarded_through,
                entries=tuple(entries),
            )
            return self._encode_snapshot(updated)

        try:
            saved = self._atomic_file_store.update(
                self.path,
                update,
                default=None,
                validator=self._validate_bytes,
            )
        except AtomicWriteError as error:
            raise NotificationHistoryWriteError(error) from None
        saved_snapshot = self._decode_snapshot(saved)
        return saved_snapshot.entries[-1]

    def _renew_history_id(self) -> NotificationHistorySnapshot:
        new_history_id = str(uuid4())

        def update(current: bytes | None) -> bytes:
            if current is None:
                raise NotificationHistoryUnavailableError()
            snapshot = self._decode_snapshot(current)
            fresh = NotificationHistorySnapshot(
                history_id=new_history_id,
                next_sequence=snapshot.next_sequence,
                discarded_through=snapshot.discarded_through,
                entries=tuple(
                    NotificationEntry(
                        id=f"{new_history_id}:{entry.sequence}",
                        sequence=entry.sequence,
                        timestamp=entry.timestamp,
                        text=entry.text,
                    )
                    for entry in snapshot.entries
                ),
            )
            return self._encode_snapshot(fresh)

        try:
            saved = self._atomic_file_store.update(
                self.path,
                update,
                default=None,
                validator=self._validate_bytes,
            )
        except AtomicWriteError as error:
            raise NotificationHistoryWriteError(error) from None
        return self._decode_snapshot(saved)

    def _read_bytes(self) -> bytes | None:
        try:
            with open(self.path, "rb") as history_file:
                return history_file.read()
        except FileNotFoundError:
            return None
        except OSError:
            raise NotificationHistoryUnavailableError() from None

    def _decode_snapshot(self, raw: bytes) -> NotificationHistorySnapshot:
        try:
            document = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=self._reject_duplicate_keys,
                parse_constant=self._reject_non_finite_json_value,
            )
            return self._snapshot_from_document(document)
        except InvalidNotificationHistoryError:
            raise
        except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
            raise InvalidNotificationHistoryError() from None

    def _snapshot_from_document(self, document: object) -> NotificationHistorySnapshot:
        if not isinstance(document, dict) or set(document) != {
            "schemaVersion",
            "historyId",
            "nextSequence",
            "discardedThrough",
            "entries",
        }:
            raise InvalidNotificationHistoryError()
        schema_version = document.get("schemaVersion")
        history_id = document.get("historyId")
        next_sequence = document.get("nextSequence")
        discarded_through = document.get("discardedThrough")
        raw_entries = document.get("entries")
        if type(schema_version) is not int or schema_version != _SCHEMA_VERSION:
            raise InvalidNotificationHistoryError()
        if not isinstance(history_id, str) or not self._is_canonical_uuid(history_id):
            raise InvalidNotificationHistoryError()
        if type(next_sequence) is not int or next_sequence < 1:
            raise InvalidNotificationHistoryError()
        if type(discarded_through) is not int or discarded_through < 0:
            raise InvalidNotificationHistoryError()
        if discarded_through >= next_sequence or not isinstance(raw_entries, list):
            raise InvalidNotificationHistoryError()
        if len(raw_entries) > _ENTRY_LIMIT:
            raise InvalidNotificationHistoryError()

        entries: list[NotificationEntry] = []
        expected_sequence = discarded_through + 1
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict) or set(raw_entry) != {
                "id",
                "sequence",
                "timestamp",
                "text",
            }:
                raise InvalidNotificationHistoryError()
            sequence = raw_entry.get("sequence")
            timestamp = raw_entry.get("timestamp")
            text = raw_entry.get("text")
            if type(sequence) is not int or sequence != expected_sequence:
                raise InvalidNotificationHistoryError()
            if not isinstance(timestamp, str) or not self._is_iso_offset_timestamp(timestamp):
                raise InvalidNotificationHistoryError()
            if not isinstance(text, str):
                raise InvalidNotificationHistoryError()
            if any(0xD800 <= ord(character) <= 0xDFFF for character in text):
                raise InvalidNotificationHistoryError()
            entry_id = f"{history_id}:{sequence}"
            if raw_entry.get("id") != entry_id:
                raise InvalidNotificationHistoryError()
            entries.append(
                NotificationEntry(
                    id=entry_id,
                    sequence=sequence,
                    timestamp=timestamp,
                    text=self._sanitize_text(text),
                )
            )
            expected_sequence += 1

        if entries and entries[-1].sequence != next_sequence - 1:
            raise InvalidNotificationHistoryError()
        if not entries and next_sequence != discarded_through + 1:
            raise InvalidNotificationHistoryError()
        return NotificationHistorySnapshot(
            schema_version=schema_version,
            history_id=history_id,
            next_sequence=next_sequence,
            discarded_through=discarded_through,
            entries=tuple(entries),
        )

    def _sanitize_text(self, text: str) -> str:
        if _TRACEBACK.search(text) or _EXCEPTION_PREFIX.search(text):
            return _REDACTION_MARKER
        if _CONFIG_ASSIGNMENT.search(text):
            return _REDACTION_MARKER
        sanitized = _CONFIG_PATH.sub(_REDACTION_MARKER, text)
        sanitized = _AUTHORIZATION_HEADER.sub(_REDACTION_MARKER, sanitized)
        sanitized = _ABSOLUTE_URL.sub(_REDACTION_MARKER, sanitized)
        sanitized = _URL_QUERY.sub(_REDACTION_MARKER, sanitized)
        if self._token and self._token != _REDACTION_MARKER:
            sanitized = sanitized.replace(self._token, _REDACTION_MARKER)
        sanitized = _SECRET_ASSIGNMENT.sub(
            lambda match: f"{match.group(1)}{_REDACTION_MARKER}", sanitized
        )
        sanitized = _BEARER_CREDENTIAL.sub(
            lambda match: match.group(1) + _REDACTION_MARKER,
            sanitized,
        )
        safe_characters = [
            " " if unicodedata.category(character) == "Cc" else character
            for character in sanitized
        ]
        return " ".join("".join(safe_characters).split())

    def _encode_snapshot(self, snapshot: NotificationHistorySnapshot) -> bytes:
        return json.dumps(
            snapshot.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def _validate_bytes(self, raw: bytes) -> None:
        self._decode_snapshot(raw)

    @staticmethod
    def _is_canonical_uuid(value: str) -> bool:
        try:
            return str(UUID(value)) == value
        except (ValueError, AttributeError, TypeError):
            return False

    @staticmethod
    def _is_iso_offset_timestamp(value: str) -> bool:
        if not _ISO_OFFSET_TIMESTAMP.fullmatch(value):
            return False
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            timestamp = datetime.datetime.fromisoformat(normalized)
        except ValueError:
            return False
        return timestamp.utcoffset() is not None

    @staticmethod
    def _timestamp_text(timestamp: datetime.datetime | None) -> str:
        value = timestamp if timestamp is not None else datetime.datetime.now().astimezone()
        if value.utcoffset() is None:
            raise InvalidNotificationError("Notification timestamp must include an offset")
        timestamp_text = value.isoformat()
        if not NotificationHistoryStore._is_iso_offset_timestamp(timestamp_text):
            raise InvalidNotificationError("Notification timestamp must use ISO 8601")
        return timestamp_text

    @staticmethod
    def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Notification history contains a duplicate key")
            result[key] = value
        return result

    @staticmethod
    def _reject_non_finite_json_value(value: str) -> None:
        raise ValueError("Notification history contains a non-finite JSON value")
