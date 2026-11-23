#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mirae Web3 Candidate Enrichment → Supabase.

Что делает:
- Берёт кандидатов из Supabase.
- Читает их profiles/profile_url/source_url.
- Для GitHub дополнительно читает GitHub API profile + README последних реп.
- Ищет:
    email
    website
    X/Twitter
    LinkedIn
    GitHub
    EVM wallets
    Solana wallets
    ENS
    .sol names
- Пишет найденное в contacts, wallets, evidence.
- Пересчитывает score кандидата.

Запуск:
    python3 enrich_to_supabase.py

Опционально:
    python3 enrich_to_supabase.py --limit 10
    python3 enrich_to_supabase.py --id 123
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

from crycon.config import load_settings
from crycon.scoring import calculate_enrichment_scores
from db_supabase import get_supabase_client, clean_text

settings = load_settings()

SLEEP_MIN = settings.number("SLEEP_MIN", 1.0)
SLEEP_MAX = settings.number("SLEEP_MAX", 2.0)

ENRICH_LIMIT = settings.integer("ENRICH_LIMIT", 30)
MAX_GITHUB_REPOS_TO_SCAN = settings.integer("MAX_GITHUB_REPOS_TO_SCAN", 3)

GITHUB_TOKEN = settings.text("GITHUB_TOKEN")

USER_AGENT = "Mirae-Web3-Enrichment"

MAX_TEXT_CHARS_PER_PAGE = 200_000


# =========================
# REGEX
# =========================

EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"(?![A-Za-z0-9._%+-])"
)

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

URL_RE = re.compile(
    r"https?://[^\s\"'<>]+",
    re.IGNORECASE,
)

X_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})(?:[/?#][^\s\"'<>]*)?",
    re.IGNORECASE,
)

LINKEDIN_URL_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/(?:in|company)/[A-Za-z0-9_.%-]+/?",
    re.IGNORECASE,
)

GITHUB_URL_RE = re.compile(
    r"https?://(?:www\.)?github\.com/[A-Za-z0-9_.-]+/?",
    re.IGNORECASE,
)


# =========================
# HELPERS
# =========================

def polite_sleep() -> None:
    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))


def normalize_url(url: str) -> str:
    url = clean_text(url)

    if not url:
        return ""

    return url.rstrip(").,;\"'")


def is_probably_personal_website(url: str) -> bool:
    url = normalize_url(url)

    if not url:
        return False

    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    if not domain or "." not in domain:
        return False

    # Служебные / технические домены
    bad_domains = [
        "schema.org",
        "w3.org",
        "cloudflareinsights.com",
        "googletagmanager.com",
        "google-analytics.com",
        "googleapis.com",
        "gstatic.com",
        "sentry.io",
        "discourse.org",
        "github.com/discourse",
        "makerdao-forum-backup.s3",
    ]

    if any(bad in domain for bad in bad_domains):
        return False

    # Внутренние форумные домены не считаем personal website.
    # Они уже есть как profile_url/source_url.
    forum_domains = [
        "forum.makerdao.com",
        "forum.skyeco.com",
        "gov.uniswap.org",
        "forum.arbitrum.foundation",
        "governance.aave.com",
        "research.lido.fi",
        "discuss.ens.domains",
    ]

    if any(forum in domain for forum in forum_domains):
        return False

    # Соцсети / explorer / платформы не кладём как website.
    # Для них есть отдельные contact_type.
    platform_domains = [
        "github.com",
        "x.com",
        "twitter.com",
        "linkedin.com",
        "discord.gg",
        "t.me",
        "telegram.me",
        "etherscan.io",
        "solscan.io",
        "basescan.org",
        "arbiscan.io",
        "polygonscan.com",
        "optimistic.etherscan.io",
        "medium.com",
        "mirror.xyz",
    ]

    if any(platform in domain for platform in platform_domains):
        return False

    # Ассеты не считаем сайтами
    bad_extensions = [
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".ico",
        ".css",
        ".js",
        ".xml",
        ".rss",
        ".json",
        ".map",
        ".woff",
        ".woff2",
    ]

    if any(path.endswith(ext) for ext in bad_extensions):
        return False

    return True
    url = normalize_url(url)

    if not url:
        return False

    parsed = urlparse(url)

    domain = parsed.netloc.lower()

    bad_domains = [
        "github.com",
        "x.com",
        "twitter.com",
        "linkedin.com",
        "discord.gg",
        "t.me",
        "telegram.me",
        "etherscan.io",
        "solscan.io",
        "medium.com",
        "mirror.xyz",
    ]

    if any(bad in domain for bad in bad_domains):
        return False

    if "." not in domain:
        return False

    return True


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
        "Accept": "text/html,application/json,text/plain,*/*",
    }


