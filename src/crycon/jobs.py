"""Parser job contract and one-job worker execution policy."""

from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol

from crycon.repository import Record


class ParserJobRepository(Protocol):
    def enqueue_job(
        self,
        job_type: str,
        query: str,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> Record: ...

    def get_job(self, job_id: int) -> Optional[Record]: ...

    def list_jobs(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> List[Record]: ...

    def claim_job(self, worker_id: str, stale_after_seconds: int = 300) -> Optional[Record]: ...

    def heartbeat_job(self, job_id: int, worker_id: str) -> bool: ...

    def complete_job(self, job_id: int, worker_id: str, result_count: int) -> bool: ...

    def fail_job(
        self,
        job_id: int,
        worker_id: str,
        error_text: str,
        retryable: bool,
    ) -> str | None: ...


class RetryableJobError(Exception):
    """Expected transient failure whose message is safe to store."""


@dataclass(frozen=True)
class WorkerOutcome:
    job_id: int
    status: str
    result_count: int = 0
    job_type: str = ""
    attempt_count: int = 0


def run_next_job(
    repository: ParserJobRepository,
    worker_id: str,
    handler: Callable[[Record], int],
    *,
    stale_after_seconds: int = 300,
) -> WorkerOutcome | None:
    """Claim and execute one job, preserving retry and ownership rules."""
    job = repository.claim_job(worker_id, stale_after_seconds)
    if job is None:
        return None

    job_id = int(job["id"])
    job_type = str(job.get("job_type") or "")
    attempt_count = int(job.get("attempt_count") or 0)
    try:
        result_count = max(0, int(handler(job)))
    except RetryableJobError as error:
        status = repository.fail_job(
            job_id, worker_id, str(error)[:1000], retryable=True
        )
        return WorkerOutcome(
            job_id, status or "lease_lost", job_type=job_type,
            attempt_count=attempt_count,
        )
    except Exception as error:
        # Unknown exception messages may contain secrets. Persist only the type,
        # mark the job terminal, then re-raise for worker supervision/logging.
        repository.fail_job(
            job_id, worker_id, type(error).__name__, retryable=False
        )
        raise

    if not repository.complete_job(job_id, worker_id, result_count):
        return WorkerOutcome(
            job_id, "lease_lost", result_count, job_type, attempt_count
        )
    return WorkerOutcome(job_id, "done", result_count, job_type, attempt_count)
