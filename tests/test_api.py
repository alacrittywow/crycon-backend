import asyncio
import hmac
import json
import time
from urllib.parse import urlencode

from httpx import ASGITransport, AsyncClient

from crycon.api import create_app
from tests.fakes import FakeCandidateRepository, FakeParserJobRepository


ADMIN_HEADERS = {"X-API-Key": "test-admin"}


def request(app, method: str, path: str, **kwargs):
    async def send():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def candidate(candidate_id: int, username: str, score: int) -> dict:
    return {
        "id": candidate_id,
        "main_username": username,
        "overall_trust_score": score,
        "relevance_score": 40,
        "identity_score": 50,
        "wallet_score": 30,
        "contact_score": 20,
        "status": "valid",
    }


def test_health_is_liveness_and_needs_no_repository_or_credentials():
    app = create_app()

    response = request(app, "GET", "/health")
    readiness = request(app, "GET", "/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert readiness.status_code == 503
    assert readiness.json() == {"detail": "Storage is not ready"}


def test_readiness_checks_storage_separately_from_liveness():
    app = create_app(FakeCandidateRepository())

    assert request(app, "GET", "/ready").json() == {"status": "ready"}

    class UnreadyRepository(FakeCandidateRepository):
        def ping(self) -> bool:
            return False

    assert request(create_app(UnreadyRepository()), "GET", "/ready").status_code == 503


def test_miniapp_serves_html_and_assets_without_storage():
    app = create_app()
    index = request(app, "GET", "/miniapp/")
    assert index.status_code == 200
    assert 'id="search-form"' in index.text
    assert request(app, "GET", "/miniapp/app.js").status_code == 200
    assert request(app, "GET", "/miniapp/style.css").status_code == 200


def test_miniapp_candidate_routes_require_fresh_signed_telegram_data():
    token = "demo-test-token"
    app = create_app(
        FakeCandidateRepository(candidates=[candidate(1, "alice", 90)]),
        telegram_token=token,
        telegram_allowed_ids=frozenset({42}),
    )

    def sign(user_id, timestamp):
        fields = {"auth_date": str(timestamp), "user": json.dumps({"id": user_id})}
        canonical = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.digest(b"WebAppData", token.encode(), "sha256")
        fields["hash"] = hmac.digest(secret, canonical.encode(), "sha256").hex()
        return urlencode(fields)

    now = int(time.time())
    header = "X-Telegram-Init-Data"
    signed = sign(42, now)
    for path in ("/candidates", "/search?q=alice", "/candidates/1", "/candidates/1/evidence"):
        assert request(app, "GET", path).status_code == 401
        response = request(app, "GET", path, headers={header: signed})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"

    for invalid in (signed.replace("42", "43"), sign(42, now - 3601), signed + "&user=other"):
        assert request(app, "GET", "/candidates", headers={header: invalid}).status_code == 401
    assert request(app, "GET", "/candidates", headers={header: sign(43, now)}).status_code == 403


def test_candidate_list_has_bounded_cursorless_pagination():
    repository = FakeCandidateRepository(candidates=[
        candidate(1, "alice", 90),
        candidate(2, "bob", 80),
        candidate(3, "carol", 70),
    ])
    app = create_app(repository)

    first = request(app, "GET", "/candidates", params={"limit": 2})
    second = request(app, "GET", "/candidates", params={"limit": 2, "offset": 2})

    assert first.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == [1, 2]
    assert first.json()["next_offset"] == 2
    assert [item["id"] for item in second.json()["items"]] == [3]
    assert second.json()["next_offset"] is None
    assert request(app, "GET", "/candidates", params={"limit": 51}).status_code == 422


def test_search_returns_ranked_candidates_and_rejects_blank_query():
    repository = FakeCandidateRepository(candidates=[
        candidate(2, "alice-dev", 70),
        candidate(1, "alice", 90),
        candidate(3, "bob", 80),
    ])
    app = create_app(repository)

    response = request(app, "GET", "/search", params={"q": " alice ", "limit": 10})

    assert response.status_code == 200
    assert response.json()["query"] == "alice"
    assert [item["id"] for item in response.json()["items"]] == [2, 1]
    assert request(app, "GET", "/search", params={"q": "   "}).status_code == 422


def test_candidate_detail_and_evidence_are_separate_resources():
    repository = FakeCandidateRepository(
        candidates=[candidate(1, "alice", 90)],
        profiles=[{
            "id": 10,
            "candidate_id": 1,
            "platform": "github",
            "username": "alice",
        }],
        contacts=[{
            "id": 20,
            "candidate_id": 1,
            "contact_type": "email",
            "value": "alice@example.test",
        }],
        wallets=[{
            "id": 30,
            "candidate_id": 1,
            "wallet_type": "evm",
            "wallet_address": "0xabc",
        }],
        evidence=[
            {"id": 40, "candidate_id": 1, "entity_type": "profile", "confidence": 50},
            {"id": 41, "candidate_id": 1, "entity_type": "wallet", "confidence": 90},
        ],
    )
    app = create_app(repository)

    detail = request(app, "GET", "/candidates/1")
    evidence = request(app, "GET", "/candidates/1/evidence", params={"limit": 1})

    assert detail.status_code == 200
    assert detail.json()["candidate"]["main_username"] == "alice"
    assert detail.json()["profiles"][0]["platform"] == "github"
    assert detail.json()["contacts"][0]["contact_type"] == "email"
    assert detail.json()["wallets"][0]["wallet_type"] == "evm"
    assert "evidence" not in detail.json()
    assert [item["id"] for item in evidence.json()["items"]] == [41]
    assert request(app, "GET", "/candidates/999").status_code == 404
    assert request(app, "GET", "/candidates/999/evidence").status_code == 404
    assert request(app, "GET", "/candidates/0").status_code == 422


def test_openapi_documents_read_only_routes():
    schema = create_app(
        FakeCandidateRepository(), FakeParserJobRepository(), "test-admin"
    ).openapi()

    assert set(schema["paths"]) >= {
        "/health",
        "/candidates",
        "/search",
        "/candidates/{candidate_id}",
        "/candidates/{candidate_id}/evidence",
        "/jobs",
        "/jobs/{job_id}",
    }
    assert "post" in schema["paths"]["/jobs"]
    assert all(
        set(methods).isdisjoint({"post", "put", "patch", "delete"})
        for path, methods in schema["paths"].items()
        if path.startswith("/candidates") or path == "/search"
    )


def test_job_api_requires_idempotency_and_returns_same_job_for_retry():
    jobs = FakeParserJobRepository()
    app = create_app(FakeCandidateRepository(), jobs, "test-admin")
    payload = {"job_type": "discovery", "keywords": ["validator"], "max_attempts": 3}

    missing_header = request(
        app, "POST", "/jobs", json=payload, headers=ADMIN_HEADERS
    )
    first = request(
        app, "POST", "/jobs", json=payload,
        headers={**ADMIN_HEADERS, "Idempotency-Key": "request-123"},
    )
    duplicate = request(
        app, "POST", "/jobs", json=payload,
        headers={**ADMIN_HEADERS, "Idempotency-Key": "request-123"},
    )

    assert missing_header.status_code == 422
    assert first.status_code == 202
    assert duplicate.status_code == 202
    assert first.json()["id"] == duplicate.json()["id"]
    assert len(jobs.jobs) == 1


def test_job_api_lists_filters_and_returns_404():
    jobs = FakeParserJobRepository()
    first = jobs.enqueue_job("discovery", "one", "key-1")
    jobs.enqueue_job("enrichment", "two", "key-2")
    jobs.claim_job("worker-a")
    app = create_app(FakeCandidateRepository(), jobs, "test-admin")

    running = request(
        app, "GET", "/jobs", params={"status": "running"}, headers=ADMIN_HEADERS
    )
    detail = request(app, "GET", f"/jobs/{first['id']}", headers=ADMIN_HEADERS)

    assert running.status_code == 200
    assert [job["id"] for job in running.json()["items"]] == [first["id"]]
    assert detail.json()["attempt_count"] == 1
    assert request(app, "GET", "/jobs/999", headers=ADMIN_HEADERS).status_code == 404
    assert request(
        app, "GET", "/jobs", params={"status": "mystery"}, headers=ADMIN_HEADERS
    ).status_code == 422


def test_job_api_validates_payload_by_job_type():
    jobs = FakeParserJobRepository()
    app = create_app(FakeCandidateRepository(), jobs, "test-admin")
    headers = {**ADMIN_HEADERS, "Idempotency-Key": "contact-42"}

    valid = request(app, "POST", "/jobs", headers=headers, json={
        "job_type": "contact_enrichment",
        "candidate_id": 42,
    })
    invalid = request(app, "POST", "/jobs", headers=headers, json={
        "job_type": "contact_enrichment",
        "identity": "alice.eth",
    })
    unsupported = request(app, "POST", "/jobs", headers=headers, json={
        "job_type": "made_up",
    })

    assert valid.status_code == 202
    assert '"candidate_id":42' in valid.json()["query"]
    assert invalid.status_code == 422
    assert unsupported.status_code == 422


def test_job_api_is_closed_when_admin_key_is_missing_or_wrong():
    disabled = create_app(FakeCandidateRepository(), FakeParserJobRepository(), "")
    protected = create_app(
        FakeCandidateRepository(), FakeParserJobRepository(), "test-admin"
    )

    assert request(disabled, "GET", "/jobs").status_code == 503
    assert request(
        protected, "GET", "/jobs", headers={"X-API-Key": "wrong"}
    ).status_code == 401
    assert request(protected, "GET", "/jobs", headers=ADMIN_HEADERS).status_code == 200
