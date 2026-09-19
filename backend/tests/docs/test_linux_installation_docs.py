"""Documentation reality tests for the Linux / local-AI installation path
(`AI-08`, `docs/decision-log.md` D-040).

A guide that names a setting, port, endpoint or file that does not exist is
worse than no guide. These tests tie what `docs/installation-linux.md` says to
what the repository actually contains — the real `Settings` fields and
defaults, the real compose file, the real OpenAPI routes and the README's
links — and pin the honest statement of what is *not* yet supported so a later
edit cannot quietly turn a limitation into a claim.

They do not (and cannot) prove the guide works on a fresh Linux host with a
real model; that is an explicit `REL-02` acceptance requirement.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from trusttable_backend.config import Settings
from trusttable_backend.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
README = REPO_ROOT / "README.md"
GUIDE = REPO_ROOT / "docs" / "installation-linux.md"
COMPOSE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
BACKLOG = REPO_ROOT / "docs" / "implementation-backlog.md"
LOCAL_DEV = REPO_ROOT / "docs" / "local-development.md"

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def slug(heading: str) -> str:
    """GitHub-style heading anchor."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def anchors(markdown: str) -> set[str]:
    return {
        slug(match.group(1))
        for match in re.finditer(r"^#{1,6}\s+(.+?)\s*$", markdown, re.MULTILINE)
    }


def relative_links(path: Path) -> list[str]:
    return [
        link
        for link in _LINK_RE.findall(read(path))
        if not link.startswith(("http://", "https://", "mailto:"))
    ]


# ---------------------------------------------------------------------------
# Reachability from the README, and link integrity
# ---------------------------------------------------------------------------


def test_the_guide_exists_and_the_readme_links_to_it_before_the_project_status() -> None:
    readme = read(README)
    assert GUIDE.is_file()
    assert "(docs/installation-linux.md)" in readme
    assert readme.index("docs/installation-linux.md") < readme.index("## Project status")
    assert "## Quick start (Linux)" in readme
    assert readme.index("## Quick start (Linux)") < readme.index("## Project status")


@pytest.mark.parametrize("source", [README, GUIDE], ids=["README", "installation-linux"])
def test_every_relative_link_resolves_to_a_real_file_and_anchor(source: Path) -> None:
    for link in relative_links(source):
        target, _, fragment = link.partition("#")
        resolved = (source.parent / target).resolve() if target else source
        assert resolved.exists(), f"{source.name}: {link} does not resolve"
        if fragment and resolved.suffix == ".md":
            assert fragment in anchors(read(resolved)), f"{source.name}: {link} has no such heading"


def test_the_guide_is_linked_from_the_documentation_map_and_local_development() -> None:
    assert "docs/installation-linux.md" in read(README).split("## Documentation map")[1]
    assert "installation-linux.md" in read(LOCAL_DEV)


def test_public_docs_do_not_reference_private_delivery_paths() -> None:
    for path in (README, GUIDE):
        text = read(path)
        for private in ("project-ops", ".eds"):
            assert private not in text, (path.name, private)
    # The new guide is written for users, not for the delivery history.
    for private in ("WP-0", "FUP-0"):
        assert private not in read(GUIDE), private


# ---------------------------------------------------------------------------
# Every named setting, port, endpoint and file is real
# ---------------------------------------------------------------------------


def test_every_llm_variable_named_in_the_docs_is_a_real_settings_field() -> None:
    fields = {name.upper() for name in Settings.model_fields}
    for path in (GUIDE, ENV_EXAMPLE, REPO_ROOT / "docs" / "configuration.md"):
        named = set(re.findall(r"\bLLM_[A-Z_]+\b", read(path)))
        assert named, path.name
        assert named <= fields, (path.name, sorted(named - fields))


def test_the_env_example_matches_the_real_defaults_it_documents() -> None:
    env = dict(
        line.split("=", 1)
        for line in read(ENV_EXAMPLE).splitlines()
        if "=" in line and not line.startswith("#")
    )
    defaults = Settings()
    assert env["LLM_PROVIDER"] == defaults.llm_provider == "disabled"
    assert env["LLM_BASE_URL"] == defaults.llm_base_url
    assert env["LLM_TIMEOUT_SECONDS"] == str(defaults.llm_timeout_seconds)
    assert {key.lower() for key in env} <= set(Settings.model_fields)


def test_the_guides_default_base_url_and_llama_server_flags_match_the_settings() -> None:
    guide = read(GUIDE)
    defaults = Settings()
    assert f"LLM_BASE_URL={defaults.llm_base_url}" in guide
    assert "--port 8081" in guide and defaults.llm_base_url.endswith(":8081")
    assert f"--ctx-size {defaults.llm_context_window}" in guide
    assert "--no-webui" in guide
    assert "LLM_PROVIDER=llama_cpp" in guide
    assert "llama_cpp" in Settings.model_fields["llm_provider"].annotation.__args__  # type: ignore[union-attr]
    assert "Qwen3.5-4B-Q4_K_M" in guide  # the documented baseline (D-034/D-035)


