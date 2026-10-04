"""The first real, explicit detector registration (`DET-02` partial),
matching `docs/detector-framework.md` §9's own example pattern:

```python
DETECTORS = [
    ExactDuplicateRowsDetector(),
    MissingIdentifierDetector(),
    LineTotalMismatchDetector(),
    PossiblePromptInjectionDetector(),
]
```

All twelve `DET-02` detectors exist — the two structural detectors
(`WP-014`), the two completeness detectors (`WP-015`), the two
consistency detectors (`WP-016`), the two validity detectors (`WP-017`),
the invalid-percentages/line-total-mismatch pair (`WP-018`), and the
constant-column/extreme-outliers pair (`WP-019`), completing `DET-02` in
full. `DET-SEC-01`'s `PossiblePromptInjectionDetector` (`WP-021`) extends
this list additively to 13/13, the required
`security.possible_llm_prompt_injection` security detector
(`docs/detector-framework.md` §14).

`DET-03` slice 1 (`WP-100`) adds `FullyEmptyRowsDetector` and
`InconsistentBooleansDetector`, bringing the list to 15; slice 2 (`WP-101`)
adds `ImplausiblyOldDatesDetector` and `InvalidEmailShapeDetector`, bringing
it to 17; slice 3 (`WP-102`) adds `NumericValuesStoredAsTextDetector` and
`NearDuplicateCategoriesDetector`, bringing it to 19; slice 4 (`WP-104`) adds
`DuplicateNormalizedColumnNameDetector`, bringing it to 20. `DET-03` is
delivered in slices; the rest of `docs/detector-framework.md` §16 is not built
yet.
"""

from __future__ import annotations

from .completeness import (
    ExcessiveMissingValuesDetector,
    FullyEmptyRowsDetector,
    MissingLikelyIdentifierDetector,
)
from .consistency import (
    InconsistentBooleansDetector,
    InconsistentCapitalizationDetector,
    LeadingTrailingWhitespaceDetector,
    NearDuplicateCategoriesDetector,
    NumericValuesStoredAsTextDetector,
)
from .cross_field import LineTotalMismatchDetector
from .registry import register_detectors
from .security import PossiblePromptInjectionDetector
from .statistical import ExtremeOutliersDetector, SuspiciouslyConstantColumnDetector
from .structural import (
    DuplicateNormalizedColumnNameDetector,
    EmptyColumnDetector,
    ExactDuplicateRowsDetector,
)
from .validity import (
    FutureDatesDetector,
    ImplausiblyOldDatesDetector,
    InvalidEmailShapeDetector,
    InvalidPercentagesDetector,
    NegativeLikelyNonNegativeValuesDetector,
)

DETECTORS = register_detectors(
    [
        ExactDuplicateRowsDetector(),
        EmptyColumnDetector(),
        ExcessiveMissingValuesDetector(),
        MissingLikelyIdentifierDetector(),
        InconsistentCapitalizationDetector(),
        LeadingTrailingWhitespaceDetector(),
        FutureDatesDetector(),
        NegativeLikelyNonNegativeValuesDetector(),
        InvalidPercentagesDetector(),
        LineTotalMismatchDetector(),
        SuspiciouslyConstantColumnDetector(),
        ExtremeOutliersDetector(),
        PossiblePromptInjectionDetector(),
        FullyEmptyRowsDetector(),
        InconsistentBooleansDetector(),
        ImplausiblyOldDatesDetector(),
        InvalidEmailShapeDetector(),
        NumericValuesStoredAsTextDetector(),
        NearDuplicateCategoriesDetector(),
        DuplicateNormalizedColumnNameDetector(),
    ]
)
