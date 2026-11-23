import pytest
from pydantic import ValidationError

from crycon.job_handlers import JobHandlerRegistry
from crycon.job_payloads import (
    ContactEnrichmentPayload,
    DiscoveryPayload,
    parse_job_payload,
    serialize_job_payload,
)


def test_payload_round_trip_is_discriminated_and_strict():
    payload = ContactEnrichmentPayload(
        job_type="contact_enrichment",
        candidate_id=42,
    )

    parsed = parse_job_payload("contact_enrichment", serialize_job_payload(payload))

    assert parsed == payload
    with pytest.raises(ValueError, match="does not match"):
        parse_job_payload("wallet_enrichment", serialize_job_payload(payload))
    with pytest.raises(ValidationError):
        parse_job_payload(
            "contact_enrichment",
            '{"job_type":"contact_enrichment","candidate_id":0}',
        )


def test_legacy_discovery_query_is_upgraded_to_typed_payload():
    payload = parse_job_payload("discovery", "validator | governance")

    assert isinstance(payload, DiscoveryPayload)
    assert payload.keywords == ["validator", "governance"]


def test_registry_routes_only_registered_job_types():
    received = []
    registry = JobHandlerRegistry({
        "contact_enrichment": lambda payload, job: received.append(
            (payload.candidate_id, job["id"])
        ) or 3,
    })
    job = {
        "id": 7,
        "job_type": "contact_enrichment",
        "query": serialize_job_payload(ContactEnrichmentPayload(
            job_type="contact_enrichment",
            candidate_id=42,
        )),
    }

    assert registry.handle(job) == 3
    assert received == [(42, 7)]
    with pytest.raises(ValueError, match="unsupported job_type"):
        registry.handle({"id": 8, "job_type": "unknown", "query": "{}"})
