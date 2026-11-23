#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Recalculate candidate trust scores in Supabase.

Usage:
    python3 recalculate_scores.py
    python3 recalculate_scores.py --id 44
    python3 recalculate_scores.py --limit 50
"""

import argparse
import json
from typing import Any, Dict, List
from crycon.contacts import (
    BAD_CONTACT_FRAGMENTS, FORUM_DOMAINS, PLATFORM_DOMAINS, get_domain,
    is_bad_contact_value, is_forum_url, is_platform_url, is_source_or_profile_url,
    is_real_personal_website, is_useful_contact,
)
from crycon.scoring import calculate_scores, explain_scores, status_from_score as status_from_overall
from crycon.supabase_repository import SupabaseCandidateRepository

from db_supabase import get_supabase_client, clean_text


def fetch_candidates(client, limit: int = 500) -> List[Dict[str, Any]]:
    response = (
        client
        .table("candidates")
        .select("*")
        .order("id")
        .limit(limit)
        .execute()
    )

    return response.data or []


def fetch_candidate_by_id(client, candidate_id: int) -> Dict[str, Any]:
    return SupabaseCandidateRepository(client).get_candidate(candidate_id) or {}


def fetch_profiles(client, candidate_id: int) -> List[Dict[str, Any]]:
    return SupabaseCandidateRepository(client).list_profiles(candidate_id)


def fetch_contacts(client, candidate_id: int) -> List[Dict[str, Any]]:
    return SupabaseCandidateRepository(client).list_contacts(candidate_id)


def fetch_wallets(client, candidate_id: int) -> List[Dict[str, Any]]:
    return SupabaseCandidateRepository(client).list_wallets(candidate_id)


def update_candidate(client, candidate_id: int, scores: Dict[str, int | str]) -> None:
    (
        client
        .table("candidates")
        .update(scores)
        .eq("id", candidate_id)
        .execute()
    )


def recalculate_candidate(client, candidate: Dict[str, Any], explain: bool = False) -> Dict[str, Any]:
    candidate_id = int(candidate["id"])

    profiles = fetch_profiles(client, candidate_id)
    contacts = fetch_contacts(client, candidate_id)
    wallets = fetch_wallets(client, candidate_id)

    scores = calculate_scores(
        candidate=candidate,
        profiles=profiles,
        contacts=contacts,
        wallets=wallets,
    )

    old_overall = int(candidate.get("overall_trust_score") or 0)
    old_status = clean_text(candidate.get("status"))

    update_candidate(client, candidate_id, scores)

    result = {
        "candidate_id": candidate_id,
        "username": candidate.get("main_username"),
        "old_overall": old_overall,
        "new_overall": scores["overall_trust_score"],
        "old_status": old_status,
        "new_status": scores["status"],
        "contact_score": scores["contact_score"],
        "wallet_score": scores["wallet_score"],
    }
    if explain:
        result["score_breakdown"] = explain_scores(candidate, profiles, contacts, wallets)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recalculate Mirae trust scores."
    )

    parser.add_argument(
        "--id",
        type=int,
        help="Recalculate one candidate by ID",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max candidates to recalculate",
    )

    parser.add_argument("--explain", action="store_true", help="Print score breakdown (still writes scores)")
    args = parser.parse_args()

    client = get_supabase_client()

    print("=" * 90)
    print("Mirae Score Recalculation")
    print("=" * 90)

    if args.id:
        candidate = fetch_candidate_by_id(client, args.id)

        if not candidate:
            print(f"Candidate not found: {args.id}")
            return

        candidates = [candidate]

    else:
        candidates = fetch_candidates(client, args.limit)

    print(f"Candidates: {len(candidates)}")
    print("=" * 90)

    for candidate in candidates:
        result = recalculate_candidate(client, candidate, explain=args.explain)

        print(
            f"candidate_id={result['candidate_id']} "
            f"username={result['username']} "
            f"overall {result['old_overall']} → {result['new_overall']} "
            f"status {result['old_status']} → {result['new_status']} "
            f"contact_score={result['contact_score']} "
            f"wallet_score={result['wallet_score']}"
        )
        if args.explain:
            print(json.dumps(result["score_breakdown"], ensure_ascii=False, indent=2))

    print("=" * 90)
    print("Done")
    print("=" * 90)


if __name__ == "__main__":
    main()
