from collections import deque
from types import SimpleNamespace

from crycon.repository import CandidateRepository
from crycon.supabase_repository import SupabaseCandidateRepository
from tests.fakes import FakeCandidateRepository


class ScriptedSupabaseClient:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = []

    def table(self, name):
        self.calls.append(("table", name))
        return self

    def select(self, columns):
        self.calls.append(("select", columns))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.calls.append(("in", column, values))
        return self

    def order(self, column, **options):
        self.calls.append(("order", column, options))
        return self

    def limit(self, value):
        self.calls.append(("limit", value))
        return self

    def range(self, start, end):
        self.calls.append(("range", start, end))
        return self

    def execute(self):
        return SimpleNamespace(data=self.responses.popleft())


def _candidate_name(repository: CandidateRepository, candidate_id: int) -> str | None:
    candidate = repository.get_candidate(candidate_id)
    return candidate.get("main_username") if candidate else None


def test_fake_repository_satisfies_read_contract_without_database():
    repository = FakeCandidateRepository(
        candidates=[
            {"id": 1, "main_username": "alice", "overall_trust_score": 70},
            {"id": 2, "main_username": "bob", "overall_trust_score": 90},
        ],
        evidence=[
            {"id": 1, "candidate_id": 1, "confidence": 40},
            {"id": 2, "candidate_id": 1, "confidence": 80},
        ],
    )

    assert _candidate_name(repository, 1) == "alice"
    assert repository.list_top_candidate_ids() == [2, 1]
    assert [row["id"] for row in repository.list_evidence(1)] == [2, 1]
    assert repository.search_candidate_ids("ALI") == [1]
    assert repository.get_candidate(99) is None


def test_supabase_repository_translates_existing_reads_and_bounds_limits():
    client = ScriptedSupabaseClient([
        [{"id": 7, "main_username": "alice"}],
        [{"candidate_id": 7, "platform": "github"}],
        [{"candidate_id": 7, "contact_type": "email"}],
        [{"candidate_id": 7, "wallet_type": "evm"}],
        [{"candidate_id": 7, "confidence": 90}],
        [{"id": 7}, {"id": 8}],
    ])
    repository = SupabaseCandidateRepository(client)

    assert repository.get_candidate(7)["main_username"] == "alice"
    assert repository.list_profiles(7)[0]["platform"] == "github"
    assert repository.list_contacts(7)[0]["contact_type"] == "email"
    assert repository.list_wallets(7)[0]["wallet_type"] == "evm"
    assert repository.list_evidence(7, limit=500)[0]["confidence"] == 90
    assert repository.list_top_candidate_ids(limit=0) == [7, 8]
    assert ("limit", 100) in client.calls
    assert client.calls[-1] == ("limit", 1)


def test_supabase_repository_does_not_query_for_blank_search():
    client = ScriptedSupabaseClient([])
    repository = SupabaseCandidateRepository(client)

    assert repository.search_candidate_ids("   ") == []
    assert client.calls == []


def test_supabase_repository_batches_ids_and_paginates_deterministically():
    client = ScriptedSupabaseClient([
        [{"id": 8}, {"id": 7}],
        [{"id": 9}, {"id": 10}],
    ])
    repository = SupabaseCandidateRepository(client)

    assert [row["id"] for row in repository.get_candidates([7, 8, 7])] == [7, 8]
    assert [row["id"] for row in repository.list_candidates(2, offset=4)] == [9, 10]
    assert ("in", "id", [7, 8]) in client.calls
    assert client.calls[-1] == ("range", 4, 5)
