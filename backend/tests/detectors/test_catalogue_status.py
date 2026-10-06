"""Executable catalogue-status check for the Core detector catalogue closure
(`DET-03` closure package 4, `docs/decision-log.md` D-061 finite definition
item 7).

It reads the 41-entry table in `docs/detector-framework.md` section 16 and
compares it with the real registry and with the successor items in
`docs/implementation-backlog.md`. The check is a pure function over text so
that the mutation tests below can prove it fails for each kind of drift: a
dropped row, an unknown detector id, an unknown carrier, and a moved entry
counted as built.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

from trusttable_backend.detectors.catalogue import DETECTORS

REPO_ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK = REPO_ROOT / "docs" / "detector-framework.md"
BACKLOG = REPO_ROOT / "docs" / "implementation-backlog.md"
README = REPO_ROOT / "README.md"

ENTRY_COUNT = 41
EXPECTED_DISPOSITIONS = {
    "BUILT": 20,
    "BUILT BY CLOSURE": 8,
    "MOVED": 11,
    "MOVED PREVIOUSLY": 2,
}
EXPECTED_REGISTERED = 26
EXPECTED_BUILT_ENTRIES = 28
EXPECTED_MOVED_ENTRIES = 13

# Longest first so that "MOVED PREVIOUSLY" is never read as "MOVED".
DISPOSITIONS = ("BUILT BY CLOSURE", "MOVED PREVIOUSLY", "BUILT", "MOVED")
BUILT_DISPOSITIONS = {"BUILT", "BUILT BY CLOSURE"}
MOVED_DISPOSITIONS = {"MOVED", "MOVED PREVIOUSLY"}

_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.*)\|\s*$")
_DETECTOR_ID = re.compile(r"`([a-z_]+\.[a-z_]+)`")
_ITEM_ID = re.compile(r"\b[A-Z]{2,5}-\d{2}\b")
_SECTION_START = "### Closure boundary"
_SECTION_END = "## 17."


class CatalogueRow:
    def __init__(self, number: int, entry: str, disposition: str, carrier: str) -> None:
        self.number = number
        self.entry = entry
        self.disposition = disposition
        self.carrier = carrier


def _disposition_of(cell: str) -> str | None:
    text = cell.strip()
    for name in DISPOSITIONS:
        if text == name or text.startswith(name + " "):
            return name
    return None


def parse_table(framework_text: str) -> tuple[list[CatalogueRow], list[str]]:
    """Return the parsed rows and any structural problems found while parsing."""
    problems: list[str] = []
    start = framework_text.find(_SECTION_START)
    if start < 0:
        return [], ["the 'Closure boundary' section is missing"]
    end = framework_text.find(_SECTION_END, start)
    section = framework_text[start : end if end > 0 else len(framework_text)]
    rows: list[CatalogueRow] = []
    for line in section.splitlines():
        match = _ROW.match(line)
        if match is None:
            continue
        cells = [cell.strip() for cell in match.group(2).split("|")]
        if len(cells) != 3:
            problems.append(f"row {match.group(1)} does not have four columns")
            continue
        disposition = _disposition_of(cells[1])
        if disposition is None:
            problems.append(f"row {match.group(1)} has an invalid disposition {cells[1]!r}")
            continue
        rows.append(CatalogueRow(int(match.group(1)), cells[0], disposition, cells[2]))
    return rows, problems


def backlog_item_ids(backlog_text: str) -> set[str]:
    """Identifiers named in the headings of the implementation backlog."""
    ids: set[str] = set()
    for line in backlog_text.splitlines():
        if line.startswith("## "):
            ids.update(_ITEM_ID.findall(line))
    return ids


def check_catalogue(framework_text: str, backlog_text: str, registered_ids: set[str]) -> list[str]:
    """Return every disagreement between the table, the registry and the backlog."""
    rows, problems = parse_table(framework_text)
    numbers = [row.number for row in rows]
    if sorted(numbers) != list(range(1, ENTRY_COUNT + 1)):
        missing = sorted(set(range(1, ENTRY_COUNT + 1)) - set(numbers))
        duplicated = sorted(n for n, c in Counter(numbers).items() if c > 1)
        problems.append(
            f"entries must be exactly 1..{ENTRY_COUNT} once each "
            f"(missing {missing}, duplicated {duplicated}, found {len(rows)})"
        )

    counts = Counter(row.disposition for row in rows)
    for name, expected in EXPECTED_DISPOSITIONS.items():
        if counts.get(name, 0) != expected:
            problems.append(f"{name} entries: expected {expected}, found {counts.get(name, 0)}")

    items = backlog_item_ids(backlog_text)
    built_ids: set[str] = set()
    for row in rows:
        carried_detectors = set(_DETECTOR_ID.findall(row.carrier))
        carried_items = set(_ITEM_ID.findall(row.carrier))
        if row.disposition in BUILT_DISPOSITIONS:
            if not carried_detectors:
                problems.append(f"entry {row.number} is built but names no detector id")
            for detector_id in carried_detectors:
                if detector_id not in registered_ids:
                    problems.append(
                        f"entry {row.number} names {detector_id}, which is not registered"
                    )
            built_ids.update(carried_detectors & registered_ids)
        else:
            if carried_detectors & registered_ids:
                problems.append(
                    f"entry {row.number} is moved but names a registered detector as built"
                )
            if not carried_items:
                problems.append(f"entry {row.number} is moved but names no successor item")
            for item in carried_items:
                if item not in items:
                    problems.append(
                        f"entry {row.number} names successor {item}, which has no backlog item"
                    )

    for detector_id in sorted(registered_ids - built_ids):
        problems.append(f"registered detector {detector_id} is not mapped to a built entry")

    built_entries = sum(1 for row in rows if row.disposition in BUILT_DISPOSITIONS)
    moved_entries = sum(1 for row in rows if row.disposition in MOVED_DISPOSITIONS)
    if built_entries != EXPECTED_BUILT_ENTRIES:
        problems.append(f"built entries: expected {EXPECTED_BUILT_ENTRIES}, found {built_entries}")
    if moved_entries != EXPECTED_MOVED_ENTRIES:
        problems.append(f"moved entries: expected {EXPECTED_MOVED_ENTRIES}, found {moved_entries}")
    if len(registered_ids) != EXPECTED_REGISTERED:
        problems.append(
            f"registered detectors: expected {EXPECTED_REGISTERED}, found {len(registered_ids)}"
        )
    return problems


def _registered_ids() -> set[str]:
    return {detector.metadata.detector_id for detector in DETECTORS}


def _framework() -> str:
    return FRAMEWORK.read_text(encoding="utf-8")


def _backlog() -> str:
    return BACKLOG.read_text(encoding="utf-8")


def test_the_real_documents_and_registry_agree() -> None:
    assert check_catalogue(_framework(), _backlog(), _registered_ids()) == []


def test_the_registry_has_26_unique_detectors_and_the_table_has_41_rows() -> None:
    ids = [detector.metadata.detector_id for detector in DETECTORS]
    assert len(ids) == len(set(ids)) == EXPECTED_REGISTERED
    rows, problems = parse_table(_framework())
    assert problems == []
    assert [row.number for row in rows] == list(range(1, ENTRY_COUNT + 1))


def test_the_disposition_counts_add_up_to_41() -> None:
    rows, _ = parse_table(_framework())
    counts = Counter(row.disposition for row in rows)
    assert dict(counts) == EXPECTED_DISPOSITIONS
    assert sum(counts.values()) == ENTRY_COUNT
    assert counts["BUILT"] + counts["BUILT BY CLOSURE"] == EXPECTED_BUILT_ENTRIES
    assert counts["MOVED"] + counts["MOVED PREVIOUSLY"] == EXPECTED_MOVED_ENTRIES


def test_entries_40_and_41_are_carried_by_the_existing_detector_not_a_new_one() -> None:
    rows, _ = parse_table(_framework())
    by_number = {row.number: row for row in rows}
    for number in (39, 40, 41):
        assert _DETECTOR_ID.findall(by_number[number].carrier) == [
            "security.possible_llm_prompt_injection"
        ]


def test_every_moved_entry_names_an_existing_successor_item() -> None:
    rows, _ = parse_table(_framework())
    items = backlog_item_ids(_backlog())
    moved = [row for row in rows if row.disposition in MOVED_DISPOSITIONS]
    assert len(moved) == EXPECTED_MOVED_ENTRIES
    for row in moved:
        carried = set(_ITEM_ID.findall(row.carrier))
        assert carried, row.entry
        assert carried <= items, (row.entry, carried - items)


# --- mutation tests: the check must fail for each kind of drift -------------


def _row_line(framework_text: str, number: int) -> str:
    for line in framework_text.splitlines():
        match = _ROW.match(line)
        if match is not None and int(match.group(1)) == number:
            return line
    raise AssertionError(f"row {number} not found")


def test_mutation_dropping_a_row_is_detected() -> None:
    framework = _framework()
    mutated = framework.replace(_row_line(framework, 17) + "\n", "", 1)
    assert mutated != framework
    problems = check_catalogue(mutated, _backlog(), _registered_ids())
    assert any("missing [17]" in problem for problem in problems)


def test_mutation_duplicating_a_row_is_detected() -> None:
    framework = _framework()
    line = _row_line(framework, 17)
    mutated = framework.replace(line, line + "\n" + line, 1)
    problems = check_catalogue(mutated, _backlog(), _registered_ids())
    assert any("duplicated [17]" in problem for problem in problems)


def test_mutation_an_unknown_detector_id_is_detected() -> None:
    framework = _framework()
    line = _row_line(framework, 17)
    mutated = framework.replace(
        line, line.replace("consistency.inconsistent_booleans", "consistency.made_up")
    )
    problems = check_catalogue(mutated, _backlog(), _registered_ids())
    assert any(
        "consistency.made_up" in problem and "not registered" in problem for problem in problems
    )
    assert any(
        "consistency.inconsistent_booleans" in problem and "not mapped" in problem
        for problem in problems
    )


def test_mutation_an_unknown_carrier_is_detected() -> None:
    framework = _framework()
    line = _row_line(framework, 29)
    mutated = framework.replace(line, line.replace("DET-04", "DET-99"))
    problems = check_catalogue(mutated, _backlog(), _registered_ids())
    assert any("DET-99" in problem and "no backlog item" in problem for problem in problems)


def test_mutation_a_moved_entry_counted_as_built_is_detected() -> None:
    framework = _framework()
    line = _row_line(framework, 29)
    mutated = framework.replace(line, line.replace("| MOVED |", "| BUILT |"))
    assert mutated != framework
    problems = check_catalogue(mutated, _backlog(), _registered_ids())
    assert any("entry 29 is built but names no detector id" in problem for problem in problems)
    assert any("BUILT entries: expected 20, found 21" in problem for problem in problems)


def test_mutation_a_built_entry_marked_moved_is_detected() -> None:
    framework = _framework()
    line = _row_line(framework, 2)
    mutated = framework.replace(line, line.replace("| BUILT |", "| MOVED |"))
    assert mutated != framework
    problems = check_catalogue(mutated, _backlog(), _registered_ids())
    assert any(
        "entry 2 is moved but names a registered detector" in problem for problem in problems
    )


def test_mutation_an_invalid_disposition_is_detected() -> None:
    framework = _framework()
    line = _row_line(framework, 5)
    mutated = framework.replace(line, line.replace("| BUILT |", "| DONE |"))
    problems = check_catalogue(mutated, _backlog(), _registered_ids())
    assert any("invalid disposition" in problem for problem in problems)


def test_mutation_an_unregistered_extra_registry_entry_is_detected() -> None:
    problems = check_catalogue(_framework(), _backlog(), _registered_ids() | {"structural.extra"})
    assert any("structural.extra" in problem and "not mapped" in problem for problem in problems)
    assert any("registered detectors: expected 26, found 27" in problem for problem in problems)


def test_mutation_a_missing_successor_item_in_the_backlog_is_detected() -> None:
    backlog = _backlog()
    mutated = backlog.replace("## DET-06 —", "## Removed —")
    assert mutated != backlog
    problems = check_catalogue(_framework(), mutated, _registered_ids())
    assert any("DET-06" in problem and "no backlog item" in problem for problem in problems)


# --- wording: the claim is the exact scope, never a complete catalogue ------

CLOSURE_WORDING = "26 detectors covering 28 of 41 catalogue entries; 13 carried by named successors"
_COMPLETE_CLAIM = re.compile(
    r"(?i)\b(complete|full|whole)\s+(detector\s+)?catalogue\s+"
    r"(is\s+|was\s+|has been\s+)?(built|delivered|implemented|shipped)"
)
_NEGATION = re.compile(r"(?i)\b(never|not|no)\b")


def _normalised(text: str) -> str:
    unquoted = re.sub(r"(?m)^>\s?", "", text)
    return re.sub(r"\s+", " ", unquoted.replace("`", ""))


def _complete_claims(text: str) -> list[str]:
    """Paragraphs that claim a complete catalogue without negating the claim."""
    claims: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        flattened = _normalised(paragraph)
        if _COMPLETE_CLAIM.search(flattened) and not _NEGATION.search(flattened):
            claims.append(flattened[:120])
    return claims


def test_the_framework_states_the_exact_closure_wording() -> None:
    assert CLOSURE_WORDING in _normalised(_framework())


def test_the_backlog_states_the_exact_closure_wording() -> None:
    assert CLOSURE_WORDING in _normalised(_backlog())


@pytest.mark.parametrize(
    "path", [FRAMEWORK, BACKLOG, README, REPO_ROOT / "docs" / "release-plan.md"]
)
def test_no_document_claims_a_complete_catalogue_was_built(path: Path) -> None:
    assert _complete_claims(path.read_text(encoding="utf-8")) == []


def test_the_wording_guard_catches_a_positive_complete_catalogue_claim() -> None:
    assert _complete_claims("The complete detector catalogue is built.")
    assert _complete_claims("The full catalogue delivered in v1.0.")
    assert not _complete_claims('Never write "complete catalogue built" here.')