def fetch_text(url: str, timeout: int = 20) -> str:
    url = normalize_url(url)

    if not url.startswith("http"):
        return ""

    try:
        response = requests.get(
            url,
            headers=default_headers(),
            timeout=timeout,
        )

        if response.status_code in {403, 404, 429}:
            return ""

        response.raise_for_status()

        text = response.text or ""

        return text[:MAX_TEXT_CHARS_PER_PAGE]

    except requests.RequestException:
        return ""


def fetch_json(url: str, timeout: int = 20) -> Optional[Any]:
    try:
        response = requests.get(
            url,
            headers=github_headers(),
            timeout=timeout,
        )

        if response.status_code in {403, 404, 429}:
            return None

        response.raise_for_status()

        return response.json()

    except requests.RequestException:
        return None
    except ValueError:
        return None


def is_bad_email(email: str) -> bool:
    email = email.lower()

    bad_fragments = [
        "example.com",
        "test.com",
        "your@email",
        "email.com",
        "sentry.io",
        "w3.org",
        "schema.org",
    ]

    return any(fragment in email for fragment in bad_fragments)


def is_bad_wallet_context(text: str, wallet: str) -> bool:
    """
    Отсекаем очевидные test/example контексты.
    """
    index = text.find(wallet)

    if index == -1:
        return False

    start = max(0, index - 120)
    end = min(len(text), index + len(wallet) + 120)

    context = text[start:end].lower()

    bad_words = [
        "example",
        "sample",
        "test address",
        "testnet",
        "dummy",
        "placeholder",
        "fake",
    ]

    return any(word in context for word in bad_words)


def get_context(text: str, value: str, window: int = 180) -> str:
    index = text.find(value)

    if index == -1:
        return ""

    start = max(0, index - window)
    end = min(len(text), index + len(value) + window)

    context = text[start:end]
    context = re.sub(r"\s+", " ", context)

    return context.strip()


# =========================
# EXTRACTION
# =========================

def extract_artifacts(text: str, include_websites: bool = True) -> Dict[str, Set[str]]:
    text = clean_text(text)

    emails = set()
    websites = set()
    x_urls = set()
    linkedin_urls = set()
    github_urls = set()

    evm_wallets = set()
    solana_wallets = set()
    ens_names = set()
    sol_names = set()

    for email in EMAIL_RE.findall(text):
        email = email.lower()

        if not is_bad_email(email):
            emails.add(email)

    if include_websites:
        for url in URL_RE.findall(text):
            url = normalize_url(url)

            if not url:
                continue

            if is_probably_personal_website(url):
                websites.add(url)

    for match in X_URL_RE.findall(text):
        handle = match.strip().lstrip("@")

        if handle.lower() not in {"home", "search", "share", "intent"}:
            x_urls.add(f"https://x.com/{handle}")

    for url in LINKEDIN_URL_RE.findall(text):
        linkedin_urls.add(normalize_url(url))

    for url in GITHUB_URL_RE.findall(text):
        url = normalize_url(url)

        if "github.com/discourse" in url.lower():
            continue

        github_urls.add(url)

    for wallet in EVM_RE.findall(text):
        if not is_bad_wallet_context(text, wallet):
            evm_wallets.add(wallet)

    for name in ENS_RE.findall(text):
        ens_names.add(name.lower())

    for name in SOL_NAME_RE.findall(text):
        sol_names.add(name.lower())

    for candidate in SOLANA_CANDIDATE_RE.findall(text):
        if is_valid_solana_address(candidate):
            if not is_bad_wallet_context(text, candidate):
                solana_wallets.add(candidate)

    return {
        "emails": emails,
        "websites": websites,
        "x_urls": x_urls,
        "linkedin_urls": linkedin_urls,
        "github_urls": github_urls,
        "evm_wallets": evm_wallets,
        "solana_wallets": solana_wallets,
        "ens_names": ens_names,
        "sol_names": sol_names,
    }


