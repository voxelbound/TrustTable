"""Staged-upload routes (`UX-02`, `docs/decision-log.md` D-068,
`docs/api-specification.md` §7).

Choosing a file stages its bytes temporarily and inspects them; nothing is
analysed until Run, which analyses exactly the staged bytes. The opaque
reference travels only in JSON request bodies (never a URL), is never logged
here, and every response is `Cache-Control: no-store`. The validation rules are
the shared ones in `trusttable_backend.ingestion`, so direct upload and staging
cannot drift apart.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from trusttable_backend.analysis.history import find_previous_analysis_notice
from trusttable_backend.api.v1.analyses import get_analysis_store, start_analysis_from_content
from trusttable_backend.errors import AppError
from trusttable_backend.ingestion import (
    CSV_EXTENSION,
    XLSX_EXTENSION,
    plan_ingestion,
    read_upload_content,
    validate_upload_name,
)
from trusttable_backend.persistence import SqlStagingStore, StagedUpload, StagingFullError
from trusttable_backend.schemas.analysis import UploadAnalysisResponse
from trusttable_backend.schemas.history import PreviousAnalysisNoticeResponse
from trusttable_backend.schemas.staging import (
    StagedCheckGroup,
    StagedNotice,
    StagedProblem,
    StagedShape,
    StagedUploadInspectRequest,
    StagedUploadReference,
    StagedUploadResponse,
    StagedUploadRunRequest,
    StagedWorksheet,
)
from trusttable_backend.staging_inspection import FileInspection, check_groups, inspect_content

router = APIRouter(tags=["staged-uploads"])

_NO_STORE = "no-store"
_FORMAT_FOR_EXTENSION = {CSV_EXTENSION: "csv", XLSX_EXTENSION: "xlsx"}
_EXTENSION_FOR_FORMAT = {"csv": CSV_EXTENSION, "xlsx": XLSX_EXTENSION}


def get_staging_store(request: Request) -> SqlStagingStore:
    """The current app's `SqlStagingStore` (created by `main.create_app`)."""
    store: SqlStagingStore = request.app.state.staging_store
    return store


def _unavailable() -> AppError:
    # One answer for unknown, malformed, expired, consumed and corrupted
    # references, so the response reveals nothing about which it was.
    return AppError(
        "STAGED_UPLOAD_UNAVAILABLE",
        "This file is no longer available. Chosen files are kept only briefly; "
        "choose the file again.",
        status_code=410,
        details={},
    )


def _resource(
    *,
    staging_ref: str | None,
    staged: StagedUpload | None,
    filename: str,
    file_format: str,
    byte_size: int,
    inspection: FileInspection,
    previously_analysed: PreviousAnalysisNoticeResponse | None = None,
) -> StagedUploadResponse:
    return StagedUploadResponse(
        staging_ref=staging_ref,
        expires_at=staged.expires_at if staged is not None else None,
        filename=filename,
        format="xlsx" if file_format == "xlsx" else "csv",
        byte_size=byte_size,
        worksheets=(
            [StagedWorksheet(name=w.name, visible=w.visible) for w in inspection.worksheets]
            if inspection.worksheets is not None
            else None
        ),
        selected_worksheet=inspection.selected_worksheet,
        shape=(
            StagedShape(
                row_count=inspection.shape.row_count, column_count=inspection.shape.column_count
            )
            if inspection.shape is not None
            else None
        ),
        problems=[StagedProblem(code=p.code, message=p.message) for p in inspection.problems],
        notices=[
            StagedNotice(code=n.code, message=n.message, count=n.count) for n in inspection.notices
        ],
        checks=[StagedCheckGroup(title=g.title, description=g.description) for g in check_groups()],
        can_run=staging_ref is not None and inspection.can_run,
        previously_analysed=previously_analysed,
    )


def _previous_notice(
    request: Request, *, content_sha256: str, filename: str
) -> PreviousAnalysisNoticeResponse | None:
    """The "analysed before" notice for a staged file (`UX-03`, D-069): an
    indexed lookup over the analyses that exist now. The digest goes in and
    never comes out."""
    notice = find_previous_analysis_notice(
        get_analysis_store(request), content_sha256=content_sha256, filename=filename
    )
    if notice is None:
        return None
    return PreviousAnalysisNoticeResponse(
        kind=notice.kind.value,
        count=notice.count,
        latest_analysis_id=notice.latest.analysis_id,
        latest_analysed_at=notice.latest.completed_at or notice.latest.created_at,
        latest_filename=notice.latest.original_filename,
    )


