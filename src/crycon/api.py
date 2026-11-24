"""FastAPI application with repository dependency injection."""

import secrets
from pathlib import Path as FilePath
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Response, status
from fastapi.staticfiles import StaticFiles

from crycon.api_models import (
    CandidateDetail,
    CandidatePage,
    EvidenceResults,
    Health,
    JobStatus,
    ParserJob,
    ParserJobPage,
    SearchResults,
)
from crycon.jobs import ParserJobRepository
from crycon.job_payloads import JobPayload, serialize_job_payload
from crycon.repository import CandidateRepository
from crycon.supabase_repository import SupabaseCandidateRepository
from crycon.supabase_jobs import SupabaseParserJobRepository
from crycon.telegram_auth import parse_allowed_user_ids, telegram_user_id


def create_app(
    repository: CandidateRepository | None = None,
    job_repository: ParserJobRepository | None = None,
    admin_api_key: str | None = None,
    *,
    telegram_token: str | None = None,
    telegram_allowed_ids: frozenset[int] = frozenset(),
) -> FastAPI:
    app = FastAPI(
        title="Crycon API",
        version="0.1.0",
        description="Public Web3 evidence reads and durable parser jobs API.",
    )
    app.state.candidate_repository = repository
    app.state.parser_job_repository = job_repository
    app.state.supabase_client = None
    app.state.admin_api_key = admin_api_key

    def get_client():
        if app.state.supabase_client is None:
            from db_supabase import get_supabase_client

            app.state.supabase_client = get_supabase_client()
        return app.state.supabase_client

    def require_candidate_access(
        response: Response,
        init_data: Annotated[str, Header(alias="X-Telegram-Init-Data")] = "",
    ) -> None:
        if telegram_token is None:
            return
        response.headers["Cache-Control"] = "private, no-store"
        user_id = telegram_user_id(init_data, telegram_token)
        if user_id is None:
            raise HTTPException(status_code=401, detail="Open Crycon from Telegram")
        if telegram_allowed_ids and user_id not in telegram_allowed_ids:
            raise HTTPException(status_code=403, detail="Telegram account has no access")

    def get_repository() -> CandidateRepository:
        current = app.state.candidate_repository
        if current is None:
            # Keep configuration and credentials lazy: /health and imports work
            # without a developer .env or a live Supabase connection.
            current = SupabaseCandidateRepository(get_client())
            app.state.candidate_repository = current
        return current

    def get_job_repository() -> ParserJobRepository:
        current = app.state.parser_job_repository
        if current is None:
            current = SupabaseParserJobRepository(get_client())
            app.state.parser_job_repository = current
        return current

    def require_job_admin(
        api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> None:
        expected = app.state.admin_api_key
        if expected is None:
            from crycon.config import load_settings

            expected = load_settings().text("CRYCON_ADMIN_API_KEY")
        if not expected:
            raise HTTPException(status_code=503, detail="Job administration is disabled")
        if api_key is None or not secrets.compare_digest(api_key, expected):
            raise HTTPException(status_code=401, detail="Invalid API key")

    def get_candidate_repository(
        _: Annotated[None, Depends(require_candidate_access)],
    ) -> CandidateRepository:
        return get_repository()

    Repository = Annotated[CandidateRepository, Depends(get_candidate_repository)]
    JobRepository = Annotated[ParserJobRepository, Depends(get_job_repository)]
    JobAdmin = Annotated[None, Depends(require_job_admin)]

    @app.get("/health", response_model=Health, tags=["system"])
    def health() -> Health:
        """Liveness only; database readiness is intentionally separate."""
        return Health(status="ok")

    @app.get("/ready", response_model=Health, tags=["system"])
    def readiness() -> Health:
        try:
            # Resolve storage inside the guarded readiness boundary. FastAPI
            # dependencies run before the endpoint body, so injecting Repository
            # here would turn missing credentials into an unhandled HTTP 500.
            ready = get_repository().ping()
        except Exception:
            ready = False
        if not ready:
            raise HTTPException(status_code=503, detail="Storage is not ready")
        return Health(status="ready")

    @app.get("/candidates", response_model=CandidatePage, tags=["candidates"])
    def list_candidates(
        repository: Repository,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> CandidatePage:
        rows = repository.list_candidates(limit=limit + 1, offset=offset)
        has_more = len(rows) > limit
        return CandidatePage(
            items=rows[:limit],
            limit=limit,
            offset=offset,
            next_offset=offset + limit if has_more else None,
        )

    @app.get("/search", response_model=SearchResults, tags=["candidates"])
    def search_candidates(
        repository: Repository,
        q: Annotated[str, Query(min_length=1, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> SearchResults:
        query = q.strip()
        if not query:
            raise HTTPException(status_code=422, detail="q must not be blank")
        candidate_ids = repository.search_candidate_ids(query, limit=limit)
        return SearchResults(
            query=query,
            items=repository.get_candidates(candidate_ids),
        )

    @app.get(
        "/candidates/{candidate_id}",
        response_model=CandidateDetail,
        tags=["candidates"],
    )
    def get_candidate(
        candidate_id: Annotated[int, Path(ge=1)],
        repository: Repository,
    ) -> CandidateDetail:
        candidate = repository.get_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return CandidateDetail(
            candidate=candidate,
            profiles=repository.list_profiles(candidate_id),
            contacts=repository.list_contacts(candidate_id),
            wallets=repository.list_wallets(candidate_id),
        )

    @app.get(
        "/candidates/{candidate_id}/evidence",
        response_model=EvidenceResults,
        tags=["candidates"],
    )
    def get_candidate_evidence(
        candidate_id: Annotated[int, Path(ge=1)],
        repository: Repository,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> EvidenceResults:
        if repository.get_candidate(candidate_id) is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return EvidenceResults(
            candidate_id=candidate_id,
            items=repository.list_evidence(candidate_id, limit=limit),
        )

    @app.post(
        "/jobs",
        response_model=ParserJob,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["jobs"],
    )
    def enqueue_job(
        _authorization: JobAdmin,
        payload: JobPayload,
        repository: JobRepository,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", min_length=1, max_length=200),
        ],
    ) -> ParserJob:
        return ParserJob.model_validate(repository.enqueue_job(
            job_type=payload.job_type,
            query=serialize_job_payload(payload),
            idempotency_key=idempotency_key.strip(),
            max_attempts=payload.max_attempts,
        ))

    @app.get("/jobs", response_model=ParserJobPage, tags=["jobs"])
    def list_jobs(
        _authorization: JobAdmin,
        repository: JobRepository,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
        job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    ) -> ParserJobPage:
        rows = repository.list_jobs(
            limit=limit + 1,
            offset=offset,
            status=job_status,
        )
        has_more = len(rows) > limit
        return ParserJobPage(
            items=rows[:limit],
            limit=limit,
            offset=offset,
            next_offset=offset + limit if has_more else None,
        )

    @app.get("/jobs/{job_id}", response_model=ParserJob, tags=["jobs"])
    def get_job(
        job_id: Annotated[int, Path(ge=1)],
        _authorization: JobAdmin,
        repository: JobRepository,
    ) -> ParserJob:
        job = repository.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Parser job not found")
        return ParserJob.model_validate(job)

    miniapp = FilePath(__file__).resolve().parents[2] / "miniapp"
    if not (miniapp / "index.html").is_file():
        miniapp = FilePath.cwd() / "miniapp"
    if (miniapp / "index.html").is_file():
        app.mount("/miniapp", StaticFiles(directory=miniapp, html=True), name="miniapp")
    return app


def create_miniapp() -> FastAPI:
    from crycon.config import load_settings

    settings = load_settings()
    return create_app(
        admin_api_key="",
        telegram_token=settings.require("TELEGRAM_BOT_TOKEN"),
        telegram_allowed_ids=parse_allowed_user_ids(settings.text("TELEGRAM_ALLOWED_USER_IDS")),
    )


app = create_app()