def merge_artifacts(target: Dict[str, Set[str]], source: Dict[str, Set[str]]) -> None:
    for key, values in source.items():
        if key not in target:
            target[key] = set()

        target[key].update(values)


def empty_artifacts() -> Dict[str, Set[str]]:
    return {
        "emails": set(),
        "websites": set(),
        "x_urls": set(),
        "linkedin_urls": set(),
        "github_urls": set(),
        "evm_wallets": set(),
        "solana_wallets": set(),
        "ens_names": set(),
        "sol_names": set(),
    }


# =========================
# SUPABASE READ
# =========================

def get_candidates_to_enrich(client, limit: int) -> List[Dict[str, Any]]:
    response = (
        client
        .table("candidates")
        .select("*")
        .order("overall_trust_score", desc=True)
        .limit(limit)
        .execute()
    )

    return response.data or []


def get_candidate_by_id(client, candidate_id: int) -> Optional[Dict[str, Any]]:
    response = (
        client
        .table("candidates")
        .select("*")
        .eq("id", candidate_id)
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def get_profiles_for_candidate(client, candidate_id: int) -> List[Dict[str, Any]]:
    response = (
        client
        .table("profiles")
        .select("*")
        .eq("candidate_id", candidate_id)
        .execute()
    )

    return response.data or []


# =========================
# SUPABASE WRITE
# =========================

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


def wallet_exists(
    client,
    candidate_id: int,
    wallet_type: str,
    wallet_address: str = "",
    name_service: str = "",
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


def insert_contact(
    client,
    candidate_id: int,
    contact_type: str,
    value: str,
    confidence: int,
    status: str,
    evidence_url: str,
    evidence_text: str,
) -> bool:
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
        "status": status,
        "evidence_url": evidence_url,
        "evidence_text": evidence_text[:1000] if evidence_text else "",
    }

    (
        client
        .table("contacts")
        .insert(payload)
        .execute()
    )

    return True


def insert_wallet(
    client,
    candidate_id: int,
    wallet_type: str,
    wallet_address: str,
    name_service: str,
    chain: str,
    confidence: int,
    status: str,
    evidence_url: str,
    evidence_text: str,
) -> bool:
    wallet_address = clean_text(wallet_address)
    name_service = clean_text(name_service)

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
        "status": status,
        "evidence_url": evidence_url,
        "evidence_text": evidence_text[:1000] if evidence_text else "",
        "evidence_type": "public_text",
    }

    (
        client
        .table("wallets")
        .insert(payload)
        .execute()
    )

    return True


def insert_evidence(
    client,
    candidate_id: int,
    entity_type: str,
    entity_value: str,
    source_platform: str,
    source_url: str,
    evidence_text: str,
    confidence: int,
) -> None:
    payload = {
        "candidate_id": candidate_id,
        "entity_type": entity_type,
        "entity_value": entity_value,
        "source_platform": source_platform,
        "source_url": source_url,
        "evidence_text": evidence_text[:1000] if evidence_text else "",
        "confidence": confidence,
    }

    (
        client
        .table("evidence")
        .insert(payload)
        .execute()
    )


