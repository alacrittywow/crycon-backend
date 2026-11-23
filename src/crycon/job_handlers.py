"""Typed routing from durable jobs to existing application services."""

from typing import Any, Callable, Dict

from crycon.job_payloads import (
    ContactEnrichmentPayload,
    DiscoveryPayload,
    IdentityResolutionPayload,
    ScoreRecalculationPayload,
    WalletEnrichmentPayload,
    parse_job_payload,
)
from crycon.jobs import ParserJobRepository
from crycon.repository import Record


Handler = Callable[[Any, Record], int]


class JobHandlerRegistry:
    def __init__(self, handlers: Dict[str, Handler]) -> None:
        self._handlers = dict(handlers)

    @property
    def supported_types(self) -> set[str]:
        return set(self._handlers)

    def handle(self, job: Record) -> int:
        job_type = str(job.get("job_type") or "")
        handler = self._handlers.get(job_type)
        if handler is None:
            raise ValueError(f"unsupported job_type: {job_type}")
        payload = parse_job_payload(job_type, job.get("query"))
        return max(0, int(handler(payload, job)))


def build_job_handler_registry(
    client,
    jobs: ParserJobRepository,
    worker_id: str,
) -> JobHandlerRegistry:
    """Connect typed payloads to legacy services without subprocesses."""

    def heartbeat(job_id: int) -> None:
        if not jobs.heartbeat_job(job_id, worker_id):
            raise RuntimeError("parser job lease lost")

    def discovery(payload: DiscoveryPayload, job: Record) -> int:
        from parse_web3_to_supabase import KEYWORDS, run_discovery

        job_id = int(job["id"])
        return run_discovery(
            client,
            payload.keywords or list(KEYWORDS),
            heartbeat=lambda: jobs.heartbeat_job(job_id, worker_id),
        )

    def contact_enrichment(payload: ContactEnrichmentPayload, _job: Record) -> int:
        from enrich_to_supabase import enrich_candidate, get_candidate_by_id

        candidate = get_candidate_by_id(client, payload.candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {payload.candidate_id}")
        stats = enrich_candidate(client, candidate)
        return sum(int(value) for value in stats.values())

    def wallet_enrichment(payload: WalletEnrichmentPayload, _job: Record) -> int:
        from wallet_deep_enrich import deep_enrich_candidate, fetch_candidate_by_id

        candidate = fetch_candidate_by_id(client, payload.candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {payload.candidate_id}")
        return deep_enrich_candidate(client, candidate)

    def score_recalculation(payload: ScoreRecalculationPayload, _job: Record) -> int:
        from recalculate_scores import fetch_candidate_by_id, recalculate_candidate

        candidate = fetch_candidate_by_id(client, payload.candidate_id)
        if not candidate:
            raise ValueError(f"candidate not found: {payload.candidate_id}")
        recalculate_candidate(client, candidate)
        return 1

    def identity_resolution(payload: IdentityResolutionPayload, _job: Record) -> int:
        from recalculate_scores import fetch_candidate_by_id, recalculate_candidate
        from resolve_identity import resolve_identity

        candidate_id = resolve_identity(payload.identity, client=client)
        if candidate_id is None:
            return 0
        candidate = fetch_candidate_by_id(client, candidate_id)
        if candidate:
            recalculate_candidate(client, candidate)
        return 1

    def guarded(handler: Handler) -> Handler:
        def execute(payload: Any, job: Record) -> int:
            job_id = int(job["id"])
            heartbeat(job_id)
            result = handler(payload, job)
            heartbeat(job_id)
            return result
        return execute

    return JobHandlerRegistry({
        "discovery": guarded(discovery),
        "contact_enrichment": guarded(contact_enrichment),
        "wallet_enrichment": guarded(wallet_enrichment),
        "score_recalculation": guarded(score_recalculation),
        "identity_resolution": guarded(identity_resolution),
    })
