#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import create_client, Client
from crycon.config import load_settings
from crycon.scoring import calculate_relevance_score, status_from_score
from crycon.supabase_repository import SupabaseCandidateRepository
from crycon.text import clean_text


def get_supabase_client() -> Client:
    settings = load_settings()
    url = settings.require("SUPABASE_URL")
    key = settings.require("SUPABASE_KEY")

    return create_client(url, key)


def find_existing_profile(
    client: Client,
    platform: str,
    username: str,
) -> Optional[Dict[str, Any]]:
    response = (
        client
        .table("profiles")
        .select("*")
        .eq("platform", platform)
        .eq("username", username)
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def insert_candidate_with_profile_and_evidence(
    client: Client,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    source = clean_text(record.get("source"))
    username = clean_text(record.get("username"))

    if not source or not username:
        return {
            "status": "skipped",
            "reason": "missing source or username",
        }

    relevance_score = calculate_relevance_score(record)
    evidence_text = (
        "Discovered by parser. "
        f"Matched keyword: {clean_text(record.get('matched_keyword'))}"
    )
    response = client.rpc(
        "create_discovered_candidate",
        {
            "p_platform": source,
            "p_username": username,
            "p_display_name": clean_text(record.get("display_name")),
            "p_bio": clean_text(record.get("bio")),
            "p_profile_url": clean_text(record.get("profile_url")),
            "p_source_url": clean_text(record.get("source_url")),
            "p_matched_keyword": clean_text(record.get("matched_keyword")),
            "p_relevance_score": relevance_score,
            "p_status": status_from_score(relevance_score),
            "p_evidence_text": evidence_text,
        },
    ).execute()

    if not response.data:
        raise RuntimeError(
            "Atomic discovery RPC returned no result; apply migration 004"
        )

    row = response.data[0]
    result = {
        "status": row["result_status"],
        "candidate_id": row["candidate_id"],
        "profile_id": row["profile_id"],
        "evidence_id": row.get("evidence_id"),
    }
    if row["result_status"] == "created":
        result["relevance_score"] = relevance_score
    return result


def create_parser_job(
    client: Client,
    job_type: str,
    query: str,
    status: str = "running",
) -> Optional[int]:
    response = (
        client
        .table("parser_jobs")
        .insert({
            "job_type": job_type,
            "query": query,
            "status": status,
            "result_count": 0,
        })
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]["id"]


def finish_parser_job(
    client: Client,
    job_id: int,
    result_count: int,
    status: str = "done",
) -> None:
    (
        client
        .table("parser_jobs")
        .update({
            "status": status,
            "result_count": result_count,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", job_id)
        .execute()
    )


# ========== НОВЫЕ ФУНКЦИИ ДЛЯ УЛУЧШЕННОГО ПОИСКА ==========

def refresh_search_view(client: Client) -> None:
    """Compatibility no-op after migration 003 switched search to live tables."""
    return None


def search_candidate_ids(
    client: Client,
    query: str,
    limit: int = 10,
) -> List[int]:
    """Compatibility wrapper around the repository used by legacy callers."""
    return SupabaseCandidateRepository(client).search_candidate_ids(query, limit)
