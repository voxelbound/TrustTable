"""Opt-in gate for the v0.1 performance-baseline tests (PERF-01, scoped, WP-031).

Performance benchmarks are a release-candidate CI gate, not a
pull-request gate (`docs/testing-strategy.md` §8), so these tests are
skipped by default and only run when `--run-performance` is passed
explicitly. A CLI flag is used rather than an environment variable
because `eds-broker exec` only forwards a fixed environment allowlist
(`NODE_ENV`, `PYTHONPATH`, `CI`) to registered operations — a flag in
the operation's own `argv` has no such dependency.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-performance",
        action="store_true",
        default=False,
        help="Run the opt-in v0.1 performance-baseline tests (WP-031).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-performance"):
        return
    skip_performance = pytest.mark.skip(
        reason=(
            "Performance benchmarks are a release-candidate gate, not a pull-request "
            "gate (docs/testing-strategy.md §8). Opt in with --run-performance."
        )
    )
    for item in items:
        if "/performance/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip_performance)
