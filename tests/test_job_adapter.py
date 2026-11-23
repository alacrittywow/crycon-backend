from collections import deque
from types import SimpleNamespace

from crycon.supabase_jobs import SupabaseParserJobRepository


class FakeJobClient:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = []

    def rpc(self, name, params):
        self.calls.append(("rpc", name, params))
        return self

    def table(self, name):
        self.calls.append(("table", name))
        return self

    def select(self, columns):
        self.calls.append(("select", columns))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def limit(self, value):
        self.calls.append(("limit", value))
        return self

    def order(self, column, **options):
        self.calls.append(("order", column, options))
        return self

    def range(self, start, end):
        self.calls.append(("range", start, end))
        return self

    def execute(self):
        return SimpleNamespace(data=self.responses.popleft())


def test_job_adapter_uses_lifecycle_rpcs_and_bounded_reads():
    client = FakeJobClient([
        [{"id": 1, "status": "new"}],
        [{"id": 1, "status": "new"}],
        [{"id": 1, "status": "running"}],
        True,
        True,
        "new",
        [{"id": 1, "status": "new"}],
    ])
    repository = SupabaseParserJobRepository(client)

    assert repository.enqueue_job("discovery", "validator", "key-1")["id"] == 1
    assert repository.get_job(1)["status"] == "new"
    assert repository.claim_job("worker-a")["status"] == "running"
    assert repository.heartbeat_job(1, "worker-a") is True
    assert repository.complete_job(1, "worker-a", 3) is True
    assert repository.fail_job(1, "worker-a", "temporary", True) == "new"
    assert repository.list_jobs(limit=500, offset=-5, status="new")[0]["id"] == 1

    rpc_names = [call[1] for call in client.calls if call[0] == "rpc"]
    assert rpc_names == [
        "enqueue_parser_job",
        "claim_parser_job",
        "heartbeat_parser_job",
        "complete_parser_job",
        "fail_parser_job",
    ]
    assert ("range", 0, 99) in client.calls
