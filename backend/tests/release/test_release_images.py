"""Structural and behavioral tests for the release-image path (`REL-02`).

`docker-compose.release.yml` is the pull-only twin of `docker-compose.yml`, and
`.github/workflows/release-images.yml` builds the images it pulls. Neither has
run against a real registry, so these tests pin the properties that make the
path safe and reproducible before anything is published:

* the pull-only file cannot build, requires an explicit version, and is
  otherwise identical to the source-build file;
* the workflow publishes only for a version tag, holds package-write
  permission only in the publish job, never interpolates a ref name into a
  shell, never creates a floating tag, and verifies the published result
  without registry credentials;
* the tag/version check script does what it says (it is executed here).

They cannot prove a publish works; that first happens at the human-authorized
publish step. `tests/integration/test_docker_compose_release_file.py` proves the
pull-only file starts a real stack from locally built images.
"""

from __future__ import annotations

import copy
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

# PyYAML is guaranteed by the declared `uvicorn[standard]` dependency and ships
# no type stubs; this is test-only use.
import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_COMPOSE = REPO_ROOT / "docker-compose.yml"
RELEASE_COMPOSE = REPO_ROOT / "docker-compose.release.yml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-images.yml"

EXPECTED_IMAGES = {
    "backend": "ghcr.io/voxelbound/trusttable-backend",
    "frontend": "ghcr.io/voxelbound/trusttable-frontend",
}
VERSION_VARIABLE = "TRUSTTABLE_VERSION"


def load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def services(path: Path) -> dict[str, dict[str, Any]]:
    return load(path)["services"]  # type: ignore[no-any-return]


def runtime_fields(service: dict[str, Any]) -> dict[str, Any]:
    """Everything about a service except where its image comes from."""
    return {key: value for key, value in service.items() if key not in {"image", "build"}}


def differing_services(
    source: dict[str, dict[str, Any]], release: dict[str, dict[str, Any]]
) -> list[str]:
    """Names whose runtime fields differ (or that exist on only one side)."""
    names = sorted(set(source) | set(release))
    return [
        name
        for name in names
        if name not in source
        or name not in release
        or runtime_fields(source[name]) != runtime_fields(release[name])
    ]


def workflow() -> dict[str, Any]:
    return load(WORKFLOW)


def triggers(document: dict[str, Any]) -> dict[str, Any]:
    # PyYAML follows YAML 1.1, where the bare key `on` parses as boolean True.
    key: Any = "on" if "on" in document else True
    trigger = document[key]
    assert isinstance(trigger, dict)
    return trigger


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job["steps"]  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# The pull-only Compose file
# ---------------------------------------------------------------------------


def test_the_pull_only_file_defines_the_same_services_as_the_source_build_file() -> None:
    assert set(services(RELEASE_COMPOSE)) == set(services(SOURCE_COMPOSE)) == set(EXPECTED_IMAGES)


def test_the_pull_only_file_cannot_build_anything() -> None:
    for name, service in services(RELEASE_COMPOSE).items():
        assert "build" not in service, name
    # The source-build file is the one that builds (guards against swapped files).
    assert all("build" in service for service in services(SOURCE_COMPOSE).values())


@pytest.mark.parametrize("name", sorted(EXPECTED_IMAGES))
def test_each_pull_only_image_is_the_published_name_with_a_required_version(name: str) -> None:
    image = services(RELEASE_COMPOSE)[name]["image"]
    match = re.fullmatch(
        rf"{re.escape(EXPECTED_IMAGES[name])}:\$\{{{VERSION_VARIABLE}:\?([^}}]+)\}}", image
    )
    assert match, image
    assert match.group(1).strip(), "the required-variable message must say what to set"
    # `:?` means unset/empty is an error. A default (`:-` / `-` / `:+`) would allow an
    # unpinned or floating install and is forbidden.
    assert ":-" not in image and f"{VERSION_VARIABLE}-" not in image
    assert "latest" not in image


def test_the_pull_only_file_matches_the_source_build_file_apart_from_the_image() -> None:
    assert differing_services(services(SOURCE_COMPOSE), services(RELEASE_COMPOSE)) == []


@pytest.mark.parametrize(
    "field", ["ports", "restart", "extra_hosts", "env_file", "healthcheck", "depends_on"]
)
def test_the_parity_check_would_catch_drift_in_each_runtime_field(field: str) -> None:
    """A parity test that cannot fail proves nothing: mutate each field and see it caught."""
    source = services(SOURCE_COMPOSE)
    release = copy.deepcopy(services(RELEASE_COMPOSE))
    holder = next(name for name, service in release.items() if field in service)
    release[holder][field] = "drifted"
    assert differing_services(source, release) == [holder]