def update_candidate_scores(client, candidate_id: int) -> None:
    candidate_response = (
        client
        .table("candidates")
        .select("*")
        .eq("id", candidate_id)
        .limit(1)
        .execute()
    )

    if not candidate_response.data:
        return

    candidate = candidate_response.data[0]

    profiles = (
        client
        .table("profiles")
        .select("*")
        .eq("candidate_id", candidate_id)
        .execute()
    ).data or []

    contacts = (
        client
        .table("contacts")
        .select("*")
        .eq("candidate_id", candidate_id)
        .execute()
    ).data or []

    wallets = (
        client
        .table("wallets")
        .select("*")
        .eq("candidate_id", candidate_id)
        .execute()
    ).data or []

    scores = calculate_enrichment_scores(candidate, profiles, contacts, wallets)
    (
        client
        .table("candidates")
        .update(scores)
        .eq("id", candidate_id)
        .execute()
    )


# =========================
# GITHUB ENRICHMENT
# =========================

def get_github_username_from_profile(profile: Dict[str, Any]) -> str:
    if profile.get("platform") != "github":
        return ""

    username = clean_text(profile.get("username"))

    if username:
        return username

    url = clean_text(profile.get("profile_url"))

    match = re.search(r"github\.com/([A-Za-z0-9_.-]+)", url)

    if match:
        return match.group(1)

    return ""


def collect_github_text(username: str) -> Tuple[str, Set[str]]:
    text_parts = []
    evidence_urls = set()

    if not username:
        return "", evidence_urls

    user_api = f"https://api.github.com/users/{quote(username)}"

    user_data = fetch_json(user_api)

    polite_sleep()

    if isinstance(user_data, dict):
        github_url = f"https://github.com/{username}"
        evidence_urls.add(github_url)

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

        text_parts.append(" ".join(clean_text(item) for item in fields))

        twitter_username = clean_text(user_data.get("twitter_username"))

        if twitter_username:
            text_parts.append(f"https://x.com/{twitter_username}")

        blog = clean_text(user_data.get("blog"))

        if blog:
            if not blog.startswith("http"):
                blog = "https://" + blog

            text_parts.append(blog)

    repos_api = (
        f"https://api.github.com/users/{quote(username)}/repos"
        f"?sort=updated&per_page={MAX_GITHUB_REPOS_TO_SCAN}"
    )

    repos = fetch_json(repos_api)

    polite_sleep()

    if isinstance(repos, list):
        for repo in repos[:MAX_GITHUB_REPOS_TO_SCAN]:
            repo_name = clean_text(repo.get("name"))
            repo_url = clean_text(repo.get("html_url"))

            repo_text = " ".join([
                clean_text(repo.get("name")),
                clean_text(repo.get("description")),
                clean_text(repo.get("homepage")),
                repo_url,
            ])

            text_parts.append(repo_text)

            if repo_url:
                evidence_urls.add(repo_url)

            if not repo_name:
                continue

            readme_api = (
                f"https://api.github.com/repos/"
                f"{quote(username)}/{quote(repo_name)}/readme"
            )

            readme_data = fetch_json(readme_api)

            polite_sleep()

            if not isinstance(readme_data, dict):
                continue

            content = readme_data.get("content", "")
            encoding = readme_data.get("encoding", "")

            if content and encoding == "base64":
                try:
                    decoded = base64.b64decode(content).decode(
                        "utf-8",
                        errors="ignore",
                    )
                    text_parts.append(decoded[:MAX_TEXT_CHARS_PER_PAGE])

                    if repo_url:
                        evidence_urls.add(repo_url)

                except Exception:
                    pass

    return "\n".join(text_parts), evidence_urls


# =========================
# MAIN ENRICH
# =========================

