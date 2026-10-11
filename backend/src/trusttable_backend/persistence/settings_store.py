"""`SqlSettingsStore` (`UX-08a`): durable storage of the allowlisted product
settings in `models.AppSettingRecord`.

The store enforces the closed allowlist and the value type itself (defense in
depth: the API validates first), and every write is an optimistic compare and
swap on `version`: a write whose `expected_version` is not the stored version
changes nothing and raises `SettingsVersionConflictError`. A key that was never
written has version 0. `reset` keeps the row with no value and a higher
version, so a version never repeats and a stale writer can never match an
earlier state.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from ..product_settings import ALLOWED_SETTINGS, UnknownSettingError, validate_setting
from .database import build_session_factory
from .models import AppSettingRecord


class SettingsVersionConflictError(Exception):
    """`expected_version` is not the stored version; nothing was changed."""

    def __init__(self, key: str, expected_version: int, actual_version: int) -> None:
        super().__init__(f"{key}: expected version {expected_version}, actual {actual_version}")
        self.key = key
        self.expected_version = expected_version
        self.actual_version = actual_version


@dataclass(frozen=True, slots=True)
class StoredSetting:
    key: str
    #: The stored value, or None when nothing is stored (never written or reset).
    value: object | None
    version: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqlSettingsStore:
    """A durable, allowlisted, typed and versioned settings store."""

    def __init__(self, engine: Engine) -> None:
        self._session_factory = build_session_factory(engine)
        self._lock = threading.Lock()

    def get(self, key: str) -> StoredSetting:
        """The stored state of an allowlisted key (version 0 if never written)."""
        validate_setting_key(key)
        with self._session_factory() as session:
            row = session.get(AppSettingRecord, key)
            if row is None:
                return StoredSetting(key=key, value=None, version=0)
            return StoredSetting(key=key, value=row.value_json, version=row.version)

    def put(self, key: str, value: object, *, expected_version: int) -> StoredSetting:
        """Store `value` if the stored version is `expected_version`."""
        validate_setting(key, value)
        return self._write(key, value, expected_version)

    def reset(self, key: str, *, expected_version: int) -> StoredSetting:
        """Remove the stored value (the default applies again)."""
        validate_setting_key(key)
        return self._write(key, None, expected_version)

    def _write(self, key: str, value: object | None, expected_version: int) -> StoredSetting:
        moment = _now()
        with self._lock, self._session_factory() as session:
            row = session.get(AppSettingRecord, key)
            actual = row.version if row is not None else 0
            if actual != expected_version:
                raise SettingsVersionConflictError(key, expected_version, actual)
            if row is None:
                session.add(
                    AppSettingRecord(key=key, value_json=value, version=1, updated_at=moment)
                )
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    raise SettingsVersionConflictError(key, expected_version, 1) from None
                return StoredSetting(key=key, value=value, version=1)
            result = session.execute(
                update(AppSettingRecord)
                .where(AppSettingRecord.key == key, AppSettingRecord.version == expected_version)
                .values(value_json=value, version=expected_version + 1, updated_at=moment)
            )
            if not result.rowcount:  # type: ignore[attr-defined]
                session.rollback()
                raise SettingsVersionConflictError(key, expected_version, actual + 1)
            session.commit()
            return StoredSetting(key=key, value=value, version=expected_version + 1)


def validate_setting_key(key: str) -> None:
    """Raise `UnknownSettingError` unless `key` is allowlisted."""
    if key not in ALLOWED_SETTINGS:
        raise UnknownSettingError(key)
