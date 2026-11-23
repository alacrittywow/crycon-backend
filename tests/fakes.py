"""Reusable in-memory adapters for application and API tests."""

from collections import defaultdict
from typing import Iterable, Sequence

from crycon.repository import Record


class FakeCandidateRepository:
    def __init__(
        self,
        candidates: Iterable[Record] = (),
        profiles: Iterable[Record] = (),
        contacts: Iterable[Record] = (),
        wallets: Iterable[Record] = (),
        evidence: Iterable[Record] = (),
    ) -> None:
        self.candidates = {int(row["id"]): dict(row) for row in candidates}
        self.related = defaultdict(list)
        for table, rows in (
            ("profiles", profiles),
            ("contacts", contacts),
            ("wallets", wallets),
            ("evidence", evidence),
        ):
            for row in rows:
                self.related[(table, int(row["candidate_id"]))].append(dict(row))

    def ping(self) -> bool:
        return True

    def get_candidate(self, candidate_id: int) -> Record | None:
        candidate = self.candidates.get(candidate_id)
        return dict(candidate) if candidate else None

    def get_candidates(self, candidate_ids: Sequence[int]) -> list[Record]:
        return [
            dict(self.candidates[candidate_id])
            for candidate_id in dict.fromkeys(int(value) for value in candidate_ids)
            if candidate_id in self.candidates
        ]

    def list_candidates(self, limit: int = 20, offset: int = 0) -> list[Record]:
        ordered = sorted(
            self.candidates.values(),
            key=lambda row: (-int(row.get("overall_trust_score") or 0), int(row["id"])),
        )
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 100))
        return [dict(row) for row in ordered[offset:offset + limit]]

    def _rows(self, table: str, candidate_id: int) -> list[Record]:
        return [dict(row) for row in self.related[(table, candidate_id)]]

    def list_profiles(self, candidate_id: int) -> list[Record]:
        return self._rows("profiles", candidate_id)

    def list_contacts(self, candidate_id: int) -> list[Record]:
        return self._rows("contacts", candidate_id)

    def list_wallets(self, candidate_id: int) -> list[Record]:
        return self._rows("wallets", candidate_id)

    def list_evidence(self, candidate_id: int, limit: int = 10) -> list[Record]:
        rows = sorted(
            self._rows("evidence", candidate_id),
            key=lambda row: int(row.get("confidence") or 0),
            reverse=True,
        )
        return rows[:max(1, min(int(limit), 100))]

    def list_top_candidate_ids(self, limit: int = 20) -> list[int]:
        ordered = sorted(
            self.candidates.values(),
            key=lambda row: (-int(row.get("overall_trust_score") or 0), int(row["id"])),
        )
        return [int(row["id"]) for row in ordered[:max(1, min(int(limit), 100))]]

    def search_candidate_ids(self, query: str, limit: int = 10) -> list[int]:
        query = query.strip().lower()
        if not query:
            return []
        matches = []
        for candidate_id, candidate in self.candidates.items():
            values = (candidate.get("main_username"), candidate.get("display_name"))
            if any(query in str(value or "").lower() for value in values):
                matches.append(candidate_id)
        return matches[:max(1, min(int(limit), 100))]


class FakeParserJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[int, Record] = {}
        self.idempotency: dict[tuple[str, str], int] = {}
        self.next_id = 1

    def enqueue_job(
        self,
        job_type: str,
        query: str,
        idempotency_key: str,
        max_attempts: int = 3,
    ) -> Record:
        key = (job_type, idempotency_key)
        if key in self.idempotency:
            return dict(self.jobs[self.idempotency[key]])
        job = {
            "id": self.next_id,
            "job_type": job_type,
            "query": query,
            "status": "new",
            "result_count": 0,
            "idempotency_key": idempotency_key,
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "locked_by": None,
            "error_text": None,
        }
        self.jobs[self.next_id] = job
        self.idempotency[key] = self.next_id
        self.next_id += 1
        return dict(job)

    def get_job(self, job_id: int) -> Record | None:
        job = self.jobs.get(job_id)
        return dict(job) if job else None

    def list_jobs(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[Record]:
        jobs = sorted(self.jobs.values(), key=lambda job: int(job["id"]), reverse=True)
        if status:
            jobs = [job for job in jobs if job["status"] == status]
        return [dict(job) for job in jobs[offset:offset + limit]]

    def claim_job(self, worker_id: str, stale_after_seconds: int = 300) -> Record | None:
        for job_id in sorted(self.jobs):
            job = self.jobs[job_id]
            if job["status"] == "new" and job["attempt_count"] < job["max_attempts"]:
                job["status"] = "running"
                job["attempt_count"] += 1
                job["locked_by"] = worker_id
                return dict(job)
        return None

    def heartbeat_job(self, job_id: int, worker_id: str) -> bool:
        job = self.jobs.get(job_id)
        return bool(job and job["status"] == "running" and job["locked_by"] == worker_id)

    def complete_job(self, job_id: int, worker_id: str, result_count: int) -> bool:
        job = self.jobs.get(job_id)
        if not job or job["status"] != "running" or job["locked_by"] != worker_id:
            return False
        job.update(status="done", result_count=result_count, locked_by=None, error_text=None)
        return True

    def fail_job(
        self,
        job_id: int,
        worker_id: str,
        error_text: str,
        retryable: bool,
    ) -> str | None:
        job = self.jobs.get(job_id)
        if not job or job["status"] != "running" or job["locked_by"] != worker_id:
            return None
        status = "new" if retryable and job["attempt_count"] < job["max_attempts"] else "failed"
        job.update(status=status, locked_by=None, error_text=error_text)
        return status