def save_artifacts_for_candidate(
    client,
    candidate_id: int,
    artifacts: Dict[str, Set[str]],
    evidence_url: str,
    full_text: str,
) -> Dict[str, int]:
    stats = {
        "contacts": 0,
        "wallets": 0,
        "evidence": 0,
    }

    for email in artifacts["emails"]:
        context = get_context(full_text, email)

        if insert_contact(
            client=client,
            candidate_id=candidate_id,
            contact_type="email",
            value=email,
            confidence=80,
            status="probable",
            evidence_url=evidence_url,
            evidence_text=context,
        ):
            stats["contacts"] += 1
            insert_evidence(
                client,
                candidate_id,
                "email",
                email,
                "enrichment",
                evidence_url,
                context,
                80,
            )
            stats["evidence"] += 1

    for website in artifacts["websites"]:
        context = get_context(full_text, website)

        if insert_contact(
            client,
            candidate_id,
            "website",
            website,
            75,
            "probable",
            evidence_url,
            context,
        ):
            stats["contacts"] += 1
            insert_evidence(
                client,
                candidate_id,
                "website",
                website,
                "enrichment",
                evidence_url,
                context,
                75,
            )
            stats["evidence"] += 1

    for x_url in artifacts["x_urls"]:
        context = get_context(full_text, x_url)

        if insert_contact(
            client,
            candidate_id,
            "x",
            x_url,
            75,
            "probable",
            evidence_url,
            context,
        ):
            stats["contacts"] += 1
            insert_evidence(
                client,
                candidate_id,
                "x",
                x_url,
                "enrichment",
                evidence_url,
                context,
                75,
            )
            stats["evidence"] += 1

    for linkedin_url in artifacts["linkedin_urls"]:
        context = get_context(full_text, linkedin_url)

        if insert_contact(
            client,
            candidate_id,
            "linkedin",
            linkedin_url,
            70,
            "probable",
            evidence_url,
            context,
        ):
            stats["contacts"] += 1
            insert_evidence(
                client,
                candidate_id,
                "linkedin",
                linkedin_url,
                "enrichment",
                evidence_url,
                context,
                70,
            )
            stats["evidence"] += 1

    for github_url in artifacts["github_urls"]:
        context = get_context(full_text, github_url)

        if insert_contact(
            client,
            candidate_id,
            "github",
            github_url,
            70,
            "probable",
            evidence_url,
            context,
        ):
            stats["contacts"] += 1
            insert_evidence(
                client,
                candidate_id,
                "github",
                github_url,
                "enrichment",
                evidence_url,
                context,
                70,
            )
            stats["evidence"] += 1

    for wallet in artifacts["evm_wallets"]:
        context = get_context(full_text, wallet)

        if insert_wallet(
            client,
            candidate_id,
            "evm",
            wallet,
            "",
            "ethereum",
            85,
            "possible_wallet",
            evidence_url,
            context,
        ):
            stats["wallets"] += 1
            insert_evidence(
                client,
                candidate_id,
                "evm_wallet",
                wallet,
                "enrichment",
                evidence_url,
                context,
                85,
            )
            stats["evidence"] += 1

    for wallet in artifacts["solana_wallets"]:
        context = get_context(full_text, wallet)

        if insert_wallet(
            client,
            candidate_id,
            "solana",
            wallet,
            "",
            "solana",
            85,
            "possible_wallet",
            evidence_url,
            context,
        ):
            stats["wallets"] += 1
            insert_evidence(
                client,
                candidate_id,
                "solana_wallet",
                wallet,
                "enrichment",
                evidence_url,
                context,
                85,
            )
            stats["evidence"] += 1

    for ens_name in artifacts["ens_names"]:
        context = get_context(full_text, ens_name)

        if insert_wallet(
            client,
            candidate_id,
            "ens",
            "",
            ens_name,
            "ethereum",
            75,
            "possible_wallet",
            evidence_url,
            context,
        ):
            stats["wallets"] += 1
            insert_evidence(
                client,
                candidate_id,
                "ens",
                ens_name,
                "enrichment",
                evidence_url,
                context,
                75,
            )
            stats["evidence"] += 1

    for sol_name in artifacts["sol_names"]:
        context = get_context(full_text, sol_name)

        if insert_wallet(
            client,
            candidate_id,
            "sns_sol",
            "",
            sol_name,
            "solana",
            75,
            "possible_wallet",
            evidence_url,
            context,
        ):
            stats["wallets"] += 1
            insert_evidence(
                client,
                candidate_id,
                "sol_name",
                sol_name,
                "enrichment",
                evidence_url,
                context,
                75,
            )
            stats["evidence"] += 1

    return stats