def test_the_guides_ports_match_the_compose_file() -> None:
    compose = read(COMPOSE)
    guide = read(GUIDE)
    assert '"8000:8000"' in compose and '"8080:8080"' in compose
    assert "http://127.0.0.1:8000" in guide and "http://127.0.0.1:8080" in guide
    assert re.search(r"^  backend:", compose, re.MULTILINE)
    assert "docker compose exec backend" in guide  # a service that really exists


def test_the_compose_backend_maps_host_docker_internal_to_the_host_gateway() -> None:
    compose = read(COMPOSE)
    backend = compose.split("\n  backend:", 1)[1].split("\n  frontend:", 1)[0]
    assert "extra_hosts:" in backend
    assert '"host.docker.internal:host-gateway"' in backend
    # The documented default only resolves on Linux because of that mapping.
    assert "host.docker.internal" in Settings().llm_base_url


def test_every_api_path_in_the_guide_is_a_real_route() -> None:
    templates = list(create_app().openapi()["paths"])
    patterns = [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", t) + "$") for t in templates]
    seen = 0
    for raw in re.findall(r"(/api/v1/[A-Za-z0-9_/<>.\-]+)", read(GUIDE)):
        path = re.sub(r"<[^>]+>", "x", raw).rstrip("/")
        seen += 1
        assert any(p.match(path) for p in patterns), f"{raw} is not a route"
    assert seen >= 4


def test_the_guide_covers_every_required_topic() -> None:
    guide = read(GUIDE).lower()
    for topic in (
        "quick start",  # 1. Linux quick start
        "without any ai",  # 2. running without AI
        "llama-server",  # 3. llama.cpp / llama-server provider
        "gguf",  # 4. where the model is provisioned
        "no hugging face access at runtime",
        "docker compose versus native",  # 6. Docker/Compose versus native
        "troubleshooting",  # 7. troubleshooting / verification
        "health/ready",
        "model connectivity",
    ):
        assert topic in guide, topic


# ---------------------------------------------------------------------------
# The restricted-network limitation is stated, and is a REL-02 requirement
# ---------------------------------------------------------------------------


def test_the_guide_states_the_current_ghcr_only_limitation_exactly() -> None:
    guide = read(GUIDE)
    section = guide.split("## Restricted-network installs", 1)[1]
    for phrase in (
        "not supported yet",
        "builds both images from source",
        "PyPI",
        "npm",
        "GHCR",
        "No TrustTable images are published",
    ):
        assert phrase in section, phrase
    assert "REL-02" in section


def test_the_readme_repeats_the_limitation_beside_the_quick_start() -> None:
    quick_start = (
        read(README).split("## Quick start (Linux)", 1)[1].split("## Project status", 1)[0]
    )
    assert "not supported yet" in quick_start
    assert "GitHub-and-GHCR-only" in quick_start


def test_the_backlog_orders_ai_08_between_eval_ai_01_and_rel_02_with_linux_requirements() -> None:
    backlog = read(BACKLOG)
    eval_at = backlog.index("## EVAL-AI-01")
    ai08_at = backlog.index("## AI-08 — Grounded AI analysis")
    rel02_at = backlog.index("## REL-02 — v0.2 package")
    assert eval_at < ai08_at < rel02_at
    # AI-08 is immediately followed by REL-02: nothing else advanced.
    between = backlog[ai08_at:rel02_at]
    assert "## " not in between.split("\n", 1)[1]
    rel02 = backlog[rel02_at:].split("\n# ", 1)[0]
    for requirement in (
        "GHCR",
        "pull-only",
        "fresh Linux host",
        "offline",
        "no Hugging Face access at runtime",
        "PyPI/npm",
    ):
        assert requirement in rel02, requirement
    # It does not claim the deferred v0.3 items.
    assert "Does **not** deliver `REM-01`" in backlog[ai08_at:rel02_at]


# ---------------------------------------------------------------------------
# Stale statements that would now be false
# ---------------------------------------------------------------------------


def test_no_public_doc_still_says_the_ai_surfaces_are_unavailable() -> None:
    local_dev = read(LOCAL_DEV)
    assert "No product route or analysis feature calls it yet" not in local_dev
    assert "v0.1 has no AI path at all" not in local_dev
    readme = read(README)
    assert "no real LLM provider is wired in yet" not in readme
    ui_spec = read(REPO_ROOT / "docs" / "ui-specification.md")
    assert "Not yet available — business-impact" not in ui_spec
