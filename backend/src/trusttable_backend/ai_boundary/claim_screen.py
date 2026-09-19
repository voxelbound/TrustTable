"""Bounded unsupported-claim screen for model narratives (`EVAL-AI-01`).

`validate_model_output` (`SEC-02`) is otherwise purely structural: it
verifies schema, evidence IDs, column names, numeric claims, severity,
provenance and the absence of unsupported control fields, but it never
looks at what the narrative *says*. A schema-valid output whose only
content is "this dataset is perfect" would therefore be accepted and
shown to the user as an AI interpretation, even though deterministic
findings contradict it (`docs/testing-strategy.md` §3: "unsupported
'dataset is perfect' output is rejected").

This module closes that gap with a **bounded, closed, documented** screen
over the narrative text. It is defense in depth, not the guarantee:
deterministic authority (`docs/product-requirements.md` §5.3) already
holds structurally, because no output field can remove a finding or change
a score. The screen exists so a false whole-dataset assertion cannot be
*presented* as an accepted AI interpretation beside those findings.

Five closed claim families are recognized (`CLAIM_FAMILY_IDS`):

- `dataset_perfection_claim` — a dataset-level subject asserted perfect,
  clean, valid, accurate, reliable, and similar.
- `no_issues_claim` — an assertion that no data-quality issues exist.
- `disregard_findings_instruction` — an instruction or assurance to ignore,
  dismiss or override deterministic findings, scores, risk or evidence.
- `score_override_claim` — an assertion that a trust/quality score is
  perfect or maximal, or that risk is zero.
- `fitness_assurance_claim` — an assurance that the dataset is safe to
  use or trust.

Design constraints (each covered by tests):

- **Bounded and non-catastrophic.** Every pattern uses only small, fixed
  quantifiers and simple alternations; no unbounded nested quantifiers.
  The *whole* narrative is screened (never truncated), so padding a claim
  beyond a length cap cannot evade it; matching stays linear in length.
- **Normalized before matching.** Compatibility decomposition, removal of
  zero-width/format characters and combining marks, case folding,
  unification of dash and apostrophe variants, and collapse of
  markdown/punctuation/whitespace to single spaces, so trivial obfuscation
  does not evade the patterns.
- **Negation is narrow, never a global escape hatch.** "is not perfect" is
  accepted because the negator sits inside the copula gap; "do not ignore
  the findings" is accepted because the negator is immediately adjacent to
  the verb. A "not" elsewhere in the sentence does not exempt a claim.
- **Biased toward rejecting.** A false positive degrades safely to the
  deterministic explanation (`docs/product-requirements.md` §5.7); a false
  negative is the real risk. The one deliberate exemption is a "no issues
  found" statement that is explicitly scoped to a named column, because a
  column-level "nothing wrong here" is not a whole-dataset claim.
- **Deliberately excludes "ignore previous instructions" phrasing.** An
  explanation that merely *names* a flagged injection pattern must not be
  rejected, so instruction-echo wording is out of scope here (that content
  is the prompt-injection detector's job, `DET-SEC-01`). Likewise a
  *priority* score of 100 is the worst case, not a reassurance, so score
  claims are only screened in the direction that reassures.

Documented limitation: this is a lexical screen. A sufficiently creative
paraphrase can evade it, cross-script homoglyphs are not folded, and it
screens English only. It does not replace deterministic authority and
makes no claim of semantic completeness; extending it means adding a
family or pattern with a positive and a negative-control test, and bumping
`CLAIM_SCREEN_VERSION`.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import, no provider
import, no dynamic code execution. Stdlib only.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

#: Bumped whenever a family or pattern is added, removed, or materially
#: changed, so a future consumer can tell which screen judged an output.
CLAIM_SCREEN_VERSION: Final[str] = "1"

CLAIM_FAMILY_DATASET_PERFECTION: Final[str] = "dataset_perfection_claim"
CLAIM_FAMILY_NO_ISSUES: Final[str] = "no_issues_claim"
CLAIM_FAMILY_DISREGARD_FINDINGS: Final[str] = "disregard_findings_instruction"
CLAIM_FAMILY_SCORE_OVERRIDE: Final[str] = "score_override_claim"
CLAIM_FAMILY_FITNESS_ASSURANCE: Final[str] = "fitness_assurance_claim"

#: The closed set of claim family identifiers, in evaluation order.
CLAIM_FAMILY_IDS: Final[tuple[str, ...]] = (
    CLAIM_FAMILY_DATASET_PERFECTION,
    CLAIM_FAMILY_NO_ISSUES,
    CLAIM_FAMILY_DISREGARD_FINDINGS,
    CLAIM_FAMILY_SCORE_OVERRIDE,
    CLAIM_FAMILY_FITNESS_ASSURANCE,
)

# --- Normalization --------------------------------------------------------

_DASHES: Final[re.Pattern[str]] = re.compile("[‐‑‒–—―−]")
_APOSTROPHES: Final[re.Pattern[str]] = re.compile("[‘’‛ʼ′]")
# Anything that is not a word character, percent sign, apostrophe, hyphen
# or whitespace becomes a space (this also removes markdown emphasis and
# all sentence punctuation), and underscores become spaces so `_perfect_`
# and snake_case identifiers tokenize as words.
_NOT_TOKEN: Final[re.Pattern[str]] = re.compile(r"[^\w%'\-\s]|_")
# A hyphen that is not between two word characters is punctuation, not
# part of a compound like `error-free`.
_LOOSE_HYPHEN: Final[re.Pattern[str]] = re.compile(r"(?<!\w)-|-(?!\w)")
_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
_DROPPED_CATEGORIES: Final[frozenset[str]] = frozenset({"Cf", "Mn"})


def normalize_narrative(text: str) -> str:
    """Return `text` in the canonical form the claim patterns match.

    Never truncates: the whole narrative is screened.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(
        ch for ch in decomposed if unicodedata.category(ch) not in _DROPPED_CATEGORIES
    )
    folded = _DASHES.sub("-", stripped)
    folded = _APOSTROPHES.sub("'", folded)
    folded = folded.casefold()
    folded = _NOT_TOKEN.sub(" ", folded)
    folded = _LOOSE_HYPHEN.sub(" ", folded)
    return _WHITESPACE.sub(" ", folded).strip()