def enrich_candidate(client, candidate: Dict[str, Any]) -> Dict[str, int]:
    candidate_id = int(candidate["id"])

    profiles = get_profiles_for_candidate(client, candidate_id)

    total_stats = {
        "contacts": 0,
        "wallets": 0,
        "evidence": 0,
    }

    print("-" * 90)
    print(
        f"Enriching candidate_id={candidate_id} "
        f"username={candidate.get('main_username')} "
        f"status={candidate.get('status')}"
    )

    for profile in profiles:
        platform = clean_text(profile.get("platform"))
        profile_url = clean_text(profile.get("profile_url"))
        source_url = clean_text(profile.get("source_url"))

        base_text = " ".join([
            clean_text(candidate.get("main_username")),
            clean_text(candidate.get("display_name")),
            clean_text(candidate.get("bio")),
            clean_text(profile.get("username")),
            clean_text(profile.get("display_name")),
            clean_text(profile.get("bio")),
            profile_url,
            source_url,
        ])

        artifacts = empty_artifacts()
        merge_artifacts(artifacts, extract_artifacts(base_text, include_websites=True))

        evidence_url = source_url or profile_url or ""

        full_text_for_context = base_text

        for url in [profile_url, source_url]:
            if not url:
                continue

            page_text = fetch_text(url)
            polite_sleep()

            if page_text:
                # Из полного HTML страницы НЕ достаём websites,
                # иначе получаем schema.org, png, rss, js и другой мусор.
                # Но email/X/LinkedIn/wallets из страницы всё ещё достаём.
                merge_artifacts(artifacts, extract_artifacts(page_text, include_websites=False))
                full_text_for_context += "\n" + page_text
                evidence_url = url

        github_username = get_github_username_from_profile(profile)

        if github_username:
            github_text, github_evidence_urls = collect_github_text(github_username)

            if github_text:
                # Из GitHub API/README можно доставать websites:
                # blog/homepage часто реально полезные.
                merge_artifacts(artifacts, extract_artifacts(github_text, include_websites=True))
                full_text_for_context += "\n" + github_text

            if github_evidence_urls:
                evidence_url = sorted(github_evidence_urls)[0]

        stats = save_artifacts_for_candidate(
            client=client,
            candidate_id=candidate_id,
            artifacts=artifacts,
            evidence_url=evidence_url,
            full_text=full_text_for_context,
        )

        for key, value in stats.items():
            total_stats[key] += value

    update_candidate_scores(client, candidate_id)

    print(
        f"Done candidate_id={candidate_id} | "
        f"contacts+{total_stats['contacts']} "
        f"wallets+{total_stats['wallets']} "
        f"evidence+{total_stats['evidence']}"
    )

    return total_stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich Mirae candidates with contacts/wallets."
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=ENRICH_LIMIT,
        help="How many top candidates to enrich",
    )

    parser.add_argument(
        "--id",
        type=int,
        help="Enrich exact candidate ID",
    )

    args = parser.parse_args()

    client = get_supabase_client()

    print("=" * 90)
    print("Mirae Enrichment → Supabase")
    print("=" * 90)
    print(f"Limit: {args.limit}")
    print(f"Candidate ID: {args.id or 'not specified'}")
    print(f"GitHub token present: {bool(GITHUB_TOKEN)}")
    print("=" * 90)

    if args.id:
        candidate = get_candidate_by_id(client, args.id)

        if not candidate:
            print(f"Candidate not found: {args.id}")
            return

        candidates = [candidate]

    else:
        candidates = get_candidates_to_enrich(client, args.limit)

    total_contacts = 0
    total_wallets = 0
    total_evidence = 0

    for candidate in candidates:
        stats = enrich_candidate(client, candidate)

        total_contacts += stats["contacts"]
        total_wallets += stats["wallets"]
        total_evidence += stats["evidence"]

    print("=" * 90)
    print("Enrichment finished")
    print(f"Candidates processed: {len(candidates)}")
    print(f"Contacts added: {total_contacts}")
    print(f"Wallets added: {total_wallets}")
    print(f"Evidence added: {total_evidence}")
    print("=" * 90)


if __name__ == "__main__":
    main()
