"""Pure rules of the confirmed-relationship record (`DET-03`)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trusttable_backend.domain.confirmed_relationship import (
    MAX_ACTIVE_RELATIONSHIPS,
    MAX_VERSIONS_PER_ANALYSIS,
    MAX_VERSIONS_PER_RELATIONSHIP,
    CheckStatus,
    ConfirmationSource,
    Rejection,
    RejectionCode,
    RelationshipKind,
    RelationshipState,
    RelationshipVersion,
    RoleColumn,
    Transition,
    TransitionRequest,
    active_relationship_count,
    next_version,
)

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
START = RoleColumn("start_date", 0)
END = RoleColumn("end_date", 1)


def _version(
    relationship_id: str = "r1",
    version: int = 1,
    transition: Transition | None = None,
) -> RelationshipVersion:
    chosen = transition or (Transition.CONFIRM if version == 1 else Transition.REPLACE)
    return RelationshipVersion(
        analysis_id="a1",
        relationship_id=relationship_id,
        version=version,
        kind=RelationshipKind.START_END_DATE,
        transition=chosen,
        start=START,
        end=END,
        source=ConfirmationSource.DIRECT,
        recorded_at=NOW,
    )


def _request(transition: Transition, **overrides: object) -> TransitionRequest:
    fields: dict[str, object] = {
        "transition": transition,
        "kind": RelationshipKind.START_END_DATE,
        "source": ConfirmationSource.DIRECT,
    }
    if transition is Transition.CONFIRM:
        fields.update(start=START, end=END)
    elif transition is Transition.REPLACE:
        fields.update(relationship_id="r1", expected_version=1, start=START, end=END)
    else:
        fields.update(relationship_id="r1", expected_version=1)
    fields.update(overrides)
    return TransitionRequest(**fields)  # type: ignore[arg-type]


def _decide(
    request: TransitionRequest, history: tuple[RelationshipVersion, ...]
) -> RelationshipVersion | Rejection:
    return next_version(
        request, history, new_relationship_id="new", recorded_at=NOW, analysis_id="a1"
    )


def test_check_status_never_reads_as_passed() -> None:
    assert CheckStatus.NOT_ACTIVE.value == "not_active"
    assert {status.value for status in CheckStatus} == {"not_active"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"version": 0},
        {"relationship_id": ""},
        {"relationship_id": "x" * 65},
        {"recorded_at": datetime(2026, 1, 1)},  # noqa: DTZ001 - the naive value is the case
        {"transition": Transition.REPLACE, "version": 1},
        {"transition": Transition.CONFIRM, "version": 2},
    ],
)
def test_an_invalid_version_cannot_be_constructed(kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {
        "analysis_id": "a1",
        "relationship_id": "r1",
        "version": 1,
        "kind": RelationshipKind.START_END_DATE,
        "transition": Transition.CONFIRM,
        "start": START,
        "end": END,
        "source": ConfirmationSource.DIRECT,
        "recorded_at": NOW,
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        RelationshipVersion(**base)  # type: ignore[arg-type]


def test_a_version_is_immutable_and_has_no_identity_or_free_text_field() -> None:
    version = _version()
    with pytest.raises(AttributeError):
        version.version = 2  # type: ignore[misc]
    assert {field for field in RelationshipVersion.__slots__} == {
        "analysis_id",
        "relationship_id",
        "version",
        "kind",
        "transition",
        "start",
        "end",
        "source",
        "recorded_at",
    }


def test_a_role_column_is_bounded() -> None:
    with pytest.raises(ValueError):
        RoleColumn("", 0)
    with pytest.raises(ValueError):
        RoleColumn("k" * 257, 0)
    with pytest.raises(ValueError):
        RoleColumn("k", -1)


def test_confirm_creates_version_one_of_a_new_relationship() -> None:
    result = _decide(_request(Transition.CONFIRM), ())

    assert isinstance(result, RelationshipVersion)
    assert (result.relationship_id, result.version) == ("new", 1)
    assert result.state is RelationshipState.ACTIVE


def test_replace_adds_the_next_version_with_new_roles() -> None:
    swapped = _request(Transition.REPLACE, start=END, end=START)

    result = _decide(swapped, (_version(),))

    assert isinstance(result, RelationshipVersion)
    assert (result.version, result.start, result.end) == (2, END, START)


def test_withdraw_keeps_the_roles_it_ends_and_is_terminal() -> None:
    withdrawn = _decide(_request(Transition.WITHDRAW), (_version(),))
    assert isinstance(withdrawn, RelationshipVersion)
    assert withdrawn.state is RelationshipState.WITHDRAWN
    assert (withdrawn.start, withdrawn.end) == (START, END)

    history = (_version(), withdrawn)
    for transition in (Transition.REPLACE, Transition.WITHDRAW):
        refused = _decide(_request(transition, expected_version=2), history)
        assert isinstance(refused, Rejection)
        assert refused.code is RejectionCode.WITHDRAWN


@pytest.mark.parametrize("transition", [Transition.REPLACE, Transition.WITHDRAW])
def test_a_stale_or_unknown_target_is_refused(transition: Transition) -> None:
    history = (_version(), _version(version=2))

    stale = _decide(_request(transition, expected_version=1), history)
    unknown = _decide(_request(transition, relationship_id="nope"), history)

    assert isinstance(stale, Rejection)
    assert (stale.code, stale.detail) == (RejectionCode.VERSION_CONFLICT, {"current_version": 2})
    assert isinstance(unknown, Rejection)
    assert unknown.code is RejectionCode.NOT_FOUND


@pytest.mark.parametrize(
    "request_",
    [
        _request(Transition.CONFIRM, relationship_id="r1", expected_version=1),
        _request(Transition.CONFIRM, end=None),
        _request(Transition.REPLACE, expected_version=None),
        _request(Transition.REPLACE, start=None),
        _request(Transition.WITHDRAW, start=START, end=END),
    ],
)
def test_malformed_requests_are_invalid_transitions(request_: TransitionRequest) -> None:
    result = _decide(request_, (_version(),))

    assert isinstance(result, Rejection)
    assert result.code is RejectionCode.INVALID_TRANSITION


def test_the_active_relationship_limit_ignores_withdrawn_relationships() -> None:
    history = tuple(_version(f"r{i}") for i in range(MAX_ACTIVE_RELATIONSHIPS))
    assert active_relationship_count(history) == MAX_ACTIVE_RELATIONSHIPS

    refused = _decide(_request(Transition.CONFIRM), history)
    assert isinstance(refused, Rejection)
    assert refused.code is RejectionCode.ACTIVE_LIMIT

    withdrawn = history + (_version("r0", 2, Transition.WITHDRAW),)
    assert active_relationship_count(withdrawn) == MAX_ACTIVE_RELATIONSHIPS - 1
    assert isinstance(_decide(_request(Transition.CONFIRM), withdrawn), RelationshipVersion)


def test_replace_stops_at_the_per_relationship_cap_but_withdraw_does_not() -> None:
    full = tuple(_version("r1", n) for n in range(1, MAX_VERSIONS_PER_RELATIONSHIP + 1))

    replace = _decide(
        _request(Transition.REPLACE, expected_version=MAX_VERSIONS_PER_RELATIONSHIP), full
    )
    withdraw = _decide(
        _request(Transition.WITHDRAW, expected_version=MAX_VERSIONS_PER_RELATIONSHIP), full
    )

    assert isinstance(replace, Rejection)
    assert replace.code is RejectionCode.VERSION_LIMIT
    assert isinstance(withdraw, RelationshipVersion)
    assert withdraw.version == MAX_VERSIONS_PER_RELATIONSHIP + 1


def test_the_analysis_total_stops_confirm_and_replace_but_never_withdraw() -> None:
    # Nine full relationships (450 versions) and ten short ones of 5 versions
    # each (50) reach the 500 total exactly.
    full = tuple(_version(f"f{i}", n) for i in range(9) for n in range(1, 51))
    short = tuple(_version(f"s{i}", n) for i in range(10) for n in range(1, 6))
    history = full + short
    assert len(history) == MAX_VERSIONS_PER_ANALYSIS

    confirm = _decide(_request(Transition.CONFIRM), history)
    replace = _decide(
        _request(Transition.REPLACE, relationship_id="s0", expected_version=5), history
    )
    withdraw_full = _decide(
        _request(Transition.WITHDRAW, relationship_id="f0", expected_version=50), history
    )
    withdraw_short = _decide(
        _request(Transition.WITHDRAW, relationship_id="s0", expected_version=5), history
    )

    for refused in (confirm, replace):
        assert isinstance(refused, Rejection)
        assert refused.code is RejectionCode.ANALYSIS_VERSION_LIMIT
    assert isinstance(withdraw_full, RelationshipVersion)
    assert isinstance(withdraw_short, RelationshipVersion)


def test_decisions_are_deterministic_for_the_same_input() -> None:
    history = (_version(),)
    request = _request(Transition.REPLACE)

    assert _decide(request, history) == _decide(request, history)
