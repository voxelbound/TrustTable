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
  clean, valid, accurate, reliable, verified, and similar, or said to pass
  or meet all checks, tests, standards or rules.
- `no_issues_claim` — an assertion that no data-quality issues exist, in
  any grammatical shape and whoever asserts it: passive ("no issues were
  found"), active ("the analysis found no issues"), negated detection ("did
  not find any issues", "failed to detect any problems"), or "without/free
  of". "No *other* issues" is not matched (an issue exists), and a
  statement scoped to a named column is exempt.
- `disregard_findings_instruction` — an instruction or assurance to ignore,
  dismiss or override deterministic findings, scores, risk or evidence.
- `score_override_claim` — an assertion that a trust/quality score is
  perfect or maximal, or that risk is zero.
- `fitness_assurance_claim` — an assurance that the dataset is safe to
  use or trust.

Design constraints (each covered by tests):

- **Recognizes a class of claims, not a list of phrasings.** Fixed
  patterns cover distinctive shapes ("you can ignore the findings", "no
  data quality issues were found"), and a token-window matcher covers the
  open-ended part: a whole-dataset subject (`dataset`, `data`, `file`,
  `all rows`, `every record`, ...) linked by a copula or preposition to a
  positive assessment within a short window, so "is in perfect condition",
  "is of excellent quality", "All rows are valid" and the inverted "Not
  only is the dataset perfect" are all recognized. The tests prove this
  over a cross product of subjects, linking frames and adjectives, not
  only over listed examples.
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
  accepted because the negator sits between the subject and the positive
  word; "do not ignore the findings" is accepted because the negator is
  immediately adjacent to the verb. A "not" elsewhere in the sentence does
  not exempt a claim ("Not only is the dataset perfect" is screened), and
  neither does a cheap hedge insertion such as "in some sense". Honest
  hedges ("only partly clean") and column scoping ("the data in the
  quantity column is valid") do stop the match.
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

What is structural and what is enumerated (stated so the coverage is not
overclaimed): grammatical shape is generalized structurally — copular,
prepositional ("in perfect condition"), passive, active verb-object and
negated-detection forms; arbitrary modifiers, numerals and quantifier
phrases between the parts ("passes all 12 automated quality checks",
"every single record"); negation, hedges, "other" and column scope as
barriers. The *vocabulary* of positive assessments, issue nouns, check
nouns and passing verbs is enumerated — broad, and covered by an
independently authored thesaurus test, but finite. An evaluative word that
is on none of the lists is the residual gap.

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
    r"(?:dataset|data\s?set|data|file|table|spreadsheet|worksheet|everything)"
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

_ISSUE_NOUN = (
    r"(?:issues?|problems?|errors?|defects?|flaws?|concerns?|anomal(?:y|ies)|mistakes?|faults?|"
    r"inconsistenc(?:y|ies)|irregularit(?:y|ies)|discrepanc(?:y|ies)|deficienc(?:y|ies)|"
    r"blemish(?:es)?|quality\s+(?:issues?|problems?|concerns?))"
)
_ISSUE_MODIFIER = (
    r"(?:(?:known|apparent|obvious|significant|major|serious|material|remaining|real|"
    r"actual|data|quality|data\s+quality|detected|reported)\s+){0,3}"
)
# A "no issues" statement explicitly scoped to a named column is not a
# whole-dataset claim (the one deliberate exemption; see module docstring).
# Up to four intervening words are allowed ("no issues were found in the
# quantity column"); every quantifier is bounded.
_NOT_COLUMN_SCOPED = (
    r"(?!(?:\s+\w+){0,4}\s+(?:in|for|within|inside|on|with|of|regarding|about)\s+"
    r"(?:(?:the|this|that|its|a|an)\s+)?(?:\w+\s+){0,3}columns?\b)"
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
    # (Possessive "the dataset's perfect" and attributive "a perfect dataset"
    # forms are handled by the token-window matcher below, which — unlike a
    # bare pattern — honors an adjacent negation such as "not a perfect
    # dataset".)
    _compile(
        CLAIM_FAMILY_DATASET_PERFECTION,
        r"\b(?:all|everything)\s+(?:is|looks?|seems?|appears?)\s+"
        r"(?:to\s+be\s+)?(?:well|good|fine|clear|great|perfect|okay|ok|in\s+order)\b"
        r"|\beverything\s+checks\s+out\b",
    ),
    # "Passes / meets all checks, tests, standards, rules" is handled by the
    # token-window matcher below (a universal quantifier and a check noun with
    # arbitrary modifiers between, honoring negation, "other" and a trailing
    # "except ..."); only the bare "passes validation" form stays here.
    _compile(
        CLAIM_FAMILY_DATASET_PERFECTION,
        _NEGATOR + r"(?:passes|passed)\s+(?:validation|quality\s+control|the\s+audit|inspection)\b",
        negatable=True,
    ),
    _compile(
        CLAIM_FAMILY_DATASET_PERFECTION,
        r"\b(?:dataset|data|file|table|spreadsheet|worksheet|everything)\s+checks\s+out\b",
    ),
    # 2. no_issues_claim ---------------------------------------------
    # Subject-free and verb-free: "no issues" is the claim whoever asserts it
    # and however it is phrased — passive ("no issues were found"), active
    # ("the analysis found no issues"), or negated detection ("did not find
    # any issues"). "no *other* issues" is an honest hedge (an issue exists)
    # and is not matched; a statement scoped to a named column is exempt.
    _compile(
        CLAIM_FAMILY_NO_ISSUES,
        r"\b(?:no|zero|nil|not\s+a\s+single|not\s+one)\s+"
        + _ISSUE_MODIFIER
        + _ISSUE_NOUN
        + r"\b"
        + _NOT_COLUMN_SCOPED,
    ),
    _compile(
        CLAIM_FAMILY_NO_ISSUES,
        r"\b(?:without|lacking|lacks?|devoid\s+of|free\s+(?:of|from))\s+"
        r"(?:(?:any|a\s+single|even\s+one)\s+)?"
        + _ISSUE_MODIFIER
        + _ISSUE_NOUN
        + r"\b"
        + _NOT_COLUMN_SCOPED,
    ),
    _compile(
        CLAIM_FAMILY_NO_ISSUES,
        r"\b(?:(?:did|does|do|could|would|can|will|has|have|had)(?:\s+not|n't)|cannot|won't|"
        r"never|fail(?:s|ed)?\s+to|unable\s+to|(?:was|were)\s+unable\s+to)\s+"
        r"(?:(?:yet|ever|actually|really)\s+)?"
        r"(?:find|found|detect(?:ed)?|identif(?:y|ied)|see|saw|seen|observe[d]?|notice[d]?|"
        r"discover(?:ed)?|encounter(?:ed)?|locate[d]?|reveal(?:ed)?|uncover(?:ed)?|"
        r"show(?:ed|n)?|contain(?:ed)?|have|had|exhibit(?:ed)?|turn(?:ed)?\s+up)\s+"
        r"(?:any|a\s+single|even\s+one)\s+"
        + _ISSUE_MODIFIER
        + _ISSUE_NOUN
        + r"\b"
        + _NOT_COLUMN_SCOPED,
    ),
    _compile(
        CLAIM_FAMILY_NO_ISSUES,
        r"\bthere\s+(?:aren't|isn't|weren't|wasn't|are\s+not|is\s+not|were\s+not|was\s+not)\s+"
        r"any\s+" + _ISSUE_MODIFIER + _ISSUE_NOUN + r"\b" + _NOT_COLUMN_SCOPED,
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
        r"|do\s+not\s+worry|don't\s+worry|nothing\s+is\s+wrong|nothing\s+wrong"
        r"|nothing\s+(?:to\s+see|of\s+concern|concerning|unusual))\b",
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
    _compile(
        CLAIM_FAMILY_FITNESS_ASSURANCE,
        r"\b(?:good|ready)\s+to\s+go\b"
        r"|\bgo\s+ahead\s+and\s+(?:use|trust|rely\s+on)\b"
        r"|\bfeel\s+free\s+to\s+(?:use|trust|rely\s+on)\b"
        r"|\bno\s+reason\s+not\s+to\s+(?:use|trust|rely\s+on)\b"
        r"|\bcan\s+(?:be\s+)?(?:safely\s+|confidently\s+|fully\s+|completely\s+)?"
        r"(?:trusted|relied\s+(?:on|upon))\b",
    ),
    # 3 (continued). Passive and adjectival dismissal of deterministic results.
    _compile(
        CLAIM_FAMILY_DISREGARD_FINDINGS,
        r"\b"
        + _DETERMINISTIC_NOUN
        + r"\s+(?:(?:can|may|could|should|might|will|would|are|is|were|was)\s+)?"
        r"(?:(?:safely|simply|just|all|be|being|been|now)\s+){0,3}"
        r"(?:ignored|disregarded|dismissed|overlooked|discarded|skipped|overridden|"
        r"overruled|bypassed|suppressed)\b",
    ),
    _compile(
        CLAIM_FAMILY_DISREGARD_FINDINGS,
        r"\b(?:findings?|warnings?|alerts?|flags?|detections?|issues?|results?)\s+"
        r"(?:are|is|were|was)\s+"
        r"(?:(?:all|just|merely|simply|mostly|probably|likely|really|completely|entirely|"
        r"totally|essentially)\s+){0,3}"
        r"(?:false\s+(?:positives?|alarms?)|irrelevant|unimportant|meaningless|noise|spurious|"
        r"not\s+(?:important|relevant|a\s+concern|worth\s+(?:reviewing|worrying|attention|"
        r"your\s+time)))\b",
    ),
    _compile(
        CLAIM_FAMILY_DISREGARD_FINDINGS,
        r"\bno\s+(?:further\s+|additional\s+|more\s+)?"
        r"(?:action|review|attention|follow-up|follow\s+up|fix|fixes|remediation)\s+"
        r"(?:is\s+|are\s+)?(?:required|needed|necessary|warranted|called\s+for)\b"
        r"|\b(?:don't|do\s+not|no\s+need\s+to)\s+bother\b"
        r"|\bpay\s+no\s+(?:attention|heed)\s+to\b"
        r"|\b(?:needn't|need\s+not)\s+worry\b"
        r"|\bnothing\s+to\s+(?:be\s+)?(?:concerned|worried)\s+about\b",
    ),
    # 4 (continued). Wider trust/quality and overall-risk assertions.
    _compile(
        CLAIM_FAMILY_SCORE_OVERRIDE,
        r"\b(?:trust|quality|reliability|overall)\s+"
        r"(?:score|rating|level|assessment|label)\s+"
        r"(?:is|should\s+be|must\s+be|has\s+been|was|is\s+now|of|to)\s+"
        r"(?:(?:now|actually|really|effectively|very)\s+)?"
        r"(?:high|great|good|strong|top|full)\b",
    ),
    _compile(
        CLAIM_FAMILY_SCORE_OVERRIDE,
        r"\b(?:overall|dataset|data)\s+risk(?:\s+(?:score|level|rating))?\s+"
        r"(?:is|should\s+be|has\s+been|was|is\s+now|of|to)\s+"
        r"(?:(?:now|actually|really|effectively|very)\s+)?"
        r"(?:low|minimal|lowest)\b",
    ),
)


# --- Token-window matcher --------------------------------------------------
#
# Fixed-adjacency patterns alone are too narrow: "the dataset is in perfect
# condition", "the data is of excellent quality" and "all rows are valid" all
# assert the same false whole-dataset claim while sharing no exact phrasing
# with the patterns above. This matcher therefore recognizes the *class*: a
# whole-dataset subject, linked by a copula/preposition, to a positive
# assessment within a short window, with negation, column scoping and
# partial quantifiers acting as barriers. It is linear in the narrative's
# length (each subject scans at most `_WINDOW` tokens) and is only ever
# additive to the patterns above.

_WINDOW: Final[int] = 6

_SUBJECT_MASS: Final[frozenset[str]] = frozenset(
    {
        "dataset",
        "data",
        "file",
        "table",
        "spreadsheet",
        "worksheet",
        "workbook",
        "csv",
        "sheet",
        "everything",
    }
)
_SUBJECT_PLURAL: Final[frozenset[str]] = frozenset(
    {"records", "rows", "entries", "values", "observations"}
)
_SUBJECT_SINGULAR: Final[frozenset[str]] = frozenset({"row", "record", "entry", "value"})
_DEFINITE: Final[frozenset[str]] = frozenset(
    {"the", "this", "that", "these", "those", "your", "our", "its", "my"}
)
_UNIVERSAL: Final[frozenset[str]] = frozenset(
    {"all", "every", "each", "entire", "whole", "any", "both"}
)

_LINKS: Final[frozenset[str]] = frozenset(
    {
        "is", "are", "was", "were", "be", "been", "being", "am",
        "look", "looks", "looked", "appear", "appears", "appeared",
        "seem", "seems", "seemed", "remain", "remains", "remained",
        "stay", "stays", "has", "have", "had", "of", "in", "as",
        "contains", "contain", "shows", "show", "exhibits", "displays",
        "holds", "includes",
    }
)  # fmt: skip

# Tokens that end a subject's scan: negation, "far/less than", exceptions,
# column/field/cell scoping and partial quantifiers. Hitting one means the
# nearby positive word is not an unqualified whole-dataset assertion.
_NEGATION: Final[frozenset[str]] = frozenset(
    {
        "not", "no", "never", "nor", "neither", "cannot", "can't", "cant",
        "isn't", "aren't", "wasn't", "weren't", "don't", "doesn't", "didn't",
        "hardly", "barely", "far", "less", "without", "except", "apart", "aside",
        "unless",
    }
)  # fmt: skip
_COLUMN_MARKERS: Final[frozenset[str]] = frozenset(
    {"column", "columns", "field", "fields", "cell", "cells"}
)
# Honest hedges: "partly clean" is not a whole-dataset perfection claim.
_HEDGES: Final[frozenset[str]] = frozenset({"partly", "partially", "somewhat", "only", "merely"})
# Partial quantifiers restrict a *different* noun phrase only when they occur
# before the linking verb ("the file, some rows of which are valid"). After
# the link they are not barriers, so a cheap "in some sense" insertion cannot
# hide a claim ("the dataset is, in some sense, perfect").
_PARTIAL_QUANTIFIERS: Final[frozenset[str]] = frozenset(
    {
        "some", "few", "several", "one", "two", "three", "four", "five",
        "single", "first", "last", "remaining", "other", "another",
    }
)  # fmt: skip
_BARRIERS: Final[frozenset[str]] = _NEGATION | _HEDGES | _COLUMN_MARKERS

_POSITIVE: Final[frozenset[str]] = frozenset(
    {
        "perfect", "perfectly", "flawless", "flawlessly", "pristine", "spotless",
        "immaculate", "impeccable", "faultless", "unblemished", "exemplary", "ideal",
        "superb", "outstanding", "exceptional", "excellent", "great", "fantastic",
        "wonderful", "terrific", "clean", "valid", "accurate", "correct", "reliable",
        "trustworthy", "trusted", "sound", "healthy", "fine", "okay", "ok", "good",
        "verified", "validated", "certified", "approved", "vetted",
        "error-free", "issue-free", "problem-free", "defect-free", "fault-free",
        "flaw-free", "top-notch", "high-quality", "top-quality", "good-quality",
        "first-rate", "first-class", "top-tier", "world-class", "unrivaled", "unrivalled",
        "unmatched", "unimpeachable", "extraordinary", "remarkable", "stellar", "splendid",
        "magnificent", "marvelous", "marvellous", "brilliant", "textbook", "robust",
        "solid", "polished", "irreproachable", "blameless", "untainted", "uncorrupted",
        "pure", "gold-standard", "squeaky-clean",
    }
)  # fmt: skip
_POSITIVE_BIGRAMS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("high", "quality"), ("top", "quality"), ("good", "quality"), ("top", "notch"),
        ("error", "free"), ("issue", "free"), ("problem", "free"), ("defect", "free"),
        ("fault", "free"), ("flaw", "free"), ("all", "good"), ("all", "clear"),
        ("top", "tier"), ("first", "rate"), ("first", "class"), ("world", "class"),
        ("gold", "standard"), ("squeaky", "clean"),
    }
)  # fmt: skip
# Superlatives are praise only when they qualify quality ("of the highest
# quality", "in the best possible shape") or directly follow a copula ("is
# the best"); otherwise "the dataset's highest value" would be flagged.
_POSITIVE_CONTEXTUAL: Final[frozenset[str]] = frozenset(
    {
        "highest", "best", "finest", "greatest", "utmost", "superior", "supreme",
        "premium", "optimal", "optimum", "prime",
    }
)  # fmt: skip
_QUALITY_NOUNS: Final[frozenset[str]] = frozenset(
    {
        "quality", "condition", "shape", "standard", "standards", "state", "form",
        "grade", "order", "caliber", "calibre", "possible", "available",
    }
)  # fmt: skip
# Strong perfection words that also count when they *precede* the subject
# ("a flawless dataset").
_STRONG: Final[frozenset[str]] = frozenset(
    {
        "perfect", "flawless", "pristine", "spotless", "immaculate", "impeccable",
        "faultless", "unblemished", "error-free", "issue-free", "problem-free",
        "defect-free", "fault-free", "flaw-free",
    }
)  # fmt: skip

_ISSUE_NOUNS: Final[frozenset[str]] = frozenset(
    {
        "issue", "issues", "problem", "problems", "error", "errors", "defect", "defects",
        "flaw", "flaws", "concern", "concerns", "anomaly", "anomalies", "mistake",
        "mistakes", "fault", "faults", "inconsistency", "inconsistencies",
        "irregularity", "irregularities", "discrepancy", "discrepancies",
        "deficiency", "deficiencies", "blemish", "blemishes",
    }
)  # fmt: skip
_ISSUE_MODIFIERS: Final[frozenset[str]] = frozenset(
    {
        "known", "apparent", "obvious", "significant", "major", "serious", "material",
        "remaining", "real", "actual", "data", "quality", "detected", "reported",
        "single", "any", "a", "even", "one", "visible", "noticeable", "notable",
    }
)  # fmt: skip
_COLUMN_SCOPE_MARKERS: Final[frozenset[str]] = frozenset({"column", "columns", "field", "fields"})
_SCOPING_PREPOSITIONS: Final[frozenset[str]] = frozenset(
    {"in", "for", "within", "inside", "on", "with", "of", "regarding", "about"}
)


def _subject_span(tokens: list[str], index: int) -> tuple[int, bool] | None:
    """If a whole-dataset subject starts at `index`, return `(end, possessive)`
    where `end` is the index just past it; otherwise `None`."""
    token = tokens[index]
    possessive = token.endswith("'s")
    base = token[:-2] if possessive else token
    if base == "data" and index + 1 < len(tokens) and tokens[index + 1] == "set":
        return index + 2, False
    if base in _SUBJECT_MASS:
        return index + 1, possessive
    if base in _SUBJECT_PLURAL and _determiner_before(tokens, index, _DETERMINERS):
        return index + 1, possessive
    if base in _SUBJECT_SINGULAR and _determiner_before(tokens, index, _UNIVERSAL):
        return index + 1, possessive
    return None


def _determiner_before(tokens: list[str], index: int, allowed: frozenset[str]) -> bool:
    """True when a determiner from `allowed` precedes the noun at `index`,
    allowing up to two modifiers in between ("every single record", "all 300
    rows") but not a partial count ("the two rows", "some rows")."""
    for back in (1, 2, 3):
        position = index - back
        if position < 0:
            return False
        token = tokens[position]
        if token in allowed:
            return True
        # "every single" and "every last" are emphatic universals, not counts.
        emphatic = token in {"single", "last"} and tokens[max(0, position - 1)] in _UNIVERSAL
        if token in _BARRIERS or (token in _PARTIAL_QUANTIFIERS and not emphatic):
            return False
    return False


def _is_positive_at(tokens: list[str], index: int) -> bool:
    token = tokens[index]
    if token in _POSITIVE:
        return True
    if token in _POSITIVE_CONTEXTUAL:
        if any(nearby in _QUALITY_NOUNS for nearby in tokens[index + 1 : index + 3]):
            return True
        previous = tokens[index - 1] if index >= 1 else ""
        previous_two = tokens[index - 2] if index >= 2 else ""
        return previous in _COPULA_LINKS or (
            previous in _DETERMINERS and previous_two in _COPULA_LINKS
        )
    following = tokens[index + 1] if index + 1 < len(tokens) else ""
    if (token, following) in _POSITIVE_BIGRAMS:
        return True
    # "in order" (but not the ubiquitous "in order to").
    third = tokens[index + 2] if index + 2 < len(tokens) else ""
    return token == "in" and following == "order" and third != "to"


def _column_scoped_after(tokens: list[str], start: int) -> bool:
    """True when the tokens right after a "no issues" noun scope it to a
    named column ("no issues in the quantity column")."""
    if start >= len(tokens) or tokens[start] not in _SCOPING_PREPOSITIONS:
        return False
    return any(token in _COLUMN_SCOPE_MARKERS for token in tokens[start + 1 : start + 6])


def _issue_free_at(tokens: list[str], index: int) -> bool:
    """True when an "absence of problems" phrase starts at `index`
    ("no errors", "without any issues", "free of defects", "not a single
    mistake") and is not scoped to a named column."""
    token = tokens[index]
    count = len(tokens)
    if token in {"no", "zero", "nil", "without", "lacking", "lacks"}:
        cursor = index + 1
    elif token in {"devoid", "free"} and index + 1 < count and tokens[index + 1] in {"of", "from"}:
        cursor = index + 2
    elif token == "not" and tokens[index + 1 : index + 3] == ["a", "single"]:
        cursor = index + 3
    else:
        return False
    skipped = 0
    while cursor < count and tokens[cursor] in _ISSUE_MODIFIERS and skipped < 3:
        cursor += 1
        skipped += 1
    if cursor < count and tokens[cursor] in _ISSUE_NOUNS:
        return not _column_scoped_after(tokens, cursor + 1)
    return False


def _strong_precedes(tokens: list[str], index: int) -> bool:
    """True for an attributive perfection word right before the subject
    ("a flawless dataset"), unless it is negated ("not a perfect dataset")."""
    for back in (1, 2):
        position = index - back
        if position < 0:
            return False
        if tokens[position] in _STRONG:
            window = tokens[max(0, position - 3) : position]
            return not any(token in _NEGATION for token in window)
    return False


# A passing/complying verb followed by a universal quantifier and a check noun
# is an assurance ("passes all automated quality checks", "meets every single
# requirement"), with arbitrary modifiers or numerals in between.
_PASSING_VERBS: Final[frozenset[str]] = frozenset(
    {
        "pass", "passes", "passed", "passing", "meet", "meets", "met", "meeting",
        "satisfy", "satisfies", "satisfied", "satisfying", "clear", "clears", "cleared",
        "comply", "complies", "complied", "conform", "conforms", "conformed",
        "survive", "survives", "survived",
    }
)  # fmt: skip
_PASSING_QUANTIFIERS: Final[frozenset[str]] = frozenset(
    {"all", "every", "each", "any", "both", "entire", "full", "complete", "everything"}
)
_CHECK_NOUNS: Final[frozenset[str]] = frozenset(
    {
        "check", "checks", "test", "tests", "validation", "validations", "standard",
        "standards", "requirement", "requirements", "rule", "rules", "criteria",
        "criterion", "audit", "audits", "inspection", "inspections", "verification",
        "verifications", "control", "controls", "specification", "specifications",
        "spec", "specs", "threshold", "thresholds", "benchmark", "benchmarks",
    }
)  # fmt: skip
_EXCEPTION_WORDS: Final[frozenset[str]] = frozenset(
    {"except", "apart", "aside", "save", "excluding", "besides"}
)


def _passing_assurance_at(tokens: list[str], index: int) -> bool:
    """True when the passing verb at `index` takes a universal quantifier and
    then a check noun, with negation, "other/remaining" and a trailing
    exception all defusing it ("does not pass all checks", "passes all other
    checks", "passes all checks except one")."""
    if any(token in _NEGATION for token in tokens[max(0, index - 3) : index]):
        return False
    count = len(tokens)
    for quantifier_at in range(index + 1, min(index + 5, count)):
        token = tokens[quantifier_at]
        if token in _NEGATION:
            return False
        if token not in _PASSING_QUANTIFIERS:
            continue
        for noun_at in range(quantifier_at + 1, min(quantifier_at + 9, count)):
            candidate = tokens[noun_at]
            if candidate in {"other", "remaining"} or candidate in _NEGATION:
                break
            if candidate in _CHECK_NOUNS:
                trailing = tokens[noun_at + 1 : noun_at + 4]
                if not any(word in _EXCEPTION_WORDS for word in trailing):
                    return True
                break
    return False


def _check_noun_follows(tokens: list[str], start: int) -> bool:
    """True when a check noun appears soon after a *whole-dataset subject's*
    passing verb, with no negation or exception in between."""
    for position in range(start, min(start + _WINDOW, len(tokens))):
        token = tokens[position]
        if token in _NEGATION or token in _EXCEPTION_WORDS or token in {"other", "remaining"}:
            return False
        if token in _CHECK_NOUNS:
            trailing = tokens[position + 1 : position + 4]
            return not any(word in _EXCEPTION_WORDS for word in trailing)
    return False


_COPULA_LINKS: Final[frozenset[str]] = frozenset(
    {"is", "are", "was", "were", "look", "looks", "seem", "seems", "appear", "appears",
     "remain", "remains"}
)  # fmt: skip
_DETERMINERS: Final[frozenset[str]] = _DEFINITE | _UNIVERSAL


def _copula_before(tokens: list[str], index: int) -> bool:
    """True for the inverted form "is the dataset perfect" / "Not only is the
    dataset perfect": a copula directly before the subject (skipping only
    determiners) already links it to what follows."""
    for back in (1, 2):
        position = index - back
        if position < 0:
            return False
        token = tokens[position]
        if token in _COPULA_LINKS:
            return True
        if token not in _DETERMINERS:
            return False
    return False


def _token_window_families(tokens: list[str]) -> set[str]:
    matched: set[str] = set()
    for index in range(len(tokens)):
        span = _subject_span(tokens, index)
        if span is None:
            continue
        end, possessive = span
        if _strong_precedes(tokens, index):
            matched.add(CLAIM_FAMILY_DATASET_PERFECTION)
        linked = possessive or _copula_before(tokens, index)
        for position in range(end, min(end + _WINDOW, len(tokens))):
            token = tokens[position]
            if linked and _issue_free_at(tokens, position):
                matched.add(CLAIM_FAMILY_NO_ISSUES)
                break
            if token in _BARRIERS:
                break
            if not linked and token in _PARTIAL_QUANTIFIERS:
                break
            if token in _PASSING_VERBS and _check_noun_follows(tokens, position + 1):
                matched.add(CLAIM_FAMILY_DATASET_PERFECTION)
                break
            if token in _LINKS:
                linked = True
            if linked and _is_positive_at(tokens, position):
                matched.add(CLAIM_FAMILY_DATASET_PERFECTION)
                break
    # Subject-free: any passing verb + universal quantifier + check noun.
    if any(
        token in _PASSING_VERBS and _passing_assurance_at(tokens, index)
        for index, token in enumerate(tokens)
    ):
        matched.add(CLAIM_FAMILY_DATASET_PERFECTION)
    return matched


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
    matched |= _token_window_families(normalized.split(" "))
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