def test_the_parity_check_catches_a_service_missing_from_one_side() -> None:
    release = copy.deepcopy(services(RELEASE_COMPOSE))
    del release["frontend"]
    assert differing_services(services(SOURCE_COMPOSE), release) == ["frontend"]


def test_the_pull_only_file_keeps_the_documented_runtime_contract() -> None:
    release = services(RELEASE_COMPOSE)
    assert release["backend"]["ports"] == ["8000:8000"]
    assert release["frontend"]["ports"] == ["8080:8080"]
    assert release["backend"]["restart"] == release["frontend"]["restart"] == "unless-stopped"
    assert release["backend"]["extra_hosts"] == ["host.docker.internal:host-gateway"]
    assert release["frontend"]["depends_on"] == {"backend": {"condition": "service_healthy"}}


# ---------------------------------------------------------------------------
# The release workflow: triggers, permissions, publish gating
# ---------------------------------------------------------------------------


def test_the_workflow_runs_only_for_version_tags_and_manual_dispatch() -> None:
    trigger = triggers(workflow())
    assert set(trigger) == {"push", "workflow_dispatch"}
    assert trigger["push"] == {"tags": ["v*.*.*"]}  # in particular: no `branches`
    assert "pull_request" not in trigger and "pull_request_target" not in trigger


def test_only_the_publish_job_can_write_packages() -> None:
    document = workflow()
    assert document["permissions"] == {"contents": "read"}
    jobs = document["jobs"]
    writers = {
        name
        for name, job in jobs.items()
        if isinstance(job.get("permissions"), dict)
        and job["permissions"].get("packages") == "write"
    }
    assert writers == {"images"}
    # Nothing beyond contents:read and (for the publish job) packages:write is ever requested.
    granted = {name: job["permissions"] for name, job in jobs.items() if "permissions" in job}
    assert granted["images"] == {"contents": "read", "packages": "write"}
    assert granted["verify-anonymous-pull"] == {"contents": "read"}
    assert "check-version" not in granted  # inherits the workflow's read-only default


def test_nothing_is_pushed_unless_the_ref_is_a_tag() -> None:
    images = workflow()["jobs"]["images"]
    build = next(s for s in steps(images) if str(s.get("uses", "")).startswith("docker/build-push"))
    assert build["with"]["push"] == "${{ github.ref_type == 'tag' }}"
    login = next(s for s in steps(images) if str(s.get("uses", "")).startswith("docker/login"))
    assert login["if"] == "github.ref_type == 'tag'"
    # No other step in the publish job can push (e.g. a hand-written `docker push`).
    for step in steps(images):
        assert "docker push" not in str(step.get("run", ""))


def test_images_are_amd64_only_with_no_attestations_and_no_floating_tag() -> None:
    images = workflow()["jobs"]["images"]
    build = next(s for s in steps(images) if str(s.get("uses", "")).startswith("docker/build-push"))
    assert build["with"]["platforms"] == "linux/amd64"
    assert build["with"]["provenance"] is False
    assert build["with"]["sbom"] is False
    meta = next(s for s in steps(images) if str(s.get("uses", "")).startswith("docker/metadata"))
    assert "latest=false" in meta["with"]["flavor"]
    tag_lines = [line.strip() for line in meta["with"]["tags"].splitlines() if line.strip()]
    assert tag_lines == ["type=raw,value=${{ needs.check-version.outputs.version }}"]
    # The only mentions of "latest" are the runner label and the flavor that disables it.
    text = (
        WORKFLOW.read_text(encoding="utf-8")
        .replace("ubuntu-latest", "")
        .replace("latest=false", "")
    )
    assert "latest" not in text


def test_the_workflow_builds_the_same_two_images_the_pull_only_file_pulls() -> None:
    document = workflow()
    images = document["jobs"]["images"]
    registry = document["env"]["REGISTRY"]
    meta = next(s for s in steps(images) if str(s.get("uses", "")).startswith("docker/metadata"))
    assert meta["with"]["images"] == "${{ env.REGISTRY }}/trusttable-${{ matrix.image }}"
    built = {f"{registry}/trusttable-{name}" for name in images["strategy"]["matrix"]["image"]}
    pulled = {
        re.sub(r":\$\{.*$", "", service["image"]) for service in services(RELEASE_COMPOSE).values()
    }
    assert built == pulled == set(EXPECTED_IMAGES.values())
    build = next(s for s in steps(images) if str(s.get("uses", "")).startswith("docker/build-push"))
    assert build["with"]["context"] == "./${{ matrix.image }}"
    for name in images["strategy"]["matrix"]["image"]:
        assert (REPO_ROOT / name / "Dockerfile").is_file()


