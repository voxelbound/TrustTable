"""Export the application's OpenAPI schema as JSON (FND-05).

A thin, network-free wrapper around `create_app().openapi()`: no live
server, no Docker, no external database. `create_app()` (`DB-01`) now
builds a real SQLite engine and runs migrations as part of application
construction, so this module no longer runs on `Settings`' own built-in
default (a container-only `/data` path) — `get_openapi_schema` points
`DATABASE_URL`/`DATA_DIRECTORY` at a private temporary directory first,
only when the caller has not already configured them (a test importing
this module inside `backend/tests/conftest.py`'s own per-test isolated
database already has; the standalone CLI invocation below has not).

Used by `frontend/package.json`'s `generate:api-types` script (piped into
`openapi-typescript`) and by the CI `contract` job's drift check.

Usage:
    python -m trusttable_backend.export_openapi [output_path]

With no argument, the schema JSON is written to stdout. With an argument,
it is written to that path instead.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from trusttable_backend.main import create_app


def get_openapi_schema() -> dict[str, object]:
    """Return the application's OpenAPI schema as a plain dict."""
    with tempfile.TemporaryDirectory(prefix="trusttable-openapi-export-") as tmp_dir:
        os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(tmp_dir) / 'openapi-export.db'}")
        os.environ.setdefault("DATA_DIRECTORY", tmp_dir)
        app = create_app()
        schema = app.openapi()
    return schema


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    schema = get_openapi_schema()
    text = json.dumps(schema, indent=2, sort_keys=True)

    if args:
        output_path = Path(args[0])
        output_path.write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
