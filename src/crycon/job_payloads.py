"""Typed payloads stored in parser_jobs.query as compact JSON."""

import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class JobPayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_attempts: int = Field(default=3, ge=1, le=20)


class DiscoveryPayload(JobPayloadBase):
    job_type: Literal["discovery"]
    keywords: list[str] = Field(default_factory=list, max_length=50)


class ContactEnrichmentPayload(JobPayloadBase):
    job_type: Literal["contact_enrichment"]
    candidate_id: int = Field(ge=1)


class WalletEnrichmentPayload(JobPayloadBase):
    job_type: Literal["wallet_enrichment"]
    candidate_id: int = Field(ge=1)


class ScoreRecalculationPayload(JobPayloadBase):
    job_type: Literal["score_recalculation"]
    candidate_id: int = Field(ge=1)


class IdentityResolutionPayload(JobPayloadBase):
    job_type: Literal["identity_resolution"]
    identity: str = Field(min_length=1, max_length=500)


JobPayload = Annotated[
    Union[
        DiscoveryPayload,
        ContactEnrichmentPayload,
        WalletEnrichmentPayload,
        ScoreRecalculationPayload,
        IdentityResolutionPayload,
    ],
    Field(discriminator="job_type"),
]

_adapter = TypeAdapter(JobPayload)


def serialize_job_payload(payload: JobPayloadBase) -> str:
    return payload.model_dump_json()


def parse_job_payload(job_type: str, raw: str | None) -> JobPayloadBase:
    """Validate stored JSON while accepting pre-typed discovery rows."""
    text = (raw or "").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        if job_type != "discovery":
            raise ValueError(f"{job_type} job payload is not valid JSON") from None
        value = {
            "job_type": "discovery",
            "keywords": [item.strip() for item in text.split("|") if item.strip()],
        }
    if not isinstance(value, dict):
        raise ValueError("job payload must be a JSON object")
    value.setdefault("job_type", job_type)
    if value.get("job_type") != job_type:
        raise ValueError("stored job_type does not match payload job_type")
    return _adapter.validate_python(value)
