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

Eight detectors exist so far — the two structural detectors (`WP-014`),
the two completeness detectors (`WP-015`), the two consistency detectors
(`WP-016`), and the two validity detectors (`WP-017`). The remaining
`DET-02` detectors and `DET-SEC-01` are later packages that will extend
this list additively.
"""

from __future__ import annotations

from .completeness import ExcessiveMissingValuesDetector, MissingLikelyIdentifierDetector
from .consistency import InconsistentCapitalizationDetector, LeadingTrailingWhitespaceDetector
from .registry import register_detectors
from .structural import EmptyColumnDetector, ExactDuplicateRowsDetector
from .validity import FutureDatesDetector, NegativeLikelyNonNegativeValuesDetector

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
    ]
)
