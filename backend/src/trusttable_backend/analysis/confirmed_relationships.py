"""Application service for confirmed relationships (`DET-03`).

Framework-independent: no FastAPI or SQLAlchemy import. It resolves the
internal keys a client stated against the analysis's stored profile columns,
then hands the pure decision in `domain.confirmed_relationship` to a store
that applies it atomically. Nothing here infers a relationship, reads a
column name, or looks at a cell value.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ..domain.confirmed_relationship import (
    ConfirmationSource,
    Rejection,
    RejectionCode,
    RelationshipKind,
    RelationshipState,
    RelationshipVersion,
    RoleColumn,
    Transition,
    TransitionRequest,
    next_version,
)
from .service import Analysis, AnalysisState


class RelationshipStoreProtocol(Protocol):
    def list_versions(self, analysis_id: str) -> tuple[RelationshipVersion, ...]: ...

    def append(
        self,
        analysis_id: str,
        decide: Callable[[tuple[RelationshipVersion, ...]], RelationshipVersion | Rejection],
    ) -> RelationshipVersion | Rejection | None: ...


@dataclass(frozen=True, slots=True)
class RelationshipView:
    """One relationship: its current version and its full ordered history."""

    relationship_id: str
    kind: RelationshipKind
    state: RelationshipState
    current: RelationshipVersion
    history: tuple[RelationshipVersion, ...]


def is_available(analysis: Analysis) -> bool:
    """Roles resolve against the stored profile, which a completed analysis
    always has."""
    return analysis.state is AnalysisState.COMPLETED and analysis.dataset_profile is not None


def _columns_by_key(analysis: Analysis) -> dict[str, RoleColumn]:
    assert analysis.dataset_profile is not None  # guaranteed by `is_available`
    return {
        profile.column.internal_key: RoleColumn(
            internal_key=profile.column.internal_key, ordinal=profile.column.ordinal
        )
        for profile in analysis.dataset_profile.column_profiles
    }


def apply_transition(
    analysis: Analysis,
    store: RelationshipStoreProtocol,
    *,
    transition: Transition,
    kind: RelationshipKind,
    source: ConfirmationSource,
    relationship_id: str | None,
    expected_version: int | None,
    start_key: str | None,
    end_key: str | None,
    now: datetime | None = None,
    new_relationship_id: str | None = None,
) -> RelationshipVersion | Rejection | None:
    """Apply one user-stated transition to a completed analysis.

    Returns the stored `RelationshipVersion`, the `Rejection` explaining why
    nothing was stored, or `None` when the analysis no longer exists. The
    caller has already checked `is_available(analysis)`.
    """
    columns = _columns_by_key(analysis)
    try:
        provisional = TransitionRequest(
            transition=transition,
            kind=kind,
            source=source,
            relationship_id=relationship_id,
            expected_version=expected_version,
            start=RoleColumn(start_key, columns[start_key].ordinal if start_key in columns else 0)
            if start_key is not None
            else None,
            end=RoleColumn(end_key, columns[end_key].ordinal if end_key in columns else 0)
            if end_key is not None
            else None,
        )
    except ValueError:
        return Rejection(RejectionCode.INVALID_TRANSITION, {})
    if provisional.shape_error() is not None:
        return Rejection(RejectionCode.INVALID_TRANSITION, {})
    if (start_key is not None and start_key not in columns) or (
        end_key is not None and end_key not in columns
    ):
        return Rejection(RejectionCode.UNKNOWN_COLUMN, {})

    recorded_at = now or datetime.now(UTC)
    fresh_id = new_relationship_id or uuid.uuid4().hex

    def decide(
        versions: tuple[RelationshipVersion, ...],
    ) -> RelationshipVersion | Rejection:
        return next_version(
            provisional,
            versions,
            new_relationship_id=fresh_id,
            recorded_at=recorded_at,
            analysis_id=analysis.analysis_id,
        )

    return store.append(analysis.analysis_id, decide)


def project(versions: tuple[RelationshipVersion, ...]) -> tuple[RelationshipView, ...]:
    """Group versions into relationships, in the order each first appeared."""
    grouped: dict[str, list[RelationshipVersion]] = {}
    for version in versions:
        grouped.setdefault(version.relationship_id, []).append(version)
    views: list[RelationshipView] = []
    for relationship_id, history in grouped.items():
        ordered = tuple(sorted(history, key=lambda v: v.version))
        current = ordered[-1]
        views.append(
            RelationshipView(
                relationship_id=relationship_id,
                kind=current.kind,
                state=current.state,
                current=current,
                history=ordered,
            )
        )
    return tuple(views)
