"""`SqlRelationshipStore` (`DET-03`): durable, insert-only storage of
immutable `RelationshipVersion` values in
`models.ConfirmedRelationshipVersionRecord`.

There is deliberately no update and no individual delete: a version is a
fixed fact, and all of an analysis's versions end with the analysis
(`SqlAnalysisStore.delete`). Writes are version-aware and atomic:

* the decision (`decide`) is made from the analysis's complete stored
  history inside a store-wide lock, so two writers in this process cannot
  interleave;
* the unique `(analysis, relationship, version)` key is the backstop across
  independent store instances or processes: the second writer's insert
  fails and is reported as a version conflict, never as a second version;
* the insert is `INSERT ... SELECT ... WHERE EXISTS (analysis)`, so a late
  write for a deleted analysis stores nothing (`DEL-01`).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import exists, insert, literal, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.confirmed_relationship import (
    ConfirmationSource,
    Rejection,
    RejectionCode,
    RelationshipKind,
    RelationshipVersion,
    RoleColumn,
    Transition,
)
from .database import build_session_factory
from .models import AnalysisRecord, ConfirmedRelationshipVersionRecord

#: Decides the next version (or a refusal) from every stored version of the
#: analysis, in insertion order.
Decide = Callable[[tuple[RelationshipVersion, ...]], RelationshipVersion | Rejection]


def _to_version(row: ConfirmedRelationshipVersionRecord) -> RelationshipVersion:
    return RelationshipVersion(
        analysis_id=row.analysis_id,
        relationship_id=row.relationship_id,
        version=row.version,
        kind=RelationshipKind(row.kind),
        transition=Transition(row.transition),
        start=RoleColumn(internal_key=row.start_key, ordinal=row.start_ordinal),
        end=RoleColumn(internal_key=row.end_key, ordinal=row.end_ordinal),
        source=ConfirmationSource(row.source),
        recorded_at=datetime.fromisoformat(row.recorded_at),
    )


def _read(session: Session, analysis_id: str) -> tuple[RelationshipVersion, ...]:
    rows = session.scalars(
        select(ConfirmedRelationshipVersionRecord)
        .where(ConfirmedRelationshipVersionRecord.analysis_id == analysis_id)
        .order_by(ConfirmedRelationshipVersionRecord.seq)
    ).all()
    return tuple(_to_version(row) for row in rows)


class SqlRelationshipStore:
    """A durable, insert-only store of relationship versions."""

    def __init__(self, engine: Engine) -> None:
        self._session_factory = build_session_factory(engine)
        self._write_lock = threading.Lock()

    def list_versions(self, analysis_id: str) -> tuple[RelationshipVersion, ...]:
        """Every version of the analysis, in insertion order."""
        with self._session_factory() as session:
            return _read(session, analysis_id)

    def append(self, analysis_id: str, decide: Decide) -> RelationshipVersion | Rejection | None:
        """Atomically decide and store the next version.

        Returns the stored version, the `Rejection` the decision produced,
        or `None` when the analysis no longer exists (nothing is stored).
        """
        with self._write_lock, self._session_factory() as session:
            outcome = decide(_read(session, analysis_id))
            if isinstance(outcome, Rejection):
                return outcome
            try:
                if not self._insert(session, outcome):
                    session.rollback()
                    return None
                session.commit()
            except IntegrityError:
                session.rollback()
                return self._conflict(session, analysis_id, decide)
            return outcome

    @staticmethod
    def _insert(session: Session, version: RelationshipVersion) -> bool:
        values = {
            "analysis_id": version.analysis_id,
            "relationship_id": version.relationship_id,
            "version": version.version,
            "kind": version.kind.value,
            "transition": version.transition.value,
            "start_key": version.start.internal_key,
            "start_ordinal": version.start.ordinal,
            "end_key": version.end.internal_key,
            "end_ordinal": version.end.ordinal,
            "source": version.source.value,
            "recorded_at": version.recorded_at.isoformat(),
        }
        source = select(*(literal(value) for value in values.values())).where(
            exists().where(AnalysisRecord.analysis_id == version.analysis_id)
        )
        result = session.execute(
            insert(ConfirmedRelationshipVersionRecord).from_select(list(values), source)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    @staticmethod
    def _conflict(session: Session, analysis_id: str, decide: Decide) -> Rejection:
        """The unique key refused a concurrent second writer: report the
        precise refusal against the now-current history."""
        retry = decide(_read(session, analysis_id))
        if isinstance(retry, Rejection):
            return retry
        return Rejection(RejectionCode.VERSION_CONFLICT, {})
