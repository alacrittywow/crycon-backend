#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Resolve public Web3 identity from X/Twitter / ENS / Lens / Farcaster / wallet.

Usage:
    python3 resolve_identity.py https://x.com/vitalikbuterin
    python3 resolve_identity.py @vitalikbuterin
    python3 resolve_identity.py vitalik.eth
    python3 resolve_identity.py dwr.eth
    python3 resolve_identity.py 0xd8da6bf26964af9d7eed9e03e53415d37aa96045

Then:
    python3 recalculate_scores.py --id <candidate_id>
    python3 search_candidate.py --id <candidate_id> --full
"""

import re
import argparse
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

from crycon.normalization import (
    EVM_RE, X_HANDLE_RE, BASE58_ALPHABET, normalize_x_handle,
    normalize_identity_input, base58_decode, is_valid_solana_address, normalize_profiles,
)
from crycon.deduplication import deduplicate_web3_profiles
from crycon.supabase_repository import SupabaseCandidateRepository

import requests

from crycon.config import load_settings
from db_supabase import get_supabase_client, clean_text

settings = load_settings()

WEB3BIO_API_KEY = settings.text("WEB3BIO_API_KEY")

USER_AGENT = "Mirae-Identity-Resolver"


def web3bio_headers() -> Dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    if WEB3BIO_API_KEY:
        headers["X-API-KEY"] = f"Bearer {WEB3BIO_API_KEY}"

    return headers


def request_json(url: str, timeout: int = 25) -> Optional[Any]:
    try:
        response = requests.get(
            url,
            headers=web3bio_headers(),
            timeout=timeout,
        )

        if response.status_code in {400, 401, 403, 404, 429}:
            return None

        response.raise_for_status()

        return response.json()

    except Exception:
        return None


def build_web3bio_queries(identity: Dict[str, str]) -> List[Tuple[str, str]]:
    """
    Returns:
        [(source_label, api_url)]
    """
    kind = identity["kind"]
    value = identity["value"]

    queries = []

    def add(label: str, path: str) -> None:
        queries.append((label, f"https://api.web3.bio/{path}"))

    if kind == "x":
        handle = value

        # Самый важный трюк:
        # X handle часто совпадает с Farcaster/Lens/ENS/Basename.
        add("web3bio_farcaster_handle", f"profile/farcaster/{quote(handle)}")
        add("web3bio_farcaster_handle_eth", f"profile/farcaster/{quote(handle + '.eth')}")
        add("web3bio_lens_handle", f"profile/lens/{quote(handle + '.lens')}")
        add("web3bio_ens_handle", f"profile/ens/{quote(handle + '.eth')}")
        add("web3bio_basenames_handle", f"profile/basenames/{quote(handle + '.base.eth')}")
        add("web3bio_universal_eth", f"profile/{quote(handle + '.eth')}")
        add("web3bio_universal_lens", f"profile/{quote(handle + '.lens')}")
        add("web3bio_universal_base", f"profile/{quote(handle + '.base.eth')}")

    elif kind == "ens":
        add("web3bio_universal", f"profile/{quote(value)}")
        add("web3bio_ens", f"profile/ens/{quote(value)}")
        add("web3bio_farcaster", f"profile/farcaster/{quote(value)}")

    elif kind == "lens":
        add("web3bio_universal", f"profile/{quote(value)}")
        add("web3bio_lens", f"profile/lens/{quote(value)}")

    elif kind == "sns_sol":
        add("web3bio_solana", f"profile/solana/{quote(value)}")
        add("web3bio_universal", f"profile/{quote(value)}")

    elif kind == "farcaster":
        add("web3bio_farcaster", f"profile/farcaster/{quote(value)}")
        add("web3bio_universal_farcaster", f"profile/{quote(value + '.farcaster')}")

    elif kind in {"evm", "solana"}:
        add("web3bio_universal_wallet", f"profile/{quote(value)}")

    else:
        handle = value.strip("@")
        add("web3bio_farcaster_handle", f"profile/farcaster/{quote(handle)}")
        add("web3bio_lens_handle", f"profile/lens/{quote(handle + '.lens')}")
        add("web3bio_ens_handle", f"profile/ens/{quote(handle + '.eth')}")

    return queries


def profile_web_url(profile: Dict[str, Any]) -> str:
    identity = clean_text(profile.get("identity"))

    if not identity:
        return ""

    return f"https://web3.bio/{identity}"


def get_profile_links(profile: Dict[str, Any]) -> Dict[str, Any]:
    links = profile.get("links")

    if isinstance(links, dict):
        return links

    return {}


def get_link_value(profile: Dict[str, Any], key: str) -> str:
    links = get_profile_links(profile)
    item = links.get(key)

    if isinstance(item, dict):
        return clean_text(item.get("link"))

    return ""


def get_link_handle(profile: Dict[str, Any], key: str) -> str:
    links = get_profile_links(profile)
    item = links.get(key)

    if isinstance(item, dict):
        return clean_text(item.get("handle"))

    return ""


def twitter_handle_from_profile(profile: Dict[str, Any]) -> str:
    handle = get_link_handle(profile, "twitter")

    if handle:
        return handle.strip("@")

    link = get_link_value(profile, "twitter")

    if link:
        return normalize_x_handle(link)

    return ""


def profile_has_exact_x_match(profile: Dict[str, Any], x_handle: str) -> bool:
    if not x_handle:
        return False

    linked_handle = twitter_handle_from_profile(profile)

    return linked_handle.lower() == x_handle.lower()


def wallet_from_profile(profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    address = clean_text(profile.get("address"))
    platform = clean_text(profile.get("platform")).lower()
    identity = clean_text(profile.get("identity"))

    if address and EVM_RE.match(address):
        return {
            "wallet_type": "evm",
            "wallet_address": address,
            "name_service": "",
            "chain": "ethereum",
        }

    if address and is_valid_solana_address(address):
        return {
            "wallet_type": "solana",
            "wallet_address": address,
            "name_service": "",
            "chain": "solana",
        }

    if identity.endswith(".eth"):
        return {
            "wallet_type": "ens",
            "wallet_address": "",
            "name_service": identity.lower(),
            "chain": "ethereum",
        }

    if identity.endswith(".sol"):
        return {
            "wallet_type": "sns_sol",
            "wallet_address": "",
            "name_service": identity.lower(),
            "chain": "solana",
        }

    if platform == "ens" and identity:
        return {
            "wallet_type": "ens",
            "wallet_address": "",
            "name_service": identity.lower(),
            "chain": "ethereum",
        }

    return None


def fetch_web3bio_profiles(identity: Dict[str, str]) -> List[Dict[str, Any]]:
    results = []
    for source_label, url in build_web3bio_queries(identity):
        data = request_json(url)
        for profile in normalize_profiles(data):
            results.append({**profile, "_source_label": source_label, "_api_url": url})
    return deduplicate_web3_profiles(results)


def find_candidate_by_x_handle(client, handle: str) -> Optional[Dict[str, Any]]:
    if not handle:
        return None

    variants = [
        f"https://x.com/{handle}",
        f"https://twitter.com/{handle}",
        f"http://x.com/{handle}",
        f"http://twitter.com/{handle}",
    ]

    for variant in variants:
        response = (
            client
            .table("contacts")
            .select("*")
            .eq("contact_type", "x")
            .ilike("value", f"%{variant}%")
            .limit(1)
            .execute()
        )

        if response.data:
            candidate_id = response.data[0].get("candidate_id")
            return fetch_candidate(client, candidate_id)

    response = (
        client
        .table("profiles")
        .select("*")
        .ilike("username", handle)
        .limit(1)
        .execute()
    )

    if response.data:
        candidate_id = response.data[0].get("candidate_id")
        return fetch_candidate(client, candidate_id)

    return None


def fetch_candidate(client, candidate_id: int) -> Optional[Dict[str, Any]]:
    return SupabaseCandidateRepository(client).get_candidate(candidate_id)


def create_candidate(client, username: str, display_name: str = "", bio: str = "") -> Dict[str, Any]:
    payload = {
        "main_username": username,
        "display_name": display_name or username,
        "bio": bio,
        "relevance_score": 40,
        "identity_score": 50,
        "wallet_score": 0,
        "contact_score": 0,
        "overall_trust_score": 45,
        "status": "needs_review",
    }

    response = (
        client
        .table("candidates")
        .insert(payload)
        .execute()
    )

    if not response.data:
        raise RuntimeError("Failed to create candidate")

    return response.data[0]


def ensure_candidate(client, identity: Dict[str, str], profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    x_handle = identity.get("x_handle", "")

    if x_handle:
        existing = find_candidate_by_x_handle(client, x_handle)

        if existing:
            return existing

    display_name = ""
    bio = ""

    for profile in profiles:
        display_name = clean_text(profile.get("displayName"))

        if display_name:
            break

    for profile in profiles:
        bio = clean_text(profile.get("description"))

        if bio:
            break

    username = x_handle or identity["value"]

    return create_candidate(
        client=client,
        username=username,
        display_name=display_name,
        bio=bio,
    )


def profile_exists(client, platform: str, username: str) -> bool:
    response = (
        client
        .table("profiles")
        .select("id")
        .eq("platform", platform)
        .eq("username", username)
        .limit(1)
        .execute()
    )

    return bool(response.data)


def insert_profile(client, candidate_id: int, platform: str, username: str, profile_url: str, source_url: str, confidence: int) -> bool:
    if not platform or not username:
        return False

    if profile_exists(client, platform, username):
        return False

    payload = {
        "candidate_id": candidate_id,
        "platform": platform,
        "username": username,
        "display_name": "",
        "bio": "",
        "profile_url": profile_url,
        "source_url": source_url,
        "matched_keyword": "",
        "confidence": confidence,
        "evidence_type": "identity_resolver",
    }

    (
        client
        .table("profiles")
        .insert(payload)
        .execute()
    )

    return True


def contact_exists(client, candidate_id: int, contact_type: str, value: str) -> bool:
    response = (
        client
        .table("contacts")
        .select("id")
        .eq("candidate_id", candidate_id)
        .eq("contact_type", contact_type)
        .eq("value", value)
        .limit(1)
        .execute()
    )

    return bool(response.data)


def insert_contact(client, candidate_id: int, contact_type: str, value: str, confidence: int, evidence_url: str, evidence_text: str) -> bool:
    value = clean_text(value)

    if not value:
        return False

    if contact_exists(client, candidate_id, contact_type, value):
        return False

    payload = {
        "candidate_id": candidate_id,
        "contact_type": contact_type,
        "value": value,
        "confidence": confidence,
        "status": "probable" if confidence >= 70 else "possible",
        "evidence_url": evidence_url,
        "evidence_text": evidence_text[:1000],
    }

    (
        client
        .table("contacts")
        .insert(payload)
        .execute()
    )

    return True


def wallet_exists(client, candidate_id: int, wallet_type: str, wallet_address: str, name_service: str) -> bool:
    query = (
        client
        .table("wallets")
        .select("id")
        .eq("candidate_id", candidate_id)
        .eq("wallet_type", wallet_type)
    )

    if wallet_address:
        query = query.eq("wallet_address", wallet_address)

    if name_service:
        query = query.eq("name_service", name_service)

    response = query.limit(1).execute()

    return bool(response.data)


def insert_wallet(client, candidate_id: int, wallet: Dict[str, str], confidence: int, evidence_url: str, evidence_text: str) -> bool:
    wallet_type = clean_text(wallet.get("wallet_type"))
    wallet_address = clean_text(wallet.get("wallet_address"))
    name_service = clean_text(wallet.get("name_service"))
    chain = clean_text(wallet.get("chain"))

    if not wallet_address and not name_service:
        return False

    if wallet_exists(client, candidate_id, wallet_type, wallet_address, name_service):
        return False

    payload = {
        "candidate_id": candidate_id,
        "wallet_type": wallet_type,
        "wallet_address": wallet_address,
        "name_service": name_service,
        "chain": chain,
        "confidence": confidence,
        "status": "probable_wallet" if confidence >= 85 else "possible_wallet",
        "evidence_url": evidence_url,
        "evidence_text": evidence_text[:1000],
        "evidence_type": "identity_graph",
    }

    (
        client
        .table("wallets")
        .insert(payload)
        .execute()
    )

    return True


def insert_evidence(client, candidate_id: int, entity_type: str, entity_value: str, source_platform: str, source_url: str, evidence_text: str, confidence: int) -> None:
    payload = {
        "candidate_id": candidate_id,
        "entity_type": entity_type,
        "entity_value": entity_value,
        "source_platform": source_platform,
        "source_url": source_url,
        "evidence_text": evidence_text[:1000],
        "confidence": confidence,
    }

    (
        client
        .table("evidence")
        .insert(payload)
        .execute()
    )


def confidence_for_profile(identity: Dict[str, str], profile: Dict[str, Any]) -> int:
    kind = identity["kind"]
    x_handle = identity.get("x_handle", "")

    if kind == "x":
        if profile_has_exact_x_match(profile, x_handle):
            return 95

        # Это handle reuse: handle похож на ENS/Lens/Farcaster,
        # но без явной twitter-связи. Считаем только possible.
        return 55

    if kind in {"ens", "lens", "farcaster", "sns_sol", "evm", "solana"}:
        return 90

    return 60


def save_profile_artifacts(client, candidate_id: int, identity: Dict[str, str], profile: Dict[str, Any]) -> Dict[str, int]:
    stats = {
        "profiles": 0,
        "contacts": 0,
        "wallets": 0,
        "evidence": 0,
    }

    platform = clean_text(profile.get("platform")).lower()
    profile_identity = clean_text(profile.get("identity"))
    display_name = clean_text(profile.get("displayName"))
    description = clean_text(profile.get("description"))
    address = clean_text(profile.get("address"))
    web_url = profile_web_url(profile)
    api_url = clean_text(profile.get("_api_url"))
    source_label = clean_text(profile.get("_source_label"))

    confidence = confidence_for_profile(identity, profile)

    evidence_text = (
        f"Resolved via Web3.bio. "
        f"platform={platform}; identity={profile_identity}; "
        f"displayName={display_name}; address={address}; "
        f"confidence_reason={'exact_x_link' if profile_has_exact_x_match(profile, identity.get('x_handle', '')) else 'identity_or_handle_match'}"
    )

    if insert_profile(
        client=client,
        candidate_id=candidate_id,
        platform=f"web3bio:{platform}",
        username=profile_identity or address,
        profile_url=web_url,
        source_url=api_url,
        confidence=confidence,
    ):
        stats["profiles"] += 1

    # X contact from Web3.bio links
    twitter_link = get_link_value(profile, "twitter")
    twitter_handle = twitter_handle_from_profile(profile)

    if twitter_link:
        if insert_contact(client, candidate_id, "x", twitter_link, confidence, api_url, evidence_text):
            stats["contacts"] += 1

    elif twitter_handle:
        twitter_link = f"https://x.com/{twitter_handle}"

        if insert_contact(client, candidate_id, "x", twitter_link, confidence, api_url, evidence_text):
            stats["contacts"] += 1

    # Other useful links
    for key, contact_type in [
        ("github", "github"),
        ("website", "website"),
        ("farcaster", "farcaster"),
        ("lens", "lens"),
    ]:
        link = get_link_value(profile, key)

        if link:
            if insert_contact(client, candidate_id, contact_type, link, max(confidence - 5, 50), api_url, evidence_text):
                stats["contacts"] += 1

    # Email
    email = clean_text(profile.get("email"))

    if email:
        if insert_contact(client, candidate_id, "email", email, max(confidence - 5, 50), api_url, evidence_text):
            stats["contacts"] += 1

    wallet = wallet_from_profile(profile)

    if wallet:
        if insert_wallet(client, candidate_id, wallet, confidence, api_url, evidence_text):
            stats["wallets"] += 1

        wallet_value = wallet.get("wallet_address") or wallet.get("name_service")

        insert_evidence(
            client=client,
            candidate_id=candidate_id,
            entity_type=f"{wallet.get('wallet_type')}_wallet",
            entity_value=wallet_value,
            source_platform=source_label or f"web3bio:{platform}",
            source_url=api_url,
            evidence_text=evidence_text,
            confidence=confidence,
        )
        stats["evidence"] += 1

    insert_evidence(
        client=client,
        candidate_id=candidate_id,
        entity_type="identity_resolution",
        entity_value=profile_identity or address,
        source_platform=source_label or f"web3bio:{platform}",
        source_url=api_url,
        evidence_text=evidence_text,
        confidence=confidence,
    )
    stats["evidence"] += 1

    return stats


def print_profile_result(identity: Dict[str, str], profile: Dict[str, Any]) -> None:
    confidence = confidence_for_profile(identity, profile)

    platform = clean_text(profile.get("platform"))
    profile_identity = clean_text(profile.get("identity"))
    display_name = clean_text(profile.get("displayName"))
    address = clean_text(profile.get("address"))
    twitter_handle = twitter_handle_from_profile(profile)

    print("-" * 90)
    print(f"platform:     {platform}")
    print(f"identity:     {profile_identity}")
    print(f"display name: {display_name}")
    print(f"address:      {address}")
    print(f"x link:       {twitter_handle or 'none'}")
    print(f"confidence:   {confidence}")

    links = get_profile_links(profile)

    if links:
        print("links:")

        for key, value in links.items():
            if isinstance(value, dict):
                link = clean_text(value.get("link"))

                if link:
                    print(f"  - {key}: {link}")


def resolve_identity(input_value: str, client=None) -> Optional[int]:
    client = client or get_supabase_client()

    identity = normalize_identity_input(input_value)

    print("=" * 90)
    print("Mirae Identity Resolver")
    print("=" * 90)
    print(f"Input:      {identity['raw']}")
    print(f"Kind:       {identity['kind']}")
    print(f"Value:      {identity['value']}")
    print(f"X handle:   {identity.get('x_handle') or 'none'}")
    print(f"Web3.bio key present: {bool(WEB3BIO_API_KEY)}")
    print("=" * 90)

    profiles = fetch_web3bio_profiles(identity)

    print(f"Web3.bio profiles found: {len(profiles)}")

    if not profiles:
        print("No external identity profiles found.")
        return None

    for profile in profiles:
        print_profile_result(identity, profile)

    candidate = ensure_candidate(client, identity, profiles)
    candidate_id = int(candidate["id"])

    print("=" * 90)
    print(f"Saving to candidate_id={candidate_id} username={candidate.get('main_username')}")
    print("=" * 90)

    total_profiles = 0
    total_contacts = 0
    total_wallets = 0
    total_evidence = 0

    for profile in profiles:
        stats = save_profile_artifacts(
            client=client,
            candidate_id=candidate_id,
            identity=identity,
            profile=profile,
        )

        total_profiles += stats["profiles"]
        total_contacts += stats["contacts"]
        total_wallets += stats["wallets"]
        total_evidence += stats["evidence"]

    print("=" * 90)
    print("Saved")
    print(f"candidate_id: {candidate_id}")
    print(f"profiles added: {total_profiles}")
    print(f"contacts added: {total_contacts}")
    print(f"wallets added:  {total_wallets}")
    print(f"evidence added: {total_evidence}")
    print("=" * 90)
    print("Next:")
    print(f"  python3 recalculate_scores.py --id {candidate_id}")
    print(f"  python3 search_candidate.py --id {candidate_id} --full")
    print("=" * 90)
    return candidate_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve wallets from public Web3 identity signals."
    )

    parser.add_argument(
        "identity",
        help="X URL, @handle, ENS, Lens, Farcaster, EVM wallet, Solana wallet",
    )

    args = parser.parse_args()

    resolve_identity(args.identity)


if __name__ == "__main__":
    main()
