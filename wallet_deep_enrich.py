#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deep public wallet enrichment.

Usage:
    python3 wallet_deep_enrich.py --limit 10
    python3 wallet_deep_enrich.py --id 44

Потом:
    python3 recalculate_scores.py
"""

import re
import time
import base64
import random
import argparse
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlparse

import requests

from crycon.normalization import BASE58_ALPHABET, base58_decode, is_valid_solana_address
from crycon.supabase_repository import SupabaseCandidateRepository

from crycon.config import load_settings
from db_supabase import get_supabase_client, clean_text

settings = load_settings()

SLEEP_MIN = settings.number("SLEEP_MIN", 1.0)
SLEEP_MAX = settings.number("SLEEP_MAX", 2.0)

WALLET_DEEP_LIMIT = settings.integer("WALLET_DEEP_LIMIT", 20)
MAX_GITHUB_REPOS_TO_SCAN = settings.integer("MAX_GITHUB_REPOS_TO_SCAN", 15)
MAX_DISCOURSE_SEARCHES_PER_USER = settings.integer("MAX_DISCOURSE_SEARCHES_PER_USER", 6)

GITHUB_TOKEN = settings.text("GITHUB_TOKEN")

USER_AGENT = "Mirae-Deep-Wallet-Enrichment"


EVM_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"0x[a-fA-F0-9]{40}"
    r"(?![A-Za-z0-9])"
)

ENS_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"[a-zA-Z0-9-]{2,}(?:\.[a-zA-Z0-9-]{2,})*\.eth"
    r"(?![A-Za-z0-9_.-])",
    re.IGNORECASE,
)

SOL_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"[a-zA-Z0-9-]{2,}\.sol"
    r"(?![A-Za-z0-9_.-])",
    re.IGNORECASE,
)

SOLANA_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[1-9A-HJ-NP-Za-km-z]{32,44}"
    r"(?![A-Za-z0-9])"
)


WALLET_CONTEXT_WORDS = [
    "wallet",
    "address",
    "public key",
    "pubkey",
    "delegate",
    "delegation",
    "voting address",
    "ecosystem actor address",
    "multisig",
    "safe",
    "gnosis",
    "treasury",
    "recipient",
    "donate",
    "donation",
    "tip",
    "ens",
    "ethereum",
    "evm",
    "solana",
    "staking",
    "validator",
    "signer",
    "owner",
]


BAD_CONTEXT_WORDS = [
    "example",
    "sample",
    "dummy",
    "placeholder",
    "fake",
    "test address",
    "testnet",
    "localhost",
    "hardhat",
    "foundry",
    "anvil",
    "fixture",
    "mock",
    "pragma solidity",
    "contract ",
    "interface ",
]


def polite_sleep() -> None:
    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))


def github_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    return headers


def default_headers() -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,text/html,*/*",
    }


def request_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    github: bool = False,
    timeout: int = 25,
) -> Optional[Any]:
    try:
        response = requests.get(
            url,
            params=params,
            headers=github_headers() if github else default_headers(),
            timeout=timeout,
        )

        if response.status_code in {403, 404, 429}:
            print(f"    ! {response.status_code}: {url}")
            return None

        response.raise_for_status()
        return response.json()

    except Exception as error:
        print(f"    ! request error: {error}")
        return None


def strings_from_any(value: Any, limit: int = 100_000) -> str:
    parts = []

    def walk(item: Any) -> None:
        if len(" ".join(parts)) > limit:
            return

        if item is None:
            return

        if isinstance(item, str):
            if item.strip():
                parts.append(item.strip())
            return

        if isinstance(item, (int, float, bool)):
            parts.append(str(item))
            return

        if isinstance(item, list):
            for child in item:
                walk(child)
            return

        if isinstance(item, dict):
            for child in item.values():
                walk(child)
            return

    walk(value)

    text = " ".join(parts)
    text = re.sub(r"\s+", " ", text)

    return text[:limit]


def get_context(text: str, value: str, window: int = 220) -> str:
    index = text.find(value)

    if index == -1:
        index = text.lower().find(value.lower())

    if index == -1:
        return ""

    start = max(0, index - window)
    end = min(len(text), index + len(value) + window)

    context = text[start:end]
    context = re.sub(r"\s+", " ", context)

    return context.strip()


def has_wallet_context(context: str) -> bool:
    lowered = context.lower()
    return any(word in lowered for word in WALLET_CONTEXT_WORDS)


def has_bad_context(context: str) -> bool:
    lowered = context.lower()
    return any(word in lowered for word in BAD_CONTEXT_WORDS)


def extract_wallets(text: str) -> List[Dict[str, Any]]:
    wallets = []
    seen = set()

    text = clean_text(text)

    for match in EVM_RE.finditer(text):
        value = match.group(0)
        context = get_context(text, value)

        if has_bad_context(context):
            continue

        key = ("evm", value.lower())

        if key in seen:
            continue

        seen.add(key)

        confidence = 90 if has_wallet_context(context) else 80

        wallets.append({
            "wallet_type": "evm",
            "wallet_address": value,
            "name_service": "",
            "chain": "ethereum",
            "confidence": confidence,
            "context": context,
        })

    for match in ENS_RE.finditer(text):
        value = match.group(0).lower()
        context = get_context(text, value)

        if has_bad_context(context):
            continue

        key = ("ens", value)

        if key in seen:
            continue

        seen.add(key)

        wallets.append({
            "wallet_type": "ens",
            "wallet_address": "",
            "name_service": value,
            "chain": "ethereum",
            "confidence": 75,
            "context": context,
        })

    for match in SOL_NAME_RE.finditer(text):
        value = match.group(0).lower()
        context = get_context(text, value)

        # .sol очень часто бывает Solidity-файлом.
        # Поэтому берём только если рядом есть wallet-context.
        if not has_wallet_context(context):
            continue

        if has_bad_context(context):
            continue

        key = ("sns_sol", value)

        if key in seen:
            continue

        seen.add(key)

        wallets.append({
            "wallet_type": "sns_sol",
            "wallet_address": "",
            "name_service": value,
            "chain": "solana",
            "confidence": 75,
            "context": context,
        })

    for match in SOLANA_CANDIDATE_RE.finditer(text):
        value = match.group(0)
        context = get_context(text, value)

        if not is_valid_solana_address(value):
            continue

        # Solana base58 очень шумный, поэтому обязательно нужен контекст.
        if not has_wallet_context(context):
            continue

        if has_bad_context(context):
            continue

        key = ("solana", value)

        if key in seen:
            continue

        seen.add(key)

        wallets.append({
            "wallet_type": "solana",
            "wallet_address": value,
            "name_service": "",
            "chain": "solana",
            "confidence": 85,
            "context": context,
        })

    return wallets


def fetch_candidates(client, limit: int) -> List[Dict[str, Any]]:
    response = (
        client
        .table("candidates")
        .select("*")
        .order("overall_trust_score", desc=True)
        .limit(limit)
        .execute()
    )

    return response.data or []


def fetch_candidate_by_id(client, candidate_id: int) -> Optional[Dict[str, Any]]:
    return SupabaseCandidateRepository(client).get_candidate(candidate_id)


def fetch_profiles(client, candidate_id: int) -> List[Dict[str, Any]]:
    return SupabaseCandidateRepository(client).list_profiles(candidate_id)


def wallet_exists(
    client,
    candidate_id: int,
    wallet_type: str,
    wallet_address: str,
    name_service: str,
) -> bool:
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


def insert_wallet_and_evidence(
    client,
    candidate_id: int,
    wallet: Dict[str, Any],
    source_platform: str,
    source_url: str,
) -> bool:
    wallet_type = clean_text(wallet.get("wallet_type"))
    wallet_address = clean_text(wallet.get("wallet_address"))
    name_service = clean_text(wallet.get("name_service"))
    chain = clean_text(wallet.get("chain"))
    confidence = int(wallet.get("confidence") or 0)
    context = clean_text(wallet.get("context"))

    if wallet_exists(
        client=client,
        candidate_id=candidate_id,
        wallet_type=wallet_type,
        wallet_address=wallet_address,
        name_service=name_service,
    ):
        return False

    wallet_payload = {
        "candidate_id": candidate_id,
        "wallet_type": wallet_type,
        "wallet_address": wallet_address,
        "name_service": name_service,
        "chain": chain,
        "confidence": confidence,
        "status": "probable_wallet" if confidence >= 85 else "possible_wallet",
        "evidence_url": source_url,
        "evidence_text": context[:1000],
        "evidence_type": "deep_public_scan",
    }

    (
        client
        .table("wallets")
        .insert(wallet_payload)
        .execute()
    )

    entity_value = wallet_address or name_service

    evidence_payload = {
        "candidate_id": candidate_id,
        "entity_type": f"{wallet_type}_wallet",
        "entity_value": entity_value,
        "source_platform": source_platform,
        "source_url": source_url,
        "evidence_text": context[:1000],
        "confidence": confidence,
    }

    (
        client
        .table("evidence")
        .insert(evidence_payload)
        .execute()
    )

    return True


def get_github_username(profile: Dict[str, Any]) -> str:
    platform = clean_text(profile.get("platform")).lower()

    if platform != "github":
        return ""

    username = clean_text(profile.get("username"))

    if username:
        return username

    profile_url = clean_text(profile.get("profile_url"))

    match = re.search(r"github\.com/([A-Za-z0-9_.-]+)", profile_url)

    if match:
        return match.group(1)

    return ""


def decode_github_content(data: Any) -> str:
    if not isinstance(data, dict):
        return ""

    content = data.get("content")
    encoding = data.get("encoding")

    if not content or encoding != "base64":
        return ""

    try:
        return base64.b64decode(content).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def github_fetch_readme(owner: str, repo: str) -> Tuple[str, str]:
    api_url = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/readme"

    data = request_json(api_url, github=True)
    polite_sleep()

    text = decode_github_content(data)

    html_url = ""

    if isinstance(data, dict):
        html_url = clean_text(data.get("html_url"))

    return text, html_url


def github_fetch_file(owner: str, repo: str, path: str, branch: str) -> Tuple[str, str]:
    api_url = (
        f"https://api.github.com/repos/"
        f"{quote(owner)}/{quote(repo)}/contents/{path}"
    )

    data = request_json(api_url, github=True)
    polite_sleep()

    text = decode_github_content(data)

    html_url = ""

    if isinstance(data, dict):
        html_url = clean_text(data.get("html_url"))

    if not html_url:
        html_url = f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"

    return text, html_url


def collect_github_sources(username: str) -> List[Tuple[str, str, str]]:
    """
    Returns list of:
        (source_platform, source_url, text)
    """
    sources = []

    if not username:
        return sources

    print(f"    [github deep] {username}")

    user_api = f"https://api.github.com/users/{quote(username)}"
    user_data = request_json(user_api, github=True)
    polite_sleep()

    if isinstance(user_data, dict):
        fields = [
            user_data.get("login"),
            user_data.get("name"),
            user_data.get("bio"),
            user_data.get("blog"),
            user_data.get("company"),
            user_data.get("email"),
            user_data.get("twitter_username"),
            user_data.get("html_url"),
        ]

        profile_text = " ".join(clean_text(item) for item in fields)

        sources.append((
            "github_profile",
            f"https://github.com/{username}",
            profile_text,
        ))

    # Profile README: repo with same name as username
    readme_text, readme_url = github_fetch_readme(username, username)

    if readme_text:
        sources.append((
            "github_profile_readme",
            readme_url or f"https://github.com/{username}/{username}",
            readme_text,
        ))

    repos_api = (
        f"https://api.github.com/users/{quote(username)}/repos"
        f"?sort=updated&per_page={MAX_GITHUB_REPOS_TO_SCAN}"
    )

    repos = request_json(repos_api, github=True)
    polite_sleep()

    if not isinstance(repos, list):
        return sources

    for repo in repos[:MAX_GITHUB_REPOS_TO_SCAN]:
        repo_name = clean_text(repo.get("name"))
        repo_url = clean_text(repo.get("html_url"))
        branch = clean_text(repo.get("default_branch")) or "main"

        if not repo_name:
            continue

        repo_text = " ".join([
            clean_text(repo.get("name")),
            clean_text(repo.get("description")),
            clean_text(repo.get("homepage")),
            repo_url,
        ])

        sources.append((
            "github_repo",
            repo_url,
            repo_text,
        ))

        readme_text, readme_url = github_fetch_readme(username, repo_name)

        if readme_text:
            sources.append((
                "github_readme",
                readme_url or repo_url,
                readme_text,
            ))

        for path in [
            ".github/FUNDING.yml",
            "FUNDING.yml",
        ]:
            file_text, file_url = github_fetch_file(username, repo_name, path, branch)

            if file_text:
                sources.append((
                    "github_funding",
                    file_url,
                    file_text,
                ))

    return sources


def discourse_base_from_platform(platform: str) -> str:
    platform = clean_text(platform)

    if not platform.startswith("discourse:"):
        return ""

    host = platform.replace("discourse:", "", 1).strip().strip("/")

    if not host:
        return ""

    if host.startswith("http"):
        return host.rstrip("/")

    return "https://" + host.rstrip("/")


def parse_discourse_topic_info(url: str) -> Tuple[str, str]:
    """
    Returns:
        topic_id, post_number
    """
    url = clean_text(url)

    if not url:
        return "", ""

    try:
        path = urlparse(url).path
    except Exception:
        return "", ""

    parts = [part for part in path.split("/") if part]

    if "t" not in parts:
        return "", ""

    t_index = parts.index("t")
    after_t = parts[t_index + 1:]

    numbers = [part for part in after_t if part.isdigit()]

    topic_id = numbers[0] if numbers else ""
    post_number = numbers[1] if len(numbers) > 1 else ""

    return topic_id, post_number


def collect_discourse_topic_source(
    base_url: str,
    username: str,
    source_url: str,
) -> List[Tuple[str, str, str]]:
    sources = []

    topic_id, post_number = parse_discourse_topic_info(source_url)

    if not topic_id:
        return sources

    topic_api = f"{base_url}/t/{topic_id}.json"

    data = request_json(topic_api)
    polite_sleep()

    if not isinstance(data, dict):
        return sources

    post_stream = data.get("post_stream") or {}
    posts = post_stream.get("posts") or []

    for post in posts:
        post_username = clean_text(post.get("username"))
        current_post_number = str(post.get("post_number") or "")

        is_author_post = post_username.lower() == username.lower()
        is_exact_post = post_number and current_post_number == post_number

        if not is_author_post and not is_exact_post:
            continue

        text = strings_from_any(post)

        exact_url = f"{base_url}/t/{topic_id}"

        if current_post_number:
            exact_url = f"{exact_url}/{current_post_number}"

        sources.append((
            "discourse_topic_json",
            exact_url,
            text,
        ))

    return sources


def collect_discourse_sources(profile: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    sources = []

    platform = clean_text(profile.get("platform"))
    username = clean_text(profile.get("username"))
    source_url = clean_text(profile.get("source_url"))
    profile_url = clean_text(profile.get("profile_url"))

    base_url = discourse_base_from_platform(platform)

    if not base_url or not username:
        return sources

    print(f"    [discourse deep] {base_url} / {username}")

    profile_api = f"{base_url}/u/{quote(username)}.json"
    profile_data = request_json(profile_api)
    polite_sleep()

    if isinstance(profile_data, dict):
        profile_text = strings_from_any(profile_data)
        sources.append((
            "discourse_profile_json",
            profile_url or f"{base_url}/u/{quote(username)}",
            profile_text,
        ))

    if source_url:
        sources.extend(
            collect_discourse_topic_source(
                base_url=base_url,
                username=username,
                source_url=source_url,
            )
        )

    search_terms = [
        "wallet",
        "address",
        "delegate address",
        "voting address",
        "ecosystem actor address",
        "multisig",
        "safe",
        "treasury",
        "ethereum",
        "solana",
        "ens",
        "0x",
    ]

    for term in search_terms[:MAX_DISCOURSE_SEARCHES_PER_USER]:
        query = f"{username} {term}"

        search_api = f"{base_url}/search.json"

        data = request_json(
            search_api,
            params={"q": query},
        )

        polite_sleep()

        if not isinstance(data, dict):
            continue

        posts = data.get("posts") or []

        for post in posts[:5]:
            post_username = clean_text(post.get("username"))
            topic_id = clean_text(post.get("topic_id"))
            post_number = clean_text(post.get("post_number"))

            # Берём только посты этого пользователя.
            if post_username.lower() != username.lower():
                continue

            text = strings_from_any(post)

            post_url = ""

            if topic_id:
                post_url = f"{base_url}/t/{topic_id}"

                if post_number:
                    post_url = f"{post_url}/{post_number}"

            sources.append((
                "discourse_search_post",
                post_url or source_url or profile_url,
                text,
            ))

    return sources


def insert_wallets_from_sources(
    client,
    candidate_id: int,
    sources: List[Tuple[str, str, str]],
) -> int:
    added = 0

    for source_platform, source_url, text in sources:
        wallets = extract_wallets(text)

        for wallet in wallets:
            if insert_wallet_and_evidence(
                client=client,
                candidate_id=candidate_id,
                wallet=wallet,
                source_platform=source_platform,
                source_url=source_url,
            ):
                value = wallet.get("wallet_address") or wallet.get("name_service")

                print(
                    f"      + wallet {wallet.get('wallet_type')} "
                    f"{value} confidence={wallet.get('confidence')}"
                )

                added += 1

    return added


def deep_enrich_candidate(client, candidate: Dict[str, Any]) -> int:
    candidate_id = int(candidate["id"])

    print("-" * 90)
    print(
        f"candidate_id={candidate_id} "
        f"username={candidate.get('main_username')} "
        f"status={candidate.get('status')}"
    )

    profiles = fetch_profiles(client, candidate_id)

    total_added = 0

    for profile in profiles:
        platform = clean_text(profile.get("platform")).lower()

        sources = []

        if platform == "github":
            github_username = get_github_username(profile)
            sources.extend(collect_github_sources(github_username))

        elif platform.startswith("discourse:"):
            sources.extend(collect_discourse_sources(profile))

        else:
            continue

        added = insert_wallets_from_sources(
            client=client,
            candidate_id=candidate_id,
            sources=sources,
        )

        total_added += added

    print(f"done candidate_id={candidate_id} wallets_added={total_added}")

    return total_added


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deep public wallet enrichment."
    )

    parser.add_argument(
        "--id",
        type=int,
        help="Deep-enrich one candidate by ID",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=WALLET_DEEP_LIMIT,
        help="How many top candidates to process",
    )

    args = parser.parse_args()

    client = get_supabase_client()

    print("=" * 90)
    print("Mirae Deep Wallet Enrichment")
    print("=" * 90)
    print(f"Limit: {args.limit}")
    print(f"Candidate ID: {args.id or 'not specified'}")
    print(f"GitHub token present: {bool(GITHUB_TOKEN)}")
    print("=" * 90)

    if args.id:
        candidate = fetch_candidate_by_id(client, args.id)

        if not candidate:
            print(f"Candidate not found: {args.id}")
            return

        candidates = [candidate]

    else:
        candidates = fetch_candidates(client, args.limit)

    total_added = 0

    for candidate in candidates:
        total_added += deep_enrich_candidate(client, candidate)

    print("=" * 90)
    print("Deep wallet enrichment finished")
    print(f"Candidates processed: {len(candidates)}")
    print(f"Wallets added: {total_added}")
    print("=" * 90)


if __name__ == "__main__":
    main()
