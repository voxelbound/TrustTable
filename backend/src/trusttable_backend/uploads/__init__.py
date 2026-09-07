"""Generic file-upload support (`UI-01`/`API-01` extending, `WP-029`).

Currently exposes only filename sanitization. Framework-independent:
no FastAPI/pydantic import.
"""

from __future__ import annotations

from .filename import sanitize_filename

__all__ = ["sanitize_filename"]
