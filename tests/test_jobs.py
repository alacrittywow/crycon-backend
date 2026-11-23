import pytest

from crycon.jobs import RetryableJobError, run_next_job
from tests.fakes import FakeParserJobRepository


def test_enqueue_is_idempotent_and_successful_worker_completes_job():
    repository = FakeParserJobRepository()
    first = repository.enqueue_job("discovery", "validator", "same-key")
    duplicate = repository.enqueue_job("discovery", "validator", "same-key")

    outcome = run_next_job(repository, "worker-a", lambda job: 4)

    assert first["id"] == duplicate["id"]
    assert len(repository.jobs) == 1
    assert outcome.status == "done"
    assert outcome.result_count == 4
    assert outcome.job_type == "discovery"
    assert outcome.attempt_count == 1
    assert repository.get_job(first["id"])["status"] == "done"


def test_retryable_error_requeues_until_attempts_are_exhausted():
    repository = FakeParserJobRepository()
    job = repository.enqueue_job("discovery", "validator", "retry-key", max_attempts=2)

    def temporary_failure(_job):
        raise RetryableJobError("rate limited")

    first = run_next_job(repository, "worker-a", temporary_failure)
    second = run_next_job(repository, "worker-b", temporary_failure)

    assert first.status == "new"
    assert second.status == "failed"
    assert repository.get_job(job["id"])["attempt_count"] == 2
    assert run_next_job(repository, "worker-c", temporary_failure) is None


def test_unexpected_error_is_terminal_and_only_type_is_persisted():
    repository = FakeParserJobRepository()
    job = repository.enqueue_job("discovery", "validator", "secret-key")

    def unexpected(_job):
        raise RuntimeError("Bearer super-secret-value")

    with pytest.raises(RuntimeError, match="super-secret"):
        run_next_job(repository, "worker-a", unexpected)

    stored = repository.get_job(job["id"])
    assert stored["status"] == "failed"
    assert stored["error_text"] == "RuntimeError"
    assert "secret" not in stored["error_text"]
