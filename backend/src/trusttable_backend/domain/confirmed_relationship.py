"""Confirmed relationships: the user-stated, versioned record (`DET-03`).

A *relationship* is something a user stated about one analysis: the first
kind, `start_end_date`, says that one column holds a start date and another
an end date. The system never infers it; a name, a label, a value pattern or
a model output is not a confirmation.

Every change (confirm, replace, withdraw) is a new immutable
`RelationshipVersion`. A relationship has a stable `relationship_id` that is
separate from its version number, so several relationships coexist and each
changes independently. Roles attach by `ColumnReference.internal_key` (kept
with its ordinal), never by a display name, and no column name or cell value
is stored.

This module is stdlib only and holds the pure rules; persistence lives in
`persistence.relationship_store`.

Withdrawal is final for its relationship: a later confirmation creates a new
relationship with a new id. A withdrawal is exempt from both version caps
(`SD-eb2bda99c6cc`), so a relationship at its cap can always be withdrawn;
growth stays bounded because each relationship is withdrawn at most once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

#: Storage limits (structural resource limits, not detector semantics).
MAX_ACTIVE_RELATIONSHIPS = 50
MAX_VERSIONS_PER_RELATIONSHIP = 50
MAX_VERSIONS_PER_ANALYSIS = 500

#: Bounds on identifiers carried in a request or stored.
MAX_KEY_LENGTH = 256
MAX_RELATIONSHIP_ID_LENGTH = 64


class RelationshipKind(StrEnum):
    """The relationship kinds. Each later context-bound detector adds its
    own kind through its own design; this is a discriminator, not a generic
    confirm-context route."""

    START_END_DATE = "start_end_date"


class Transition(StrEnum):
    CONFIRM = "confirm"
    REPLACE = "replace"
    WITHDRAW = "withdraw"


class ConfirmationSource(StrEnum):
    """Whether the user entered the confirmation directly or accepted it from
    a suggestion. There is no identity, client or free-text field."""

    DIRECT = "direct"
    SUGGESTION = "suggestion"


class RelationshipState(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class CheckStatus(StrEnum):
    """Whether a check exists for a relationship. An open, additive set:
    clients treat an unknown value as opaque. `NOT_ACTIVE` means no check
    exists to run; it never means the data passed one."""

    NOT_ACTIVE = "not_active"


class RejectionCode(StrEnum):
    """Stable machine-readable reasons a transition is refused."""

    INVALID_TRANSITION = "INVALID_RELATIONSHIP_TRANSITION"
    NOT_FOUND = "RELATIONSHIP_NOT_FOUND"
    WITHDRAWN = "RELATIONSHIP_WITHDRAWN"
    VERSION_CONFLICT = "RELATIONSHIP_VERSION_CONFLICT"
    UNKNOWN_COLUMN = "COLUMN_REFERENCE_NOT_IN_ANALYSIS"
    ACTIVE_LIMIT = "ACTIVE_RELATIONSHIP_LIMIT_REACHED"
    VERSION_LIMIT = "RELATIONSHIP_VERSION_LIMIT_REACHED"
    ANALYSIS_VERSION_LIMIT = "ANALYSIS_RELATIONSHIP_VERSION_LIMIT_REACHED"


@dataclass(frozen=True, slots=True)
class RoleColumn:
    """One role's column: the `ColumnReference` identity, without its name."""

    internal_key: str
    ordinal: int

    def __post_init__(self) -> None:
        if not self.internal_key or len(self.internal_key) > MAX_KEY_LENGTH:
            raise ValueError("RoleColumn.internal_key must be 1..256 characters")
        if self.ordinal < 0:
            raise ValueError("RoleColumn.ordinal must not be negative")


@dataclass(frozen=True, slots=True)
class RelationshipVersion:
    """One immutable version of one relationship in one analysis."""

    analysis_id: str
    relationship_id: str
    version: int
    kind: RelationshipKind
    transition: Transition
    start: RoleColumn
    end: RoleColumn
    source: ConfirmationSource
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not self.analysis_id:
            raise ValueError("RelationshipVersion.analysis_id must not be empty")
        if not self.relationship_id or len(self.relationship_id) > MAX_RELATIONSHIP_ID_LENGTH:
            raise ValueError("RelationshipVersion.relationship_id must be 1..64 characters")
        if self.version < 1:
            raise ValueError("RelationshipVersion.version must be at least 1")
        if (self.transition is Transition.CONFIRM) != (self.version == 1):
            raise ValueError("only version 1 is a confirm, and every confirm is version 1")
        if self.recorded_at.tzinfo is None:
            raise ValueError("RelationshipVersion.recorded_at must be timezone-aware")

    @property
    def state(self) -> RelationshipState:
        if self.transition is Transition.WITHDRAW:
            return RelationshipState.WITHDRAWN
        return RelationshipState.ACTIVE


