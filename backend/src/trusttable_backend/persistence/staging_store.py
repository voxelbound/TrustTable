"""`SqlStagingStore` (`UX-02`, `docs/decision-log.md` D-068): temporary storage
of a chosen file's bytes behind an opaque, single-use reference.

Design points (each enforced in one SQL statement so concurrent callers cannot
race past a bound):

- The client-held reference is a 256-bit random URL-safe token. Only its
  SHA-256 digest is stored, so a copy of the database yields no usable
  reference. A malformed token is treated exactly like an unknown one and never
  reaches the database.
- Count and total-bytes bounds are checked by the same `INSERT ... SELECT`
  that stores the row, so two concurrent stagings cannot both pass a check
  that only one of them fits.
- `consume` is one `DELETE ... RETURNING` conditioned on the reference digest,
  the content digest recorded at staging and an unexpired row. Exactly one of
  any number of concurrent callers obtains the row.
- Expired rows are deleted before each write and read (and at startup by the
  application factory); SQLite `secure_delete` (set per connection in
  `database.py`) zeroes the freed content.

This store holds bytes and metadata only. It creates no analysis, no dataset
record and no durable identity, and it never returns the content digest to a
client (callers use it internally).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import and_, delete, func, insert, literal, select
from sqlalchemy.engine import Engine

from .database import build_session_factory
from .models import StagedUploadRecord

#: A reference is `secrets.token_urlsafe(32)`: 43 URL-safe base64 characters.
_REFERENCE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{43}$")
_REFERENCE_BYTES: Final[int] = 32


class StagingFullError(Exception):
    """The count or total-bytes bound would be exceeded; nothing was stored."""


@dataclass(frozen=True, slots=True)
class StagedUpload:
    """One staged file as read back from the store."""

    filename: str
    format: str
    byte_size: int
    content_sha256: str
    content: bytes
    created_at: datetime
    expires_at: datetime


def reference_digest(reference: str) -> str | None:
    """The SHA-256 hex digest of a well-formed reference, else `None`."""
    if not _REFERENCE_PATTERN.fullmatch(reference):
        return None
    return hashlib.sha256(reference.encode("ascii")).hexdigest()


def _iso(moment: datetime) -> str:
    # Fixed width (always microseconds, always UTC) so that comparing the
    # stored strings orders them in time.
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqlStagingStore:
    """A bounded, expiring store of staged uploads."""

    def __init__(
        self,
        engine: Engine,
        *,
        max_count: int,
        max_total_bytes: int,
        ttl: timedelta,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_count < 1 or max_total_bytes < 1 or ttl <= timedelta(0):
            raise ValueError("staging bounds must be positive")
        self._session_factory = build_session_factory(engine)
        self._max_count = max_count
        self._max_total_bytes = max_total_bytes
        self._ttl = ttl
        self._clock = clock

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def purge_expired(self) -> int:
        """Delete every expired row; return how many were deleted."""
        now = _iso(self._clock())
        with self._session_factory() as session:
            result = session.execute(
                delete(StagedUploadRecord).where(StagedUploadRecord.expires_at <= now)
            )
            session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]

    def stage(self, *, filename: str, file_format: str, content: bytes) -> tuple[str, StagedUpload]:
        """Store `content` and return `(reference, staged)`.

        Raises `StagingFullError` (storing nothing) when the count or total
        bytes bound would be exceeded.
        """
        self.purge_expired()
        reference = secrets.token_urlsafe(_REFERENCE_BYTES)
        digest = reference_digest(reference)
        if digest is None:  # pragma: no cover - token_urlsafe(32) always matches
            raise RuntimeError("generated an unusable staging reference")
        created = self._clock()
        expires = created + self._ttl
        content_sha256 = hashlib.sha256(content).hexdigest()
        values = {
            "ref_digest": digest,
            "created_at": _iso(created),
            "expires_at": _iso(expires),
            "filename": filename,
            "format": file_format,
            "byte_size": len(content),
            "content_sha256": content_sha256,
            "content": content,
        }
        count_now = select(func.count()).select_from(StagedUploadRecord).scalar_subquery()
        bytes_now = (
            select(func.coalesce(func.sum(StagedUploadRecord.byte_size), 0))
            .select_from(StagedUploadRecord)
            .scalar_subquery()
        )
        source = select(*(literal(value) for value in values.values())).where(
            and_(
                count_now < self._max_count,
                bytes_now + len(content) <= self._max_total_bytes,
            )
        )
        with self._session_factory() as session:
            result = session.execute(insert(StagedUploadRecord).from_select(list(values), source))
            session.commit()
            stored = bool(result.rowcount)  # type: ignore[attr-defined]
        if not stored:
            raise StagingFullError
        return reference, StagedUpload(
            filename=filename,
            format=file_format,
            byte_size=len(content),
            content_sha256=content_sha256,
            content=content,
            created_at=created,
            expires_at=expires,
        )

    def peek(self, reference: str) -> StagedUpload | None:
        """The staged file for `reference`, or `None` if unknown, malformed,
        expired or already consumed. Does not extend the expiry."""
        digest = reference_digest(reference)
        if digest is None:
            return None
        self.purge_expired()
        with self._session_factory() as session:
            row = session.get(StagedUploadRecord, digest)
            if row is None:
                return None
            return _to_staged(
                filename=row.filename,
                file_format=row.format,
                byte_size=row.byte_size,
                content_sha256=row.content_sha256,
                content=row.content,
                created_at=row.created_at,
                expires_at=row.expires_at,
            )

    def discard(self, reference: str) -> None:
        """Delete the staged file if present. Never reveals whether it was."""
        digest = reference_digest(reference)
        if digest is None:
            return
        with self._session_factory() as session:
            session.execute(
                delete(StagedUploadRecord).where(StagedUploadRecord.ref_digest == digest)
            )
            session.commit()

    def consume(self, reference: str, *, content_sha256: str) -> StagedUpload | None:
        """Atomically take the staged file, or `None` if it is unavailable.

        One `DELETE ... RETURNING` conditioned on the reference digest, the
        content digest recorded at staging and an unexpired row.
        """
        digest = reference_digest(reference)
        if digest is None:
            return None
        now = _iso(self._clock())
        statement = (
            delete(StagedUploadRecord)
            .where(
                StagedUploadRecord.ref_digest == digest,
                StagedUploadRecord.content_sha256 == content_sha256,
                StagedUploadRecord.expires_at > now,
            )
            .returning(
                StagedUploadRecord.filename,
                StagedUploadRecord.format,
                StagedUploadRecord.byte_size,
                StagedUploadRecord.content_sha256,
                StagedUploadRecord.content,
                StagedUploadRecord.created_at,
                StagedUploadRecord.expires_at,
            )
        )
        with self._session_factory() as session:
            row = session.execute(statement).first()
            session.commit()
        if row is None:
            return None
        return _to_staged(
            filename=row.filename,
            file_format=row.format,
            byte_size=row.byte_size,
            content_sha256=row.content_sha256,
            content=row.content,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )


def _to_staged(
    *,
    filename: str,
    file_format: str,
    byte_size: int,
    content_sha256: str,
    content: bytes,
    created_at: str,
    expires_at: str,
) -> StagedUpload:
    return StagedUpload(
        filename=filename,
        format=file_format,
        byte_size=byte_size,
        content_sha256=content_sha256,
        content=content,
        created_at=datetime.fromisoformat(created_at),
        expires_at=datetime.fromisoformat(expires_at),
    )
