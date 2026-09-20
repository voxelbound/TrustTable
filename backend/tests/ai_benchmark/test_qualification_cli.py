"""CLI tests for the finding-analysis qualification harness (`REL-02`,
`docs/decision-log.md` D-043).

The CLI reads the product's own `Settings` and builds the provider the way the
route does. These tests run it against the `mock` and `disabled` providers and
against the real `llama_cpp` provider over a stub server, never a live model and
never the network. Output discipline is asserted on every stream: progress and
summary carry case ids and aggregate figures only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from trusttable_backend.ai_benchmark.qualification import (
    PRODUCT_AI_CALL_STATUS,
    CaseOutcome,
    build_qualification_suite,
)
from trusttable_backend.ai_benchmark.qualification_cli import (
    EXIT_OK,
    EXIT_USAGE,
    build_parser,
    main,
)
from trusttable_backend.ai_provider.contract import (
    ProviderConnectionError,
    ProviderHealth,
    ProviderRequest,
    ProviderResponse,
)
from trusttable_backend.config import Settings

from .test_qualification_route_fidelity import StubServer, accept, make_factory

DETECTOR_COUNT_FLOOR = 12

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GUIDE = _REPO_ROOT / "docs" / "local-ai-qualification.md"


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_a_mock_provider_run_writes_a_result_and_prints_only_aggregates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "result.json"
    code = main(["--output", str(target)], settings=Settings(llm_provider="mock"))

    assert code == EXIT_OK
    document = read(target)
    assert document["harness"] == "finding_analysis_qualification"
    assert document["provider_name"] == "mock"
    assert document["conditions"] == ["evidence_only", "confirmed_context"]
    cases = document["aggregate"]["case_count"]
    assert cases >= 2 * DETECTOR_COUNT_FLOOR
    # The mock provider fills the structured contract when the request names one, so
    # the product's own validator accepts every case on the first attempt.
    assert document["aggregate"]["outcome_counts"]["accepted_first_attempt"] == cases
    captured = capsys.readouterr()
    assert "fill rate: 100.0%" in captured.out
    assert f"cases: {cases}" in captured.out
    assert "result written to" in captured.out
    assert f"[{cases}/{cases}]" in captured.err  # progress reached the end
    assert "-> accepted_first_attempt" in captured.err


def test_the_conditions_flag_limits_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "result.json"
    code = main(
        ["--output", str(target), "--conditions", "evidence_only"],
        settings=Settings(llm_provider="mock"),
    )

    assert code == EXIT_OK
    document = read(target)
    assert document["conditions"] == ["evidence_only"]
    assert {r["condition"] for r in document["case_results"]} == {"evidence_only"}
    assert set(document["aggregate_by_condition"]) == {"evidence_only"}
    assert f"[{document['aggregate']['case_count']}/" in capsys.readouterr().err


def test_a_disabled_provider_is_refused_because_there_is_no_model_to_qualify(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "result.json"
    code = main(["--output", str(target)], settings=Settings(llm_provider="disabled"))

    assert code == EXIT_USAGE
    assert not target.exists()
    assert "disabled" in capsys.readouterr().err


def test_a_missing_output_directory_is_refused_before_any_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["--output", str(tmp_path / "nope" / "result.json")],
        settings=Settings(llm_provider="mock"),
    )

    assert code == EXIT_USAGE
    assert not (tmp_path / "nope").exists()
    captured = capsys.readouterr()
    assert "output directory" in captured.err
    assert "[1/" not in captured.err  # nothing ran


def test_an_unusable_provider_configuration_prints_only_the_error_class(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(
        llm_provider="llama_cpp",
        llm_base_url="http://user:secret@llama.test:8081",
        llm_model="",  # llama_cpp needs a model identifier
    )
    code = main(["--output", str(tmp_path / "result.json")], settings=settings)

    assert code == EXIT_USAGE
    captured = capsys.readouterr()
    assert "UnknownProviderError" in captured.err
    assert "secret" not in captured.err + captured.out
    assert "llama.test" not in captured.err + captured.out
    assert not (tmp_path / "result.json").exists()


def test_argument_errors_exit_through_argparse(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as no_output:
        main([], settings=Settings(llm_provider="mock"))
    assert no_output.value.code == 2
    with pytest.raises(SystemExit) as bad_scope:
        main(["--output", str(tmp_path / "x.json"), "--scope", "everything"])
    assert bad_scope.value.code == 2


def test_parser_defaults_match_the_documented_run() -> None:
    args = build_parser().parse_args(["--output", "x.json"])
    assert args.scope == "per_detector"
    assert args.conditions == ["evidence_only", "confirmed_context"]
    assert args.runtime_identifier == "llama.cpp"
    assert args.hardware_profile == "baseline"
    assert args.quantization is None
    assert args.peak_rss_mb is None and args.peak_vram_mb is None


def test_a_real_llama_cpp_provider_run_uses_the_routes_arguments_and_leaks_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    created: list[dict[str, Any]] = []
    settings = Settings(
        llm_provider="llama_cpp",
        llm_base_url="http://user:secret@llama.test:8081",
        llm_model=r"C:\models\Qwen3.5-4B-Q4_K_M.gguf",
        llm_timeout_seconds=45,
    )
    target = tmp_path / "result.json"
    code = main(
        [
            "--output",
            str(target),
            "--quantization",
            "Q4_K_M",
            "--hardware-profile",
            "baseline",
            "--notes",
            "cli test",
            "--peak-rss-mb",
            "5120",
        ],
        settings=settings,
        factory=make_factory(StubServer(accept), created),
    )

    assert code == EXIT_OK
    assert created == [
        {
            "name": "llama_cpp",
            "base_url": "http://user:secret@llama.test:8081",
            "model_identifier": r"C:\models\Qwen3.5-4B-Q4_K_M.gguf",
            "timeout_seconds": 45.0,
        }
    ]
    document = read(target)
    assert document["aggregate"]["fill_rate"] == 1.0
    assert document["provider_name"] == "llama_cpp"
    assert document["model_identifier"] == "Qwen3.5-4B-Q4_K_M.gguf"
    assert document["candidate"] == {
        "runtime_identifier": "llama.cpp",
        "model_identifier": "Qwen3.5-4B-Q4_K_M.gguf",
        "quantization_identifier": "Q4_K_M",
        "hardware_profile": "baseline",
    }
    assert document["config"]["configured_timeout_seconds"] == 45.0
    assert document["config"]["notes"] == "cli test"
    assert document["resource_observations"] == {"peak_rss_mb": 5120.0, "peak_vram_mb": None}

    captured = capsys.readouterr()
    for stream in (captured.out, captured.err, target.read_text(encoding="utf-8")):
        lowered = stream.lower()
        for forbidden in ("secret", "llama.test", "c:\\", "models\\"):
            assert forbidden not in lowered, forbidden


class UnreachableProvider:
    """A provider whose server never answers."""

    @property
    def provider_name(self) -> str:
        return "unreachable"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            available=False,
            provider_name="unreachable",
            model_identifier="m.gguf",
            detail="http://secret.example refused",
        )

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderConnectionError("http://secret.example refused")


def test_an_unreachable_server_warns_and_still_records_the_failures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "result.json"
    code = main(
        ["--output", str(target), "--conditions", "evidence_only"],
        settings=Settings(
            llm_provider="llama_cpp", llm_base_url="http://x.test", llm_model="m.gguf"
        ),
        factory=lambda *args, **kwargs: UnreachableProvider(),
    )

    assert code == EXIT_OK
    document = read(target)
    assert document["server_available_at_start"] is False
    assert document["aggregate"]["fallback_rate"] == 1.0
    assert document["aggregate"]["provider_error_kind_counts"] == {
        "ProviderConnectionError": document["aggregate"]["case_count"]
    }
    captured = capsys.readouterr()
    assert "warning" in captured.err
    assert "secret.example" not in captured.out + captured.err + target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The public guide is pinned to real behavior
# ---------------------------------------------------------------------------


def _guide() -> str:
    return _GUIDE.read_text(encoding="utf-8")


def test_the_guide_documents_every_cli_option() -> None:
    guide = _guide()
    parser = build_parser()
    flags = {
        option
        for action in parser._actions  # noqa: SLF001 - reading the real option table
        for option in action.option_strings
        if option.startswith("--") and option != "--help"
    }
    assert flags  # the parser really has options
    for flag in sorted(flags):
        assert f"`{flag}" in guide, f"{flag} is not documented"


def test_the_guides_outcome_table_matches_the_products_status_mapping() -> None:
    guide = _guide()
    for outcome in CaseOutcome:
        row = next(
            (line for line in guide.splitlines() if line.startswith(f"| `{outcome.value}`")),
            None,
        )
        assert row is not None, outcome
        assert f"`{PRODUCT_AI_CALL_STATUS[outcome]}`" in row, outcome


def test_the_guides_documented_defaults_match_the_parser() -> None:
    guide = _guide()
    defaults = build_parser().parse_args(["--output", "x.json"])
    assert f"Default `{defaults.runtime_identifier}`" in guide
    assert f"Default `{defaults.hardware_profile}`" in guide
    assert "(default, 13 cases per condition)" in guide
    assert len(build_qualification_suite().cases) == 13  # the number the guide states


def test_the_guides_relative_links_resolve() -> None:
    for target in re.findall(r"\]\(([^)#]+\.md)(?:#[^)]*)?\)", _guide()):
        assert (_GUIDE.parent / target).is_file(), target


def test_the_guide_states_its_limits_and_carries_no_delivery_provenance() -> None:
    guide = _guide()
    assert "no pass mark" in guide
    assert "does not apply `LLM_TEMPERATURE`" in guide
    assert "never contains model output" in guide.replace("\n", " ")
    for private in ("project-ops", ".eds", "WP-", "eds:", "Claude", "assistant"):
        assert private not in guide, private
