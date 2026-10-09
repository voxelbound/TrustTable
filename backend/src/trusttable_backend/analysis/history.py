"""The "analysed before" notice (`UX-03`, `docs/decision-log.md` D-069).

A lookup, not an identity. Given the bytes of a file about to be analysed it
answers one question over the analyses that exist *now*: has this exact file
(or a file with this name) been analysed before? Nothing is remembered outside
the analysis rows themselves, so deleting an analysis removes it from every
answer, and no durable dataset identity is created. Only `COMPLETED` analyses
count, because a failed or cancelled run analysed nothing.

Framework-independent: no FastAPI or SQLAlchemy import.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .service import AnalysisState, AnalysisStoreProtocol, AnalysisSummary

#: The most analyses either lookup reads. Both lookups are bounded, so the
#: notice costs the same however many analyses are stored.
LOOKUP_LIMIT = 50

#: The default and the largest page of the recent-analyses list.
DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 50


class PreviousAnalysisKind(StrEnum):
    """Closed set: the same bytes, or only the same file name."""

    SAME_FILE = "same_file"
    SAME_NAME = "same_name"


@dataclass(frozen=True, slots=True)
class PreviousAnalysisNotice:
    """What an earlier completed analysis tells a person about a staged file.

    `latest` is the newest matching analysis. `count` is how many matching
    analyses were found, at most `LOOKUP_LIMIT`.
    """

    kind: PreviousAnalysisKind
    count: int
    latest: AnalysisSummary


def find_previous_analysis_notice(
    store: AnalysisStoreProtocol, *, content_sha256: str, filename: str
) -> PreviousAnalysisNotice | None:
    """The strongest notice that applies, or `None`.

    An exact byte match always wins. Otherwise a completed analysis among the
    most recent `LOOKUP_LIMIT` whose file name matches (compared without regard
    to case) gives the weaker, name-only hint. The name hint carries no diff and
    no claim about how the contents differ; it says only that a file with this
    name was analysed and that this one is not byte-identical to it.
    """
    exact = store.find_completed_by_content_hash(content_sha256, LOOKUP_LIMIT)
    if exact:
        return PreviousAnalysisNotice(PreviousAnalysisKind.SAME_FILE, len(exact), exact[0])
    wanted = filename.casefold()
    same_name = [
        summary
        for summary in store.list_recent(LOOKUP_LIMIT)
        if summary.state is AnalysisState.COMPLETED
        and summary.original_filename.casefold() == wanted
    ]
    if same_name:
        return PreviousAnalysisNotice(PreviousAnalysisKind.SAME_NAME, len(same_name), same_name[0])
    return None
