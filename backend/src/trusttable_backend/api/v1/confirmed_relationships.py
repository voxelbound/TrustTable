"""Confirmed-relationship routes (`DET-03`, `docs/decision-log.md` D-059).

A user states, replaces or withdraws a relationship between columns of one
completed analysis. Every write is a new immutable version; the response
carries `check_status`, which in this foundation is always `not_active`
because no check exists to run (it never means "passed").

Access is the same as every other analysis route: the analysis id is the
only capability, and no identity or ownership is invented. Error bodies
carry only server-side facts (a limit, a current version), never a value
the client submitted.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from trusttable_backend.analysis.confirmed_relationships import (
    RelationshipStoreProtocol,
    RelationshipView,
    apply_transition,
    is_available,
    project,
)
from trusttable_backend.api.v1.analyses import _get_or_404, _not_found, get_analysis_store
from trusttable_backend.domain.confirmed_relationship import (
    CheckStatus,
    ConfirmationSource,
    Rejection,
    RejectionCode,
    RelationshipKind,
    RelationshipVersion,
    Transition,
)
from trusttable_backend.errors import AppError
from trusttable_backend.schemas.confirmed_relationship import (
    ConfirmedRelationshipModel,
    ConfirmedRelationshipRequest,
    ConfirmedRelationshipsResponse,
    ConfirmedRelationshipWriteResponse,
    RelationshipVersionModel,
    RoleColumnModel,
)

router = APIRouter(tags=["confirmed-relationships"])

_REJECTION_STATUS: dict[RejectionCode, tuple[int, str]] = {
    RejectionCode.INVALID_TRANSITION: (422, "The requested transition is not valid."),
    RejectionCode.NOT_FOUND: (404, "The requested relationship was not found."),
    RejectionCode.WITHDRAWN: (409, "The relationship has been withdrawn."),
    RejectionCode.VERSION_CONFLICT: (409, "The supplied version is out of date."),
    RejectionCode.UNKNOWN_COLUMN: (422, "A column is not part of this analysis."),
    RejectionCode.ACTIVE_LIMIT: (409, "The active relationship limit was reached."),
    RejectionCode.VERSION_LIMIT: (409, "The relationship version limit was reached."),
    RejectionCode.ANALYSIS_VERSION_LIMIT: (409, "The analysis version limit was reached."),
}


def get_relationship_store(request: Request) -> RelationshipStoreProtocol:
    """Return the current app's durable `SqlRelationshipStore`."""
    store: RelationshipStoreProtocol = request.app.state.relationship_store
    return store


def _not_available(analysis_id: str, state: str) -> AppError:
    return AppError(
        "INVALID_ANALYSIS_STATE",
        "Confirmed relationships are not available for this analysis in its current state.",
        status_code=409,
        details={"analysis_id": analysis_id, "state": state},
    )


def _rejection_error(analysis_id: str, rejection: Rejection) -> AppError:
    status_code, message = _REJECTION_STATUS[rejection.code]
    return AppError(
        rejection.code.value,
        message,
        status_code=status_code,
        details={"analysis_id": analysis_id, **rejection.detail},
    )


def _version_model(version: RelationshipVersion) -> RelationshipVersionModel:
    return RelationshipVersionModel(
        relationship_id=version.relationship_id,
        version=version.version,
        kind=version.kind.value,
        transition=version.transition.value,
        state=version.state.value,
        start=RoleColumnModel(
            internal_key=version.start.internal_key, ordinal=version.start.ordinal
        ),
        end=RoleColumnModel(internal_key=version.end.internal_key, ordinal=version.end.ordinal),
        source=version.source.value,
        recorded_at=version.recorded_at,
    )


def _relationship_model(view: RelationshipView) -> ConfirmedRelationshipModel:
    return ConfirmedRelationshipModel(
        relationship_id=view.relationship_id,
        kind=view.kind.value,
        state=view.state.value,
        check_status=CheckStatus.NOT_ACTIVE.value,
        current=_version_model(view.current),
        history=[_version_model(version) for version in view.history],
    )


@router.post(
    "/analyses/{analysis_id}/confirmed-relationships",
    status_code=201,
    response_model=ConfirmedRelationshipWriteResponse,
    responses={200: {"model": ConfirmedRelationshipWriteResponse}},
)
def write_confirmed_relationship(
    analysis_id: str,
    body: ConfirmedRelationshipRequest,
    request: Request,
    response: Response,
) -> ConfirmedRelationshipWriteResponse:
    """Confirm, replace or withdraw a user-stated relationship.

    `201` for a new relationship, `200` for a new version of an existing one.
    Clients rely on the returned identifiers and `check_status`, not on the
    status code alone.
    """
    analysis = _get_or_404(get_analysis_store(request), analysis_id)
    if not is_available(analysis):
        raise _not_available(analysis_id, analysis.state.value)
    outcome = apply_transition(
        analysis,
        get_relationship_store(request),
        transition=Transition(body.transition),
        kind=RelationshipKind(body.kind),
        source=ConfirmationSource(body.source),
        relationship_id=body.relationship_id,
        expected_version=body.expected_version,
        start_key=body.start,
        end_key=body.end,
    )
    if outcome is None:
        # Deleted between the check above and the insert (`DEL-01`).
        raise _not_found(analysis_id)
    if isinstance(outcome, Rejection):
        raise _rejection_error(analysis_id, outcome)
    response.status_code = 201 if outcome.transition is Transition.CONFIRM else 200
    return ConfirmedRelationshipWriteResponse(
        relationship_id=outcome.relationship_id,
        version=outcome.version,
        state=outcome.state.value,
        check_status=CheckStatus.NOT_ACTIVE.value,
        recorded_at=outcome.recorded_at,
    )


@router.get(
    "/analyses/{analysis_id}/confirmed-relationships",
    response_model=ConfirmedRelationshipsResponse,
)
def list_confirmed_relationships(
    analysis_id: str, request: Request
) -> ConfirmedRelationshipsResponse:
    """Return every relationship's current version and its full history."""
    _get_or_404(get_analysis_store(request), analysis_id)
    versions = get_relationship_store(request).list_versions(analysis_id)
    return ConfirmedRelationshipsResponse(
        relationships=[_relationship_model(view) for view in project(versions)]
    )
