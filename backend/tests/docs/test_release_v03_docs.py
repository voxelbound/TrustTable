"""Pin what the documentation says about the `v0.3` release status (`REL-03`).

The repository is prepared for `v0.3.0` (version, acceptance test), but the tag
has not been pushed, no image is published and no clean host has installed it.
These tests keep the docs from over-claiming that, and keep the version the
release workflow checks equal to the version the docs describe. They do not
prove a release exists; they prove the docs do not say one does.

When `v0.3.0` is actually published and verified, these pins are rewritten
one-for-one with the release-closeout package, as `test_linux_installation_docs`
was for `v0.2.0`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from trusttable_backend.main import create_app

_ROOT = Path(__file__).resolve().parents[3]


def _text(relative: str) -> str:
    return (_ROOT / relative).read_text(encoding="utf-8")


def _flat(relative: str) -> str:
    """The file on one line, with wrapping and blockquote markers removed."""
    lines = (line.removeprefix(">").strip() for line in _text(relative).splitlines())
    return " ".join(line for line in lines if line)


def test_backend_version_is_the_v03_release_version() -> None:
    project = tomllib.loads(_text("backend/pyproject.toml"))["project"]
    assert project["version"] == "0.3.0"
    lock = _text("backend/uv.lock")
    assert 'name = "trusttable-backend"\nversion = "0.3.0"' in lock


def test_the_running_application_reports_the_v03_release_version() -> None:
    with TestClient(create_app()) as client:
        reported = client.get("/api/v1/version").json()["application_version"]
    assert reported == "0.3.0"


def test_release_images_doc_says_v03_is_not_published_and_v02_is_latest() -> None:
    doc = _flat("docs/release-images.md")
    assert "`v0.3.0` is prepared in the repository but not published" in doc
    assert "no `0.3.0` image exists on GHCR" in doc
    assert "no clean-host install has been run for it" in doc
    assert "`v0.2.0` is the latest published and verified release" in doc


def test_readme_says_v03_is_a_release_candidate_not_a_release() -> None:
    readme = _flat("README.md")
    assert "`v0.3.0` is **not yet published**" in readme
    assert "no tag has been pushed" in readme
    assert "no images are on GHCR" in readme
    assert "no clean-host install has been run for it" in readme
    assert "The latest published and verified release remains `v0.2.0`" in readme
    # The published-and-verified wording belongs to v0.2.0 only.
    assert "released as `v0.3.0`" not in readme
    assert "published `v0.3.0` images" not in readme
    assert "verified on a clean Linux host for `v0.3.0`" not in readme


def test_planning_docs_keep_rel_03_open_until_the_release_is_published() -> None:
    backlog = _flat("docs/implementation-backlog.md")
    plan = _flat("docs/release-plan.md")
    assert "so `REL-03` stays open" in backlog
    assert "not published or verified on a clean host" in plan
    assert "`REL-03` is complete" not in backlog


def test_the_workflow_acceptance_test_named_in_the_docs_exists() -> None:
    backlog = _text("docs/implementation-backlog.md")
    assert "backend/tests/api/test_v03_complete_workflow.py" in backlog
    assert (_ROOT / "backend/tests/api/test_v03_complete_workflow.py").is_file()