# --- Pattern building blocks (all bounded) --------------------------------

_DETERMINER = (
    r"(?:(?:the|this|that|your|our|entire|whole|overall|complete|full|uploaded|"
    r"provided|given)\s+){0,3}"
)
_SUBJECT_NOUN = (
    r"(?:dataset|data\s?set|data|file|table|spreadsheet|worksheet|records|everything)"
    r"(?:\s+quality)?"
)
_SUBJECT = _DETERMINER + _SUBJECT_NOUN

_COPULA = (
    r"(?:is|are|was|were|looks?|appears?|seems?|remains?|stays?|"
    r"has\s+been|have\s+been|is\s+now|are\s+now)"
)
_INTENSIFIER = (
    r"(?:(?:completely|entirely|fully|totally|perfectly|absolutely|overall|essentially|"
    r"basically|generally|otherwise|really|very|quite|truly|indeed|actually|literally|"
    r"nearly|almost|mostly|largely|pretty|fairly|reasonably|relatively|"
    r"in\s+fact|in\s+short|100\s?%)\s+){0,3}"
)
_QUALITY_ADJ = (
    r"(?:perfect|flawless|pristine|spotless|immaculate|impeccable|faultless|"
    r"(?:error|issue|problem|defect|fault|flaw)[- ]free|clean|valid|accurate|correct|"
    r"reliable|trustworthy|trusted|sound|fine|okay|ok|good|excellent|high[- ]quality)"
)
_STRONG_ADJ = (
    r"(?:perfect|flawless|pristine|spotless|immaculate|impeccable|faultless|"
    r"(?:error|issue|problem|defect)[- ]free)"
)

_ISSUE_NOUN = (
    r"(?:issues?|problems?|errors?|defects?|flaws?|concerns?|anomalies|"
    r"inconsistenc(?:y|ies)|quality\s+(?:issues?|problems?|concerns?))"
)
_ISSUE_MODIFIER = (
    r"(?:(?:known|apparent|obvious|significant|major|serious|material|remaining|real|"
    r"actual|data|quality|data\s+quality|detected|reported)\s+){0,3}"
)
_ZERO_INTENSIFIER = r"(?:absolutely\s+|virtually\s+|essentially\s+)?"
# A "no issues" statement explicitly scoped to a named column is not a
# whole-dataset claim (the one deliberate exemption; see module docstring).
_NOT_COLUMN_SCOPED = (
    r"(?!\s+(?:in|for|within|inside|on|with|of)\s+(?:(?:the|this|that|its|a|an)\s+)?"
    r"(?:\w+\s+){0,3}columns?\b)"
)

