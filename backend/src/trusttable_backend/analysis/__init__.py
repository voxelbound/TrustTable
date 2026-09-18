"""In-memory analysis orchestration (`API-01`, enabling slice).

Framework-independent: no FastAPI/SQLAlchemy import. See `service.py` for
the full engine and `docs/architecture.md` §3 for this module's layer
placement ("Application services").
"""

from __future__ import annotations

from .service import (
    Analysis,
    AnalysisFailure,
    AnalysisNotFoundError,
    AnalysisNotReadyError,
    AnalysisState,
    AnalysisStore,
    ContextFieldNotEditableError,
    ContextVersionConflictError,
    FindingNotFoundError,
    QuestionNotFoundError,
    RowNotInFindingError,
    answer_guided_question,
    cancel_analysis,
    confirm_context_fields,
    create_analysis,
    create_analysis_from_upload,
    finalize_context,
    get_finding,
    get_finding_evidence,
    get_finding_row_context,
    get_findings,
    get_guided_questions,
    get_or_infer_context,
    get_profile,
    get_status,
    run_analysis,
)

__all__ = [
    "Analysis",
    "AnalysisFailure",
    "AnalysisNotFoundError",
    "AnalysisNotReadyError",
    "AnalysisState",
    "AnalysisStore",
    "ContextFieldNotEditableError",
    "ContextVersionConflictError",
    "FindingNotFoundError",
    "QuestionNotFoundError",
    "RowNotInFindingError",
    "answer_guided_question",
    "cancel_analysis",
    "confirm_context_fields",
    "create_analysis",
    "create_analysis_from_upload",
    "finalize_context",
    "get_finding",
    "get_finding_evidence",
    "get_finding_row_context",
    "get_findings",
    "get_guided_questions",
    "get_or_infer_context",
    "get_profile",
    "get_status",
    "run_analysis",
]
