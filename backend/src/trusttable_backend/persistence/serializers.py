"""Lossless to/from-dict conversion for the `Analysis` aggregate (`DB-01`).

A single generic, self-describing codec (`encode`/`decode`) handles every
nested dataclass/enum/tuple/frozenset/`Mapping`/`datetime`/`bytes` value
`analysis.service.Analysis` and everything it transitively references
(`Dataset`, `DatasetProfile`, `FindingCandidate`, `Evidence`,
`TrustAssessment`, `DatasetContext`, `ClarificationQuestion`,
`SecurityExposureState`, `AnalysisFailure`, ...) already contains today,
instead of one hand-written mapping per type. This is deliberate, not a
shortcut: `analysis.service`'s own `Analysis.__post_init__` and every
nested dataclass's `__post_init__` already define the single source of
truth for "what is a valid instance of this type" — `decode` reconstructs
every dataclass by calling `cls(**fields)`, which re-runs that exact
`__post_init__` on the way back in. A corrupted/malformed persisted row
therefore raises on read (AC-03) as a direct, structural consequence of
this design, not a separately-maintained check.

Every encoded node is a JSON-safe primitive, or a tagged object
`{"__t": <tag>, ...}` distinguishing it from an ordinary `dict`-shaped
domain value (`Evidence.structured_payload`, `ColumnProfile.metrics`,
`DatasetProfile.dataset_metrics`, all `Mapping[str, object]`) — a real
domain `dict` is itself tagged (`"__t": "dict"`) so the two can never be
confused during decode.

`_resolve` only imports modules under this project's own
`trusttable_backend.` package — a deliberate, defense-in-depth refusal to
resolve/import an arbitrary class name a corrupted or tampered database
row might otherwise name (this database is local-only and not untrusted
input in the threat-model sense, but nothing in this module depends on
that fact).
"""

from __future__ import annotations

import base64
import importlib
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

_ALLOWED_MODULE_PREFIX = "trusttable_backend."
_ALLOWED_MODULE_EXACT = "trusttable_backend"


def _resolve(module_name: str, qualname: str) -> type:
    if module_name != _ALLOWED_MODULE_EXACT and not module_name.startswith(_ALLOWED_MODULE_PREFIX):
        raise ValueError(f"refusing to resolve disallowed module for decode: {module_name!r}")
    module = importlib.import_module(module_name)
    obj: Any = module
    for part in qualname.split("."):
        obj = getattr(obj, part)
    if not isinstance(obj, type):
        raise ValueError(f"resolved object is not a type: {module_name}.{qualname}")
    return obj


def encode(value: Any) -> Any:
    """Encode one Python value into a JSON-safe structure.

    `bool`/`int`/`float`/`str`/`None` pass through unchanged (JSON already
    represents them natively). The `Enum` check runs *before* this
    primitive check, deliberately: this codebase's enums are all
    `StrEnum` (`str` subclasses), so an unordered `isinstance(value, str)`
    check would silently accept a `StrEnum` member as a plain string,
    losing its type on the way back in (the exact defect this ordering
    prevents — verified by `test_serializers.py`'s own enum round-trip
    test against a real nested-dataclass nested-enum field).
    """
    if isinstance(value, Enum):
        cls = type(value)
        return {"__t": "enum", "m": cls.__module__, "q": cls.__qualname__, "v": value.value}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"__t": "bytes", "v": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        return {"__t": "datetime", "v": value.isoformat()}
    if is_dataclass(value) and not isinstance(value, type):
        dataclass_cls = type(value)
        return {
            "__t": "dataclass",
            "m": dataclass_cls.__module__,
            "q": dataclass_cls.__qualname__,
            "f": {f.name: encode(getattr(value, f.name)) for f in fields(value)},
        }
    if isinstance(value, tuple):
        return {"__t": "tuple", "v": [encode(x) for x in value]}
    if isinstance(value, frozenset):
        return {"__t": "frozenset", "v": [encode(x) for x in value]}
    if isinstance(value, list):
        return {"__t": "list", "v": [encode(x) for x in value]}
    if isinstance(value, Mapping):
        return {"__t": "dict", "v": [[encode(k), encode(v)] for k, v in value.items()]}
    raise TypeError(f"persistence.serializers.encode: unsupported value type {type(value)!r}")


def decode(value: Any) -> Any:
    """Decode one `encode`-produced JSON-safe structure back to Python.

    Reconstructs every dataclass via `cls(**fields)`, re-running that
    class's own `__post_init__` invariant checks (see module docstring).
    """
    if not isinstance(value, dict) or "__t" not in value:
        return value
    tag = value["__t"]
    if tag == "bytes":
        return base64.b64decode(value["v"])
    if tag == "datetime":
        return datetime.fromisoformat(value["v"])
    if tag == "enum":
        cls = _resolve(value["m"], value["q"])
        return cls(value["v"])
    if tag == "dataclass":
        cls = _resolve(value["m"], value["q"])
        kwargs = {name: decode(encoded) for name, encoded in value["f"].items()}
        return cls(**kwargs)
    if tag == "tuple":
        return tuple(decode(x) for x in value["v"])
    if tag == "frozenset":
        return frozenset(decode(x) for x in value["v"])
    if tag == "list":
        return [decode(x) for x in value["v"]]
    if tag == "dict":
        return {decode(k): decode(v) for k, v in value["v"]}
    raise ValueError(f"persistence.serializers.decode: unknown encoded tag {tag!r}")