# Negators recognized only when *adjacent* to the claim verb/phrase. A
# match that captured this group is a negated statement ("do not ignore
# the findings", "it is not safe to use") and is not a claim.
_NEGATOR = (
    r"(?P<neg>(?:(?:do|does|did|should|must|would|could|will|can|shall)\s+not|"
    r"cannot|can't|don't|doesn't|didn't|shouldn't|mustn't|wouldn't|couldn't|won't|"
    r"never|not|isn't|aren't|wasn't|weren't|hardly|barely|far\s+from|less\s+than|"
    r"anything\s+but)\s+"
    r"(?:(?:simply|just|ever|really|yet|be|to|safe\s+to|wise\s+to|advisable\s+to|"
    r"recommended\s+to|okay\s+to|ok\s+to|appropriate\s+to|advised\s+to)\s+)?)?"
)

_ACTION = (
    r"(?:ignore|ignoring|disregard|disregarding|dismiss|dismissing|discard|discarding|"
    r"overrule|overruling|override|overriding|overlook|overlooking|bypass|bypassing|"
    r"suppress|suppressing|omit|omitting|hide|hiding|remove|removing|delete|deleting)"
)
_ACTION_DETERMINERS = (
    r"(?:(?:all|any|every|each|the|these|those|this|that|your|its|of|previous|prior|"
    r"earlier|other|deterministic|automated|detected|reported|computed|calculated|"
    r"listed|above|remaining|minor)\s+){0,4}"
)
_DETERMINISTIC_NOUN = (
    r"(?:findings?|warnings?|alerts?|scores?|risks?|risk\s+scores?|trust\s+scores?|"
    r"evidence|detectors?|detections?|assessments?|flags?|results?|checks?|issues?|problems?)"
)


@dataclass(frozen=True, slots=True)
class _Pattern:
    family: str
    regex: re.Pattern[str]
    negatable: bool = False


def _compile(family: str, source: str, *, negatable: bool = False) -> _Pattern:
    return _Pattern(family=family, regex=re.compile(source), negatable=negatable)


