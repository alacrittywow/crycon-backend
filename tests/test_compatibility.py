"""Adapter/CLI smoke tests with fake database responses; no services required."""
import importlib
import runpy
import socket
import sys
from collections import deque
from types import SimpleNamespace

import pytest

from crycon.scoring import calculate_enrichment_scores, calculate_scores


class FakeClient:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.updates = []

    def table(self, table):
        self.table_name = table
        return self

    def select(self, *args): return self
    def eq(self, *args): return self
    def limit(self, *args): return self

    def update(self, payload):
        self.updates.append((self.table_name, payload))
        return self

    def execute(self):
        return SimpleNamespace(data=self.responses.popleft())


class FakeSearchClient(FakeClient):
    def __init__(self, responses):
        super().__init__(responses)
        self.rpc_calls = []

    def select(self, *args): return self
    def or_(self, *args): return self
    def ilike(self, *args): return self

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return self


def test_enrichment_adapter_only_persists_score_columns():
    from enrich_to_supabase import update_candidate_scores
    candidate = {'id': 1, 'relevance_score': 40}
    contacts = [{'contact_type': 'email', 'value': 'alice@personal.dev', 'confidence': 80}]
    client = FakeClient([[candidate], [], contacts, [], []])
    update_candidate_scores(client, 1)
    assert client.updates == [('candidates', calculate_enrichment_scores(candidate, [], contacts, []))]
    assert not client.responses


def test_discovery_adapter_uses_one_atomic_rpc():
    from db_supabase import insert_candidate_with_profile_and_evidence

    client = FakeSearchClient([[
        {
            "result_status": "created",
            "candidate_id": 11,
            "profile_id": 22,
            "evidence_id": 33,
        }
    ]])
    result = insert_candidate_with_profile_and_evidence(client, {
        "source": "github",
        "username": "alice",
        "bio": "Solana validator",
        "matched_keyword": "validator",
    })
    assert result == {
        "status": "created",
        "candidate_id": 11,
        "profile_id": 22,
        "evidence_id": 33,
        "relevance_score": 50,
    }
    assert client.rpc_calls[0][0] == "create_discovered_candidate"
    assert len(client.rpc_calls) == 1


def test_recalculation_adapter_breakdown_is_not_written_to_database():
    from recalculate_scores import recalculate_candidate
    candidate = {'id': 1, 'relevance_score': 40}
    client = FakeClient([[], [], [], []])
    result = recalculate_candidate(client, candidate, explain=True)
    assert client.updates == [('candidates', calculate_scores(candidate, [], [], []))]
    assert result['score_breakdown']['scores']['overall_trust_score'] == result['new_overall']
    assert not client.responses


def test_search_defensively_deduplicates_old_rpc_results_and_clamps_limit():
    from db_supabase import search_candidate_ids

    client = FakeSearchClient([
        [],  # exact wallet address
        [],  # exact wallet name service
        [],  # exact profile
        [],  # exact candidate
        [],  # alias
        [
            {"candidate_id": 7, "rank": 1.0},
            {"candidate_id": 7, "rank": 0.9},
            {"candidate_id": 8, "rank": 0.8},
        ],
    ])
    assert search_candidate_ids(client, "needle", limit=500) == [7, 8]
    assert client.rpc_calls == [(
        "search_candidates_fuzzy",
        {"search_query": "needle", "limit_rows": 100},
    )]


def test_refresh_search_view_is_compatibility_noop():
    from db_supabase import refresh_search_view

    client = object()
    assert refresh_search_view(client) is None


def test_resolver_deduplicates_mocked_api_responses(monkeypatch):
    import resolve_identity as resolver
    profile = {'platform': 'ens', 'identity': 'alice.eth', 'address': '0xab'}
    monkeypatch.setattr(resolver, 'build_web3bio_queries', lambda _: [('one', 'url1'), ('two', 'url2')])
    monkeypatch.setattr(resolver, 'request_json', lambda _: [profile])
    result = resolver.fetch_web3bio_profiles({})
    assert result == [{**profile, '_source_label': 'one', '_api_url': 'url1'}]
    assert '_api_url' not in profile


@pytest.mark.parametrize('module', [
    'db_supabase', 'parse_web3_to_supabase', 'enrich_to_supabase', 'resolve_identity',
    'wallet_deep_enrich', 'recalculate_scores', 'search_candidate', 'bot',
    'test_supabase_connection', 'scoring', 'worker',
])
def test_legacy_imports_need_no_keys_and_open_no_connections(module):
    importlib.import_module(module)


@pytest.mark.parametrize('script', [
    'parse_web3_to_supabase.py', 'enrich_to_supabase.py',
    'resolve_identity.py', 'wallet_deep_enrich.py',
    'recalculate_scores.py', 'search_candidate.py', 'worker.py',
])
def test_existing_cli_help_needs_no_database(script, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', [script, '--help'])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(script, run_name='__main__')
    assert result.value.code == 0
    assert 'usage:' in capsys.readouterr().out


def test_unit_network_guard_is_active():
    with pytest.raises(AssertionError, match='Network access is forbidden'):
        socket.create_connection(('localhost', 1))
