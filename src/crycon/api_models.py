"""Stable HTTP response models for the read-only API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Candidate(ApiModel):
    id: int
    main_username: str
    display_name: str | None = None
    bio: str | None = None
    relevance_score: int = Field(default=0, ge=0, le=100)
    identity_score: int = Field(default=0, ge=0, le=100)
    wallet_score: int = Field(default=0, ge=0, le=100)
    contact_score: int = Field(default=0, ge=0, le=100)
    overall_trust_score: int = Field(default=0, ge=0, le=100)
    status: str = "new"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Profile(ApiModel):
    id: int
    candidate_id: int
    platform: str
    username: str
    display_name: str | None = None
    bio: str | None = None
    profile_url: str | None = None
    source_url: str | None = None
    matched_keyword: str | None = None
    confidence: int = Field(default=50, ge=0, le=100)
    evidence_type: str = "discovered"
    created_at: datetime | None = None


class Contact(ApiModel):
    id: int
    candidate_id: int
    contact_type: str
    value: str
    confidence: int = Field(default=0, ge=0, le=100)
    status: str = "possible"
    evidence_url: str | None = None
    evidence_text: str | None = None
    created_at: datetime | None = None


class Wallet(ApiModel):
    id: int
    candidate_id: int
    wallet_type: str
    wallet_address: str | None = None
    chain: str | None = None
    name_service: str | None = None
    confidence: int = Field(default=0, ge=0, le=100)
    status: str = "possible"
    evidence_url: str | None = None
    evidence_text: str | None = None
    evidence_type: str = "public_text"
    created_at: datetime | None = None


class Evidence(ApiModel):
    id: int
    candidate_id: int
    entity_type: str
    entity_value: str | None = None
    source_platform: str | None = None
    source_url: str | None = None
    evidence_text: str | None = None
    confidence: int = Field(default=0, ge=0, le=100)
    created_at: datetime | None = None


class CandidatePage(ApiModel):
    items: list[Candidate]
    limit: int
    offset: int
    next_offset: int | None


class SearchResults(ApiModel):
    query: str
    items: list[Candidate]


class CandidateDetail(ApiModel):
    candidate: Candidate
    profiles: list[Profile]
    contacts: list[Contact]
    wallets: list[Wallet]


class EvidenceResults(ApiModel):
    candidate_id: int
    items: list[Evidence]


class Health(ApiModel):
    status: str


JobStatus = Literal["new", "running", "done", "failed"]


class ParserJob(ApiModel):
    id: int
    job_type: str
    query: str | None = None
    status: JobStatus
    result_count: int = Field(default=0, ge=0)
    idempotency_key: str | None = None
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=20)
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    locked_by: str | None = None
    error_text: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None


class ParserJobPage(ApiModel):
    items: list[ParserJob]
    limit: int
    offset: int
    next_offset: int | None
