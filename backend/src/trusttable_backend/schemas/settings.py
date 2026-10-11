"""API schemas for the Settings routes (`UX-08a`, `docs/api-specification.md` §4).

`SettingsResponse` and the write request carry no URL, path, host, model path or
exception text: they are the ordinary settings surface. Only
`AdvancedSettingsResponse` carries the effective runtime and model
configuration (the narrow, owner-confirmed exception of D-066 item 5), and its
address is reduced to scheme, host and port: no user name, password, path, query
or fragment.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

SettingKey = Literal["ai_assistance"]
SettingSourceLabel = Literal["deployment", "stored", "default"]


class SettingItemResponse(BaseModel):
    key: SettingKey
    #: The effective value.
    value: bool
    #: Where the effective value comes from: an explicit deployment override, a
    #: value stored in the product, or the built-in default.
    source: SettingSourceLabel
    #: True when the installation configures this setting, so it is read-only here.
    managed_by_installation: bool
    #: The version a write or reset must quote (0 until the first write).
    version: int
    #: A plain-language explanation when the setting is read-only or on without
    #: anything to run; otherwise null.
    note: str | None


class SettingsResponse(BaseModel):
    settings: list[SettingItemResponse]


class SettingWriteRequest(BaseModel):
    """Set one allowlisted setting. Strict types: `1` and `"true"` are not booleans."""

    model_config = ConfigDict(extra="forbid")

    value: StrictBool
    expected_version: StrictInt = Field(ge=0, le=2**31 - 1)


class AdvancedSettingsResponse(BaseModel):
    """The effective AI runtime and model configuration, for the person who
    administers the installation. Not part of any analysis, finding or report."""

    ai_provider: str
    ai_assistance_source: SettingSourceLabel
    #: Scheme, host and port of the configured runtime; null when AI is off.
    runtime_address: str | None
    model_identifier: str | None
    timeout_seconds: int
    context_window: int
    sample_values_sent: bool
    max_sample_values: int