@dataclass(frozen=True, slots=True)
class Rejection:
    """A refused transition. `detail` names only server-side facts (a limit
    name, a current version), never a value the client submitted."""

    code: RejectionCode
    detail: dict[str, int | str]


@dataclass(frozen=True, slots=True)
class TransitionRequest:
    """A requested change, already reduced to internal keys.

    `confirm` carries both roles and neither a relationship id nor an
    expected version; `replace` carries all four; `withdraw` carries the id
    and the expected version and no roles.
    """

    transition: Transition
    kind: RelationshipKind
    source: ConfirmationSource
    relationship_id: str | None = None
    expected_version: int | None = None
    start: RoleColumn | None = None
    end: RoleColumn | None = None

    def shape_error(self) -> str | None:
        """A fixed, value-free reason the request is malformed, or `None`."""
        has_target = self.relationship_id is not None and self.expected_version is not None
        has_partial_target = (self.relationship_id is None) != (self.expected_version is None)
        has_roles = self.start is not None and self.end is not None
        has_partial_roles = (self.start is None) != (self.end is None)
        if has_partial_target or has_partial_roles:
            return "incomplete"
        if self.transition is Transition.CONFIRM:
            return None if (not has_target and has_roles) else "confirm"
        if self.transition is Transition.REPLACE:
            return None if (has_target and has_roles) else "replace"
        return None if (has_target and not has_roles) else "withdraw"


def next_version(
    request: TransitionRequest,
    analysis_versions: tuple[RelationshipVersion, ...],
    *,
    new_relationship_id: str,
    recorded_at: datetime,
    analysis_id: str,
) -> RelationshipVersion | Rejection:
    """Decide a transition from the analysis's complete version history.

    Pure: the caller supplies every version of the analysis and, for a new
    relationship, a fresh id. Checks run in a fixed order so the same input
    always yields the same refusal.
    """
    if request.shape_error() is not None:
        return Rejection(RejectionCode.INVALID_TRANSITION, {})

    if request.transition is Transition.CONFIRM:
        assert request.start is not None and request.end is not None
        if len(analysis_versions) >= MAX_VERSIONS_PER_ANALYSIS:
            return Rejection(
                RejectionCode.ANALYSIS_VERSION_LIMIT, {"limit": MAX_VERSIONS_PER_ANALYSIS}
            )
        if active_relationship_count(analysis_versions) >= MAX_ACTIVE_RELATIONSHIPS:
            return Rejection(RejectionCode.ACTIVE_LIMIT, {"limit": MAX_ACTIVE_RELATIONSHIPS})
        return RelationshipVersion(
            analysis_id=analysis_id,
            relationship_id=new_relationship_id,
            version=1,
            kind=request.kind,
            transition=Transition.CONFIRM,
            start=request.start,
            end=request.end,
            source=request.source,
            recorded_at=recorded_at,
        )

    history = [v for v in analysis_versions if v.relationship_id == request.relationship_id]
    if not history:
        return Rejection(RejectionCode.NOT_FOUND, {})
    current = max(history, key=lambda v: v.version)
    if current.kind is not request.kind:
        return Rejection(RejectionCode.INVALID_TRANSITION, {})
    if current.state is RelationshipState.WITHDRAWN:
        return Rejection(RejectionCode.WITHDRAWN, {"current_version": current.version})
    if request.expected_version != current.version:
        return Rejection(RejectionCode.VERSION_CONFLICT, {"current_version": current.version})

    if request.transition is Transition.REPLACE:
        assert request.start is not None and request.end is not None
        if len(history) >= MAX_VERSIONS_PER_RELATIONSHIP:
            return Rejection(RejectionCode.VERSION_LIMIT, {"limit": MAX_VERSIONS_PER_RELATIONSHIP})
        if len(analysis_versions) >= MAX_VERSIONS_PER_ANALYSIS:
            return Rejection(
                RejectionCode.ANALYSIS_VERSION_LIMIT, {"limit": MAX_VERSIONS_PER_ANALYSIS}
            )
        start, end = request.start, request.end
    else:
        # Withdrawal: exempt from both version caps, carries the roles it ends.
        start, end = current.start, current.end

    return RelationshipVersion(
        analysis_id=analysis_id,
        relationship_id=current.relationship_id,
        version=current.version + 1,
        kind=current.kind,
        transition=request.transition,
        start=start,
        end=end,
        source=request.source,
        recorded_at=recorded_at,
    )


def active_relationship_count(analysis_versions: tuple[RelationshipVersion, ...]) -> int:
    """Relationships whose latest version is not a withdrawal."""
    latest: dict[str, RelationshipVersion] = {}
    for version in analysis_versions:
        held = latest.get(version.relationship_id)
        if held is None or version.version > held.version:
            latest[version.relationship_id] = version
    return sum(1 for v in latest.values() if v.state is RelationshipState.ACTIVE)