_PATTERNS: Final[tuple[_Pattern, ...]] = (
    # 1. dataset_perfection_claim ------------------------------------
    _compile(
        CLAIM_FAMILY_DATASET_PERFECTION,
        r"\b" + _SUBJECT + r"\s+" + _COPULA + r"\s+" + _INTENSIFIER + _QUALITY_ADJ + r"\b",
    ),
    _compile(
        CLAIM_FAMILY_DATASET_PERFECTION,
        r"\b" + _SUBJECT + r"'s\s+" + _INTENSIFIER + _STRONG_ADJ + r"\b",
    ),
    _compile(
        CLAIM_FAMILY_DATASET_PERFECTION,
        r"\b"
        + _STRONG_ADJ
        + r"\s+(?:quality\s+)?(?:dataset|data\s?set|data|file|table|spreadsheet|worksheet)\b",
    ),
    # 2. no_issues_claim ---------------------------------------------
    _compile(
        CLAIM_FAMILY_NO_ISSUES,
        r"\b(?:no|zero|not\s+a\s+single)\s+"
        + _ISSUE_MODIFIER
        + _ISSUE_NOUN
        + r"\s+(?:(?:was|were|is|are|has\s+been|have\s+been)\s+)?"
        r"(?:found|detected|identified|observed|present|exist|exists|remain|remains|reported)\b"
        + _NOT_COLUMN_SCOPED,
    ),
    _compile(
        CLAIM_FAMILY_NO_ISSUES,
        r"\bthere\s+(?:are|is|were|was)\s+"
        + _ZERO_INTENSIFIER
        + r"(?:no|zero)\s+"
        + _ISSUE_MODIFIER
        + _ISSUE_NOUN
        + r"\b"
        + _NOT_COLUMN_SCOPED,
    ),
    _compile(
        CLAIM_FAMILY_NO_ISSUES,
        r"\b"
        + _SUBJECT
        + r"\s+(?:has|have|contains?|shows?|exhibits?|displays?)\s+"
        + _ZERO_INTENSIFIER
        + r"(?:no|zero)\s+"
        + _ISSUE_MODIFIER
        + _ISSUE_NOUN
        + r"\b",
    ),
    _compile(
        CLAIM_FAMILY_NO_ISSUES,
        r"\b(?:no|zero)\s+(?:data\s+)?quality\s+(?:issues?|problems?|concerns?)\b"
        r"|\b(?:no|zero)\s+data\s+(?:issues?|problems?|errors?)\b",
    ),
    _compile(
        CLAIM_FAMILY_NO_ISSUES,
        r"\b"
        + _SUBJECT
        + r"\s+(?:is|are|looks?|appears?|remains?)\s+"
        + _INTENSIFIER
        + r"(?:free\s+(?:of|from)|devoid\s+of|without)\s+(?:any\s+)?"
        + _ISSUE_MODIFIER
        + _ISSUE_NOUN
        + r"\b",
    ),
    # 3. disregard_findings_instruction -------------------------------
    _compile(
        CLAIM_FAMILY_DISREGARD_FINDINGS,
        r"\b" + _NEGATOR + _ACTION + r"\s+" + _ACTION_DETERMINERS + _DETERMINISTIC_NOUN + r"\b",
        negatable=True,
    ),
    _compile(
        CLAIM_FAMILY_DISREGARD_FINDINGS,
        r"\b" + _NEGATOR + r"(?:safe|fine|okay|ok|acceptable|alright)\s+to\s+"
        r"(?:ignore|disregard|dismiss|skip|overlook)\b",
        negatable=True,
    ),
    _compile(
        CLAIM_FAMILY_DISREGARD_FINDINGS,
        r"\b(?:no\s+need\s+to\s+(?:worry|fix|address|review|investigate|check|act|do\s+anything)"
        r"|nothing\s+(?:to\s+(?:worry|fix|address|fear|do)|for\s+you\s+to\s+(?:do|worry|fix))"
        r"|do\s+not\s+worry|don't\s+worry|nothing\s+is\s+wrong|nothing\s+wrong)\b",
    ),
    # 4. score_override_claim ----------------------------------------
    _compile(
        CLAIM_FAMILY_SCORE_OVERRIDE,
        r"\b(?:trust|quality|reliability|overall)\s+"
        r"(?:score|rating|level|assessment|label)\s+"
        r"(?:is|should\s+be|must\s+be|has\s+been|was|is\s+now|of|to)\s+"
        r"(?:(?:now|actually|really|effectively)\s+)?"
        r"(?:perfect|100|maximum|maximal|max|excellent|highest|high\s+confidence)\b",
    ),
    _compile(
        CLAIM_FAMILY_SCORE_OVERRIDE,
        r"\b(?:overall\s+|dataset\s+|data\s+)?risk(?:\s+(?:score|level|rating))?\s+"
        r"(?:is|should\s+be|has\s+been|was|is\s+now|of|to)\s+"
        r"(?:(?:now|actually|really|effectively)\s+)?"
        r"(?:zero|none|negligible|nil|nonexistent|non-existent)\b",
    ),
    # 5. fitness_assurance_claim -------------------------------------
    _compile(
        CLAIM_FAMILY_FITNESS_ASSURANCE,
        r"\b"
        + _SUBJECT
        + r"\s+"
        + _COPULA
        + r"\s+"
        + _INTENSIFIER
        + _NEGATOR
        + r"(?:safe|ready|fit|suitable|good\s+enough|acceptable|approved)\s+(?:to|for)\s+"
        r"(?:use|trust|rely(?:\s+on)?|production|decision-making|decision\s+making|"
        r"reporting|deployment|consumption)\b",
        negatable=True,
    ),
    _compile(
        CLAIM_FAMILY_FITNESS_ASSURANCE,
        r"\byou\s+can\s+(?:safely\s+|confidently\s+|fully\s+|completely\s+)?"
        r"(?:use|trust|rely\s+on|proceed\s+with)\s+"
        r"(?:it|this|the\s+data(?:set)?|this\s+data(?:set)?|the\s+file)\b",
    ),
)


def screen_narrative(narrative: str) -> frozenset[str]:
    """Return the claim families `narrative` asserts, empty when none.

    The empty result means only that no closed-family pattern matched —
    not that the narrative is true (see the module's documented
    limitation). Never raises for any `str` input; matching time is linear
    in the narrative's length.
    """
    normalized = normalize_narrative(narrative)
    if not normalized:
        return frozenset()
    matched: set[str] = set()
    for pattern in _PATTERNS:
        if pattern.family in matched:
            continue
        for match in pattern.regex.finditer(normalized):
            if pattern.negatable and match.group("neg"):
                continue
            matched.add(pattern.family)
            break
    return frozenset(matched)


__all__ = [
    "CLAIM_FAMILY_DATASET_PERFECTION",
    "CLAIM_FAMILY_DISREGARD_FINDINGS",
    "CLAIM_FAMILY_FITNESS_ASSURANCE",
    "CLAIM_FAMILY_IDS",
    "CLAIM_FAMILY_NO_ISSUES",
    "CLAIM_FAMILY_SCORE_OVERRIDE",
    "CLAIM_SCREEN_VERSION",
    "normalize_narrative",
    "screen_narrative",
]