def test_no_shell_command_interpolates_a_github_expression() -> None:
    """Ref names are attacker-influenced; expressions reach scripts only through `env:`."""
    for job_name, job in workflow()["jobs"].items():
        for step in steps(job):
            script = str(step.get("run", ""))
            assert "${{" not in script, (job_name, step.get("name"))


def test_the_ref_name_reaches_the_version_check_only_through_the_environment() -> None:
    check = workflow()["jobs"]["check-version"]
    step = next(s for s in steps(check) if s.get("id") == "version")
    assert step["env"] == {
        "REF_TYPE": "${{ github.ref_type }}",
        "REF_NAME": "${{ github.ref_name }}",
    }


# ---------------------------------------------------------------------------
# The anonymous-pull verification job
# ---------------------------------------------------------------------------


def test_the_verification_job_runs_only_for_tags_after_publishing_and_never_logs_in() -> None:
    verify = workflow()["jobs"]["verify-anonymous-pull"]
    assert verify["if"] == "github.ref_type == 'tag'"
    assert set(verify["needs"]) == {"check-version", "images"}
    for step in steps(verify):
        assert "login" not in str(step.get("uses", "")).lower(), step
        assert "login" not in str(step.get("run", "")).lower(), step
        assert "GITHUB_TOKEN" not in str(step), step
    scripts = "\n".join(str(s.get("run", "")) for s in steps(verify))
    assert "docker-compose.release.yml pull" in scripts
    assert "up -d --wait" in scripts
    assert "docker-compose.release.yml down" in scripts
    assert "/api/v1/version" in scripts and "application_version" in scripts


# ---------------------------------------------------------------------------
# The version check script, executed
# ---------------------------------------------------------------------------


def version_check_script() -> str:
    check = workflow()["jobs"]["check-version"]
    step = next(s for s in steps(check) if s.get("id") == "version")
    return str(step["run"])


def run_version_check(
    tmp_path: Path, *, ref_type: str, ref_name: str, package_version: str = "0.2.0"
) -> tuple[subprocess.CompletedProcess[str], Path]:
    (tmp_path / "backend").mkdir(exist_ok=True)
    (tmp_path / "backend" / "pyproject.toml").write_text(
        f'[project]\nname = "trusttable-backend"\nversion = "{package_version}"\n',
        encoding="utf-8",
    )
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", version_check_script()],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "REF_TYPE": ref_type,
            "REF_NAME": ref_name,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result, output


def test_a_tag_equal_to_the_package_version_is_accepted_and_reported_without_the_v(
    tmp_path: Path,
) -> None:
    result, output = run_version_check(tmp_path, ref_type="tag", ref_name="v0.2.0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_text(encoding="utf-8").strip() == "version=0.2.0"


@pytest.mark.parametrize(
    "ref_name",
    ["v0.2.1", "v0.3.0", "v1.2.0", "v0.2.0-rc.1", "0.2.0", "latest", "v0.2", "vx.y.z", ""],
)
def test_a_tag_that_is_not_exactly_the_package_version_is_rejected(
    tmp_path: Path, ref_name: str
) -> None:
    result, output = run_version_check(tmp_path, ref_type="tag", ref_name=ref_name)
    assert result.returncode != 0
    assert output.read_text(encoding="utf-8") == ""  # nothing is reported as publishable


def test_a_hostile_tag_name_is_never_executed_and_is_rejected(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    hostile = f"v0.2.0$(touch {marker})"
    result, output = run_version_check(tmp_path, ref_type="tag", ref_name=hostile)
    assert result.returncode != 0
    assert not marker.exists()
    assert output.read_text(encoding="utf-8") == ""


def test_a_manual_run_on_a_branch_only_reports_the_package_version(tmp_path: Path) -> None:
    result, output = run_version_check(
        tmp_path, ref_type="branch", ref_name="feat/anything", package_version="0.9.9"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_text(encoding="utf-8").strip() == "version=0.9.9"


def test_the_repository_never_pushes_by_default_for_a_branch_ref() -> None:
    """A branch run reports a version but `images` still cannot push: the two are independent."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("github.ref_type == 'tag'") >= 3  # login, push, verification job