@router.post("/staged-uploads", response_model=StagedUploadResponse, status_code=201)
async def post_staged_upload(
    file: UploadFile, request: Request, response: Response
) -> StagedUploadResponse:
    """Stage a chosen file and inspect it. Starts no analysis.

    `201` when the file was stored; `200` with `staging_ref: null` when the
    file itself cannot be read, in which case nothing is stored.
    """
    response.headers["Cache-Control"] = _NO_STORE
    filename, extension = validate_upload_name(file.filename)
    content = await read_upload_content(file)
    file_format = _FORMAT_FOR_EXTENSION[extension]
    inspection = await run_in_threadpool(inspect_content, content, extension, None)
    if inspection.file_unreadable:
        response.status_code = 200
        return _resource(
            staging_ref=None,
            staged=None,
            filename=filename,
            file_format=file_format,
            byte_size=len(content),
            inspection=inspection,
        )
    store = get_staging_store(request)
    try:
        reference, staged = await run_in_threadpool(
            lambda: store.stage(filename=filename, file_format=file_format, content=content)
        )
    except StagingFullError as exc:
        raise AppError(
            "STAGING_FULL",
            "Several files are already waiting to be analyzed. Finish or discard one, "
            "or wait for them to expire.",
            status_code=409,
            details={"ttl_minutes": int(store.ttl.total_seconds() // 60)},
        ) from exc
    return _resource(
        staging_ref=reference,
        staged=staged,
        filename=filename,
        file_format=file_format,
        byte_size=staged.byte_size,
        inspection=inspection,
        previously_analysed=await run_in_threadpool(
            lambda: _previous_notice(
                request, content_sha256=staged.content_sha256, filename=filename
            )
        ),
    )


@router.post("/staged-uploads/inspect", response_model=StagedUploadResponse)
def post_staged_upload_inspect(
    body: StagedUploadInspectRequest, request: Request, response: Response
) -> StagedUploadResponse:
    """Inspect a staged file again, optionally for one worksheet. Read-only:
    it does not extend the expiry. `POST` only keeps the reference out of the
    URL."""
    response.headers["Cache-Control"] = _NO_STORE
    staged = get_staging_store(request).peek(body.staging_ref)
    if staged is None:
        raise _unavailable()
    inspection = inspect_content(
        staged.content, _EXTENSION_FOR_FORMAT[staged.format], body.worksheet or None
    )
    return _resource(
        staging_ref=body.staging_ref,
        staged=staged,
        filename=staged.filename,
        file_format=staged.format,
        byte_size=staged.byte_size,
        inspection=inspection,
        previously_analysed=_previous_notice(
            request, content_sha256=staged.content_sha256, filename=staged.filename
        ),
    )


@router.post("/staged-uploads/run", response_model=UploadAnalysisResponse, status_code=202)
def post_staged_upload_run(
    body: StagedUploadRunRequest, request: Request, response: Response
) -> UploadAnalysisResponse:
    """Run the analysis over exactly the staged bytes.

    Order: load; verify the stored bytes against the digest recorded at
    staging; validate through the shared ingestion path (a refusal here does
    not spend the reference); consume atomically; create the analysis from the
    consumed bytes. Of any number of concurrent Runs exactly one consumes the
    row, the others get `410`. If creating the analysis fails after the row was
    consumed, the reference stays spent and the file must be chosen again.
    """
    response.headers["Cache-Control"] = _NO_STORE
    store = get_staging_store(request)
    staged = store.peek(body.staging_ref)
    if staged is None:
        raise _unavailable()
    if hashlib.sha256(staged.content).hexdigest() != staged.content_sha256:
        store.discard(body.staging_ref)
        raise _unavailable()

    extension = _EXTENSION_FOR_FORMAT[staged.format]
    plan = plan_ingestion(staged.content, extension, body.worksheet or None)
    inspection = inspect_content(staged.content, extension, plan.selected_worksheet)
    if inspection.problems:
        raise AppError(
            "STAGED_UPLOAD_NOT_RUNNABLE",
            "This file cannot be analyzed as chosen.",
            status_code=400,
            details={
                "problems": [{"code": p.code, "message": p.message} for p in inspection.problems]
            },
        )

    consumed = store.consume(body.staging_ref, content_sha256=staged.content_sha256)
    if consumed is None:
        raise _unavailable()
    if hashlib.sha256(consumed.content).hexdigest() != staged.content_sha256:
        raise _unavailable()
    return start_analysis_from_content(
        request,
        content=consumed.content,
        original_filename=consumed.filename,
        dataset_format=plan.dataset_format,
        selected_worksheet=plan.selected_worksheet,
    )


@router.post("/staged-uploads/discard", status_code=204)
def post_staged_upload_discard(body: StagedUploadReference, request: Request) -> Response:
    """Discard a staged file. Always `204`, whether or not it existed."""
    get_staging_store(request).discard(body.staging_ref)
    return Response(status_code=204, headers={"Cache-Control": _NO_STORE})
