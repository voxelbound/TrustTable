"""Pydantic schemas for the confirmed-relationship routes (`DET-03`,
`docs/api-specification.md`).

Requests are strict: unknown fields are rejected, every string is bounded,
there is no free-text field, and a column is named only by its internal key.
An unknown kind or transition fails validation through the generic
`INVALID_REQUEST` envelope, which never echoes a submitted value.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from trusttable_backend.domain.confirmed_relationship import (
    MAX_KEY_LENGTH,
    MAX_RELATIONSHIP_ID_LENGTH,
)


class ConfirmedRelationshipRequest(BaseModel):
    """Body for `POST /analyses/{analysis_id}/confirmed-relationships`.

    `confirm` carries `start` and `end` only. `replace` carries
    `relationship_id`, `expected_version`, `start` and `end`. `withdraw`
    carries `relationship_id` and `expected_version` only.
    """

    model_config = ConfigDict(extra="forbid")

    transition: Literal["confirm", "replace", "withdraw"]
    kind: Literal["start_end_date"]
    relationship_id: str | None = Field(
        default=None, min_length=1, max_length=MAX_RELATIONSHIP_ID_LENGTH
    )
    expected_version: int | None = Field(default=None, ge=1, le=100_000)
    start: str | None = Field(default=None, min_length=1, max_length=MAX_KEY_LENGTH)
    end: str | None = Field(default=None, min_length=1, max_length=MAX_KEY_LENGTH)
    source: Literal["direct", "suggestion"] = "direct"


class RoleColumnModel(BaseModel):
    """A role's `ColumnReference` identity: the internal key and ordinal."""

    internal_key: str
    ordinal: int


class RelationshipVersionModel(BaseModel):
    """One immutable version. Provenance is server-set only: the version
    number, a server timestamp and the entry source."""

    relationship_id: str
    version: int
    kind: str
    transition: str
    state: str
    start: RoleColumnModel
    end: RoleColumnModel
    source: str
    recorded_at: datetime


class ConfirmedRelationshipWriteResponse(BaseModel):
    """Result of one write.

    `check_status` states whether a check exists for the relationship. The
    set of values is open and additive: a client treats an unknown value as
    opaque. `not_active` means no check exists to run and never means the
    data passed one.
    """

    relationship_id: str
    version: int
    state: str
    check_status: str
    recorded_at: datetime


class ConfirmedRelationshipModel(BaseModel):
    """A relationship: its current version and its full ordered history."""

    relationship_id: str
    kind: str
    state: str
    check_status: str
    current: RelationshipVersionModel
    history: list[RelationshipVersionModel]


class ConfirmedRelationshipsResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/confirmed-relationships`."""

    relationships: list[ConfirmedRelationshipModel]
