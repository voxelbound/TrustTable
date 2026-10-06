"""Pin what the documentation says about the `v0.3` release status (`REL-03`).

`v0.3.0` is published and was verified on a clean host with AI off (`D-049`).
These tests keep the docs from over-claiming beyond that (local-AI setup,
scanning, signing and SBOM stay stated as not covered), and keep the version the
release workflow checks equal to the version the docs describe. They do not
prove a release exists; they prove the docs say what was reported and no more.
"""

from __future__ import annotations

import re
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


def test_release_images_doc_says_v03_is_published_and_states_its_limits() -> None:
    doc = _flat("docs/release-images.md")
    assert "Status: published and verified for `v0.3.0`" in doc
    assert "5053249adacca3c46276daa91f8ea1ff0ccc945d" in doc
    assert "`v0.3.0` is the latest published and verified release" in doc
    # What the clean-host check did not cover stays stated.
    assert "The image publication itself was not independently read back" in doc
    assert "the local-AI setup" in doc
    assert "unsigned, carry no provenance or SBOM attestation" in doc
    assert "prepared in the repository but not published" not in doc


def test_readme_says_v03_is_published_with_its_verification_limits() -> None:
    readme = _flat("README.md")
    assert "**`v0.3.0` is published**" in readme
    assert "pull, start and health check with AI off" in readme
    assert "unsigned, unattested and not container-scanned" in readme
    assert "the local-AI setup was not exercised on that host" in readme
    assert "not yet published" not in readme
    assert "no tag has been pushed" not in readme
    # The owner has recorded the v0.2 and v0.3 milestones complete (at the
    # agreed scoped qualification level), and v1.0 is the active milestone.
    # The README states that and no longer calls the decision pending or
    # v0.3 the current milestone.
    assert "**v0.2 — Local AI beta: complete, released as `v0.2.0`.**" in readme
    assert "**v0.3 — Complete manager workflow: complete, released as `v0.3.0`.**" in readme
    assert "**Current milestone: v1.0 — Production-quality local release (active).**" in readme
    assert "recorded the milestone complete at the agreed scoped qualification level" in readme
    assert (
        "recording the `v0.3` milestone as complete is the repository owner's decision"
        not in readme
    )
    assert "Current milestone: v0.3" not in readme
    assert "(v0.3 — begun)" not in readme
    assert "(v0.2 — begun)" not in readme


def test_planning_docs_record_rel_03_complete_with_the_ai_off_narrowing() -> None:
    backlog = _flat("docs/implementation-backlog.md")
    plan = _flat("docs/release-plan.md")
    log = _flat("docs/decision-log.md")
    assert "`REL-03` is complete" in backlog
    assert "the local-AI setup was not exercised" in backlog
    assert "so `REL-03` stays open" not in backlog
    assert "`REL-03` is complete" in plan
    assert "not published or verified on a clean host" not in plan
    assert "D-049 — `REL-03` is complete" in log
    assert "Whether the `v0.3` milestone is complete is the owner's decision" in log


def test_docs_say_the_configured_limits_are_consumed_and_ing_03_is_complete() -> None:
    readme = _flat("README.md")
    configuration = _flat("docs/configuration.md")
    backlog = _flat("docs/implementation-backlog.md")
    plan = _flat("docs/release-plan.md")
    log = _flat("docs/decision-log.md")
    assert "**Done — secure Excel support (`ING-03`):**" in readme
    assert "are read from the settings on every CSV and Excel parse" in readme
    assert "are not read by the parsers" not in readme
    assert "so changing those settings has no effect" not in readme
    assert "Not yet consumed:" not in configuration.split("## LLM provider")[0].split(
        "## Local limits"
    )[1].replace("**", "")
    assert "These limits are read from the settings on every parse" in configuration
    assert "the item is complete" in backlog
    assert "`ING-03` is complete" in plan
    assert "D-053 — `ING-03` is complete" in log
    # The deterministic parse-limit factory the docs name exists.
    assert (_ROOT / "backend/src/trusttable_backend/analysis/parse_limits.py").is_file()


def test_no_readme_line_contradicts_the_completed_ing_03_or_the_closed_det_03() -> None:
    """Every README mention is checked, not only the status block: a stale
    "ING-03 (in progress)" in the delivered-work list contradicted the status
    block after `ING-03` completed. `DET-03` is closed only as the Core detector
    catalogue (closure package 4, D-065): the README never says it is complete,
    and never says the full catalogue is built."""
    lines = _text("README.md").splitlines()
    for line in lines:
        if "ING-03" in line:
            assert "in progress" not in line.lower(), line
            assert "not complete" not in line.lower(), line
        if "DET-03" in line:
            assert "DET-03` is complete" not in line and "DET-03 (complete)" not in line, line
    readme = _flat("README.md")
    assert "**ING-03 (complete)**" in readme
    assert "**DET-03 (closed as the Core detector catalogue)**" in readme
    assert "**DET-03 (in progress)**" not in readme
    assert "**Done — Core detector catalogue (`DET-03`" in readme
    assert (
        "26 detectors covering 28 of 41 catalogue entries; 13 carried by named successors" in readme
    )
    assert "the full catalogue is not built" in readme
    assert "What the 26 detectors are" in readme
    assert "bringing it to 17" in readme
    assert "bringing it to 19" in readme
    assert "bringing it to 20" in readme
    assert "bringing it to 23" in readme
    assert "bringing it to 26" in readme
    assert "data observations" in readme
    assert "closure target is amended from 27 to 26" in readme
    assert "stays 26" in readme
    assert "never changes the trust assessment" in readme
    assert "Zero-padded codes and phone numbers are never reported" in readme
    assert "never an address" in readme
    assert "never an email value" in readme


def test_det_03_security_subtype_decision_is_recorded_consistently() -> None:
    """D-064 (closure package 3): entries 40 and 41 are evidence subtypes of the
    existing detector, there is no second detector, and the closure count reads 26."""
    log = _flat("docs/decision-log.md")
    assert "## D-064" in log
    assert "SD-989e7edf3d5a" in log
    # The exception (owner decision SD-0cc2de8a9889, option A) is stated, not hidden.
    assert "SD-0cc2de8a9889" in log
    assert "Newly recognised phrasings count wherever they appear" in log
    assert "every value version 1 matched" not in log
    framework = _flat("docs/detector-framework.md")
    assert "Documented exception (owner decision SD-0cc2de8a9889, option A)" in framework
    assert "every value version 1 matched" not in framework
    assert "already flagged column can rise in severity" in _flat(
        "docs/implementation-backlog.md"
    ) or ("can rise in severity" in _flat("docs/implementation-backlog.md"))
    assert "can now rise in severity" in _flat("README.md")
    for term in ("exfiltration_instruction", "secret_request", "prompt_injection"):
        assert term in framework, term
    assert "26 registered detectors covering 28 of the 41" in framework
    table = re.findall(r"\| (?:40|41) \|[^|]+\|[^|]+\|[^|]+\|", framework)
    assert len(table) == 2
    for row in table:
        assert "security.possible_llm_prompt_injection" in row
        assert "possible_exfiltration_or_secret_request" not in row
    backlog = _flat("docs/implementation-backlog.md")
    assert "no detector added, 26 registered (D-064)" in backlog


def test_the_workflow_acceptance_test_named_in_the_docs_exists() -> None:
    backlog = _text("docs/implementation-backlog.md")
    assert "backend/tests/api/test_v03_complete_workflow.py" in backlog
    assert (_ROOT / "backend/tests/api/test_v03_complete_workflow.py").is_file()
