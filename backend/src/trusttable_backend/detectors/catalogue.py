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

Only `ExactDuplicateRowsDetector` and `EmptyColumnDetector` exist so far
— the remaining `DET-02` detectors and `DET-SEC-01` are later packages
that will extend this list additively.
"""

from __future__ import annotations

from .registry import register_detectors
from .structural import EmptyColumnDetector, ExactDuplicateRowsDetector

DETECTORS = register_detectors(
    [
        ExactDuplicateRowsDetector(),
        EmptyColumnDetector(),
    ]
)
