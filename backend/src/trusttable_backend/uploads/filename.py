"""Filename sanitization for generic file uploads (`WP-029`).

Defends against path-traversal and control-character injection in a
client-supplied filename (`docs/security-threat-model.md` §3.6: "sanitized
filenames"). This module never touches the filesystem and never trusts the
client-supplied name for any storage decision — callers must always
generate their own opaque storage name (`docs/security-threat-model.md`
§3.6: "generated storage names") and use this module's output only for
safe, informational display (e.g. `Dataset.original_filename`).

Framework-independent: no FastAPI/pydantic import. Stdlib only
(`re`, `pathlib`). No `eval`/`exec` anywhere in this module.
"""

from __future__ import annotations

import re
from pathlib import PureWindowsPath

#: Fixed fallback used whenever sanitization would otherwise produce an
#: empty name (missing filename, path-only input, or a name consisting
#: entirely of stripped characters). Never derived from client input.
FALLBACK_FILENAME = "uploaded_file"

#: Reasonable, generous display-length bound. Not a security control by
#: itself (the generated storage name is authoritative for storage), just
#: keeps the sanitized display value bounded.
_MAX_LENGTH = 255

#: ASCII control characters (0x00-0x1F) and DEL (0x7F).
_CONTROL_CHARS: re.Pattern[str] = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_filename(raw: str | None) -> str:
    """Return a safe, display-only filename derived from client-supplied
    `raw`.

    Strips any path component regardless of separator style (posix `/`
    or Windows `\\`, including a Windows drive letter or UNC-style
    prefix), removes ASCII control characters, trims surrounding
    whitespace and trailing dots (both meaningful on Windows), and bounds
    the result's length. Falls back to `FALLBACK_FILENAME` when `raw` is
    `None`, empty, or reduces to nothing after sanitization.

    This function does not validate extension or content-type — callers
    perform that check separately against the *original* client-supplied
    name before sanitization changes anything meaningful about it (an
    extension is preserved by this function in the ordinary case).
    """
    if not raw:
        return FALLBACK_FILENAME

    # `PureWindowsPath.name` strips both `/`- and `\`-style path
    # components, a drive letter (`C:\...`), and a UNC prefix
    # (`\\server\share\...`) in one pass, since Windows path parsing is a
    # strict superset of posix path parsing for this purpose (a posix
    # path with `/` separators is also valid input to `PureWindowsPath`).
    name = PureWindowsPath(raw).name

    name = _CONTROL_CHARS.sub("", name)
    name = name.strip()
    name = name.strip(". ")

    if not name:
        return FALLBACK_FILENAME

    if len(name) > _MAX_LENGTH:
        name = name[:_MAX_LENGTH]
        # Re-trim in case truncation landed on a trailing dot/space.
        name = name.strip(". ")
        if not name:
            return FALLBACK_FILENAME

    return name
