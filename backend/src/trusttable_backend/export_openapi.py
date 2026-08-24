"""Export the application's OpenAPI schema as JSON (FND-05).

A thin, network-free wrapper around `create_app().openapi()`: no live
server, no Docker, no database. `create_app()` already runs standalone
(every `Settings` field has a default — see `config.py`), so this module
needs no special environment to run.

Used by `frontend/package.json`'s `generate:api-types` script (piped into
`openapi-typescript`) and by the CI `contract` job's drift check.

Usage:
    python -m trusttable_backend.export_openapi [output_path]

With no argument, the schema JSON is written to stdout. With an argument,
it is written to that path instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from trusttable_backend.main import create_app


def get_openapi_schema() -> dict[str, object]:
    """Return the application's OpenAPI schema as a plain dict."""
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
