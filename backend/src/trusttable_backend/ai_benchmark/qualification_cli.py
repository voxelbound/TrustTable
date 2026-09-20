"""Command-line entry point for the finding-analysis qualification harness
(`REL-02`, `docs/decision-log.md` D-043).

    uv run python -m trusttable_backend.ai_benchmark.qualification_cli \\
        --output qualification-run.json --quantization Q4_K_M

It reads the same `LLM_*` configuration the product reads (`config.Settings`:
environment variables and an optional repository-root `.env`) and builds the
provider exactly the way the explanation route does
(`provider_from_settings`), so a run measures the user's own configuration.

The retry bound is the product's own and is not a flag. The model is never
started, selected or tuned here; a real run is a separate, deliberate step
(`docs/local-ai-qualification.md`). CI never runs a live model: the tests
exercise this module against the `mock` and `disabled` providers only.

Output discipline: progress lines carry only a case id, the condition, the
outcome and a duration; the summary carries only aggregate figures. Model
output, exception text, the server URL and dataset values are never printed or
written.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from ..ai_provider.contract import AIProvider
from ..ai_provider.factory import create_provider
from ..config import Settings
from .persistence import CandidateMetadata, ResourceObservations
from .qualification import (
    CaseResult,
    CaseScope,
    Condition,
    QualificationAggregate,
    QualificationConfig,
    build_qualification_suite,
    run_qualification,
)
from .qualification_persistence import save_qualification_report

EXIT_OK = 0
EXIT_USAGE = 2


def provider_from_settings(
    settings: Settings, *, factory: Callable[..., AIProvider] = create_provider
) -> AIProvider:
    """Build the provider with exactly the arguments the explanation route
    passes to `create_provider` (provider, base URL, model, timeout).

    The route does not pass `LLM_TEMPERATURE` or a token bound to the factory,
    so neither does this: the harness measures what the product does, not what
    its settings imply (see `FUP-014`).
    """
    return factory(
        settings.llm_provider,
        base_url=settings.llm_base_url,
        model_identifier=settings.llm_model,
        timeout_seconds=float(settings.llm_timeout_seconds),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trusttable_backend.ai_benchmark.qualification_cli",
        description=(
            "Measure how the configured local model behaves on the product's own "
            "finding-analysis path, and write a comparable JSON result."
        ),
    )
    parser.add_argument("--output", required=True, help="path of the JSON result to write")
    parser.add_argument(
        "--scope",
        choices=[scope.value for scope in CaseScope],
        default=CaseScope.PER_DETECTOR.value,
        help="one finding per detector (default) or every finding",
    )
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=[condition.value for condition in Condition],
        default=[condition.value for condition in Condition],
        help="which context conditions to run (default: both)",
    )
    parser.add_argument("--runtime-identifier", default="llama.cpp")
    parser.add_argument("--quantization", default=None)
    parser.add_argument("--hardware-profile", default="baseline")
    parser.add_argument("--notes", default="")
    parser.add_argument("--peak-rss-mb", type=float, default=None)
    parser.add_argument("--peak-vram-mb", type=float, default=None)
    return parser


def _format_summary(aggregate: QualificationAggregate) -> list[str]:
    latency = aggregate.case_latency
    return [
        f"cases: {aggregate.case_count}",
        f"fill rate: {aggregate.fill_rate:.1%} "
        f"(first attempt {aggregate.first_attempt_fill_rate:.1%}); "
        f"fell back to built-in guidance: {aggregate.fallback_rate:.1%}",
        "outcomes: "
        + ", ".join(f"{name}={count}" for name, count in aggregate.outcome_counts.items()),
        f"case latency ms: mean {latency.mean_ms:.0f}, p50 {latency.p50_ms:.0f}, "
        f"p95 {latency.p95_ms:.0f}, max {latency.max_ms:.0f}",
        f"slowest completed attempt ms: {aggregate.slowest_completed_attempt_ms:.0f}",
    ]


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    factory: Callable[..., AIProvider] = create_provider,
) -> int:
    args = build_parser().parse_args(argv)
    output = Path(args.output)
    if not output.parent.is_dir():
        print("error: the output directory does not exist", file=sys.stderr)
        return EXIT_USAGE

    resolved = settings if settings is not None else Settings()
    if resolved.llm_provider == "disabled":
        print(
            "error: LLM_PROVIDER is 'disabled', so there is no model to qualify",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        provider = provider_from_settings(resolved, factory=factory)
    except Exception as exc:  # the message can name configuration; print the class only
        print(
            f"error: the provider configuration is unusable ({type(exc).__name__})",
            file=sys.stderr,
        )
        return EXIT_USAGE

    conditions = tuple(Condition(name) for name in dict.fromkeys(args.conditions))
    suite = build_qualification_suite(CaseScope(args.scope))
    total = len(suite.cases) * len(conditions)
    done = 0

    def progress(result: CaseResult) -> None:
        nonlocal done
        done += 1
        seconds = result.total_duration_ms / 1000
        print(
            f"[{done}/{total}] {result.case_id} {result.condition.value} -> "
            f"{result.outcome.value} ({seconds:.1f}s)",
            file=sys.stderr,
        )

    if not provider.health_check().available:
        print(
            "warning: the model server did not answer its health check; "
            "provider errors will be recorded",
            file=sys.stderr,
        )
    report = run_qualification(
        provider,
        suite,
        config=QualificationConfig(
            conditions=conditions,
            configured_timeout_seconds=float(resolved.llm_timeout_seconds),
            notes=args.notes,
        ),
        on_case_complete=progress,
    )
    save_qualification_report(
        report,
        output,
        candidate=CandidateMetadata(
            runtime_identifier=args.runtime_identifier,
            model_identifier=resolved.llm_model or "unknown",
            quantization_identifier=args.quantization,
            hardware_profile=args.hardware_profile,
        ),
        resource_observations=(
            ResourceObservations(peak_rss_mb=args.peak_rss_mb, peak_vram_mb=args.peak_vram_mb)
            if args.peak_rss_mb is not None or args.peak_vram_mb is not None
            else None
        ),
    )
    for line in _format_summary(report.aggregate):
        print(line)
    print(f"result written to: {output}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
