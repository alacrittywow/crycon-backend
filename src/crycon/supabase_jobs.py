"""Supabase adapter for durable parser jobs."""

from typing import Any, List

from crycon.repository import Record


class SupabaseParserJobRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    def enqueue_job(
        self,
        job_type: str,
        query: str,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> Record:
        response = self._client.rpc("enqueue_parser_job", {
            "p_job_type": job_type,
            "p_query": query,
            "p_idempotency_key": idempotency_key,
            "p_max_attempts": max_attempts,
        }).execute()
        if not response.data:
            raise RuntimeError("enqueue_parser_job returned no result; apply migration 005")
        return response.data[0]

    def get_job(self, job_id: int) -> Record | None:
        response = (
            self._client.table("parser_jobs").select("*")
            .eq("id", job_id).limit(1).execute()
        )
        return response.data[0] if response.data else None

    def list_jobs(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> List[Record]:
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        request = self._client.table("parser_jobs").select("*")
        if status:
            request = request.eq("status", status)
        response = (
            request.order("created_at", desc=True).order("id", desc=True)
            .range(offset, offset + limit - 1).execute()
        )
        return response.data or []

    def claim_job(self, worker_id: str, stale_after_seconds: int = 300) -> Record | None:
        response = self._client.rpc("claim_parser_job", {
            "p_worker_id": worker_id,
            "p_stale_after_seconds": stale_after_seconds,
        }).execute()
        return response.data[0] if response.data else None

    def heartbeat_job(self, job_id: int, worker_id: str) -> bool:
        response = self._client.rpc("heartbeat_parser_job", {
            "p_job_id": job_id,
            "p_worker_id": worker_id,
        }).execute()
        return bool(response.data)

    def complete_job(self, job_id: int, worker_id: str, result_count: int) -> bool:
        response = self._client.rpc("complete_parser_job", {
            "p_job_id": job_id,
            "p_worker_id": worker_id,
            "p_result_count": result_count,
        }).execute()
        return bool(response.data)

    def fail_job(
        self,
        job_id: int,
        worker_id: str,
        error_text: str,
        retryable: bool,
    ) -> str | None:
        response = self._client.rpc("fail_parser_job", {
            "p_job_id": job_id,
            "p_worker_id": worker_id,
            "p_error_text": error_text,
            "p_retryable": retryable,
        }).execute()
        return response.data
