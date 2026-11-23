#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import re
import time
import random
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

from crycon.config import load_settings
from crycon.jobs import run_next_job
from crycon.supabase_jobs import SupabaseParserJobRepository
from db_supabase import (
    get_supabase_client,
    insert_candidate_with_profile_and_evidence,
)


DEFAULT_KEYWORDS = [
    "Solana validator",
    "governance delegate",
    "DAO governance",
    "DeFi governance",
    "staking validator",
]

DEFAULT_DISCOURSE_FORUMS = [
    "https://gov.uniswap.org",
    "https://forum.arbitrum.foundation",
    "https://governance.aave.com",
    "https://forum.makerdao.com",
    "https://research.lido.fi",
    "https://discuss.ens.domains",
]

DEFAULT_SOURCES = [
    "github",
    "discourse",
]


settings = load_settings()
env_list = settings.list
env_int = settings.integer
env_float = settings.number


KEYWORDS = env_list("KEYWORDS", DEFAULT_KEYWORDS)
SOURCES = [source.lower() for source in env_list("SOURCES", DEFAULT_SOURCES)]

DISCOURSE_FORUMS = env_list("DISCOURSE_FORUMS", DEFAULT_DISCOURSE_FORUMS)

MAX_RESULTS = min(env_int("MAX_RESULTS", 50), 500)
MAX_PER_KEYWORD_PER_SOURCE = env_int("MAX_PER_KEYWORD_PER_SOURCE", 10)

SLEEP_MIN = env_float("SLEEP_MIN", 1.0)
SLEEP_MAX = env_float("SLEEP_MAX", 2.0)

GITHUB_TOKEN = settings.text("GITHUB_TOKEN")

USER_AGENT = "Mirae-Web3-Trust-Discovery"


def polite_sleep() -> None:
    time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def request_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 20,
) -> Optional[Dict[str, Any]]:
    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=timeout,
        )

        if response.status_code == 403:
            print(f"    ! Forbidden/rate limit: {url}")
            return None

        if response.status_code == 404:
            print(f"    ! Not found: {url}")
            return None

        if response.status_code == 429:
            print(f"    ! Rate limited: {url}")
            return None

        response.raise_for_status()

        return response.json()

    except requests.RequestException as error:
        print(f"    ! Request error: {error}")
        return None

    except ValueError:
        print(f"    ! Invalid JSON from: {url}")
        return None


def github_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    return headers


def github_search_users(keyword: str) -> List[Dict[str, Any]]:
    print(f"[github] Searching users: {keyword!r}")

    url = "https://api.github.com/search/users"

    params = {
        "q": f"{keyword} type:user",
        "per_page": min(MAX_PER_KEYWORD_PER_SOURCE, 30),
    }

    data = request_json(
        url=url,
        params=params,
        headers=github_headers(),
    )

    if not data:
        return []

    records = []

    for item in data.get("items", []):
        login = item.get("login")

        if not login:
            continue

        detail_url = f"https://api.github.com/users/{login}"

        detail = request_json(
            url=detail_url,
            headers=github_headers(),
        )

        polite_sleep()

        if not detail:
            continue

        if detail.get("type") != "User":
            continue

        record = {
            "source": "github",
            "username": detail.get("login", ""),
            "display_name": clean_text(detail.get("name", "")),
            "bio": clean_text(detail.get("bio", "")),
            "location": clean_text(detail.get("location", "")),
            "followers_count": detail.get("followers", ""),
            "activity_count": detail.get("public_repos", ""),
            "created_at": detail.get("created_at", ""),
            "profile_url": detail.get("html_url", ""),
            "matched_keyword": keyword,
            "source_url": detail.get("html_url", ""),
        }

        records.append(record)

    return records


def github_search_repositories_and_owners(keyword: str) -> List[Dict[str, Any]]:
    print(f"[github] Searching repos: {keyword!r}")

    url = "https://api.github.com/search/repositories"

    params = {
        "q": f"{keyword} in:name,description,readme",
        "per_page": min(MAX_PER_KEYWORD_PER_SOURCE, 30),
        "sort": "stars",
        "order": "desc",
    }

    data = request_json(
        url=url,
        params=params,
        headers=github_headers(),
    )

    if not data:
        return []

    owner_logins = []

    for repo in data.get("items", []):
        owner = repo.get("owner") or {}

        if owner.get("type") != "User":
            continue

        login = owner.get("login")

        if login and login not in owner_logins:
            owner_logins.append(login)

    records = []

    for login in owner_logins:
        detail_url = f"https://api.github.com/users/{login}"

        detail = request_json(
            url=detail_url,
            headers=github_headers(),
        )

        polite_sleep()

        if not detail:
            continue

        if detail.get("type") != "User":
            continue

        record = {
            "source": "github",
            "username": detail.get("login", ""),
            "display_name": clean_text(detail.get("name", "")),
            "bio": clean_text(detail.get("bio", "")),
            "location": clean_text(detail.get("location", "")),
            "followers_count": detail.get("followers", ""),
            "activity_count": detail.get("public_repos", ""),
            "created_at": detail.get("created_at", ""),
            "profile_url": detail.get("html_url", ""),
            "matched_keyword": keyword,
            "source_url": detail.get("html_url", ""),
        }

        records.append(record)

    return records


def normalize_base_url(url: str) -> str:
    return url.strip().rstrip("/")


def discourse_get_user_profile(
    base_url: str,
    username: str,
) -> Optional[Dict[str, Any]]:
    profile_url = f"{normalize_base_url(base_url)}/u/{quote(username)}.json"

    return request_json(
        url=profile_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )


def discourse_search_forum(base_url: str, keyword: str) -> List[Dict[str, Any]]:
    base_url = normalize_base_url(base_url)

    print(f"[discourse] Searching {base_url}: {keyword!r}")

    search_url = f"{base_url}/search.json"

    data = request_json(
        url=search_url,
        params={"q": keyword},
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    if not data:
        return []

    posts = data.get("posts", [])

    if not posts:
        print("    ! No posts found.")
        return []

    records = []
    seen_users = set()

    for post in posts[:MAX_PER_KEYWORD_PER_SOURCE]:
        username = post.get("username")

        if not username:
            continue

        if username.lower() in seen_users:
            continue

        seen_users.add(username.lower())

        profile = discourse_get_user_profile(base_url, username)
        polite_sleep()

        user_data = {}

        if profile:
            user_data = profile.get("user", {}) or {}

        topic_id = post.get("topic_id", "")
        post_number = post.get("post_number", "")

        source_url = ""

        if topic_id:
            source_url = f"{base_url}/t/{topic_id}"

            if post_number:
                source_url = f"{source_url}/{post_number}"

        bio = (
            user_data.get("bio_excerpt")
            or user_data.get("bio_raw")
            or post.get("blurb")
            or ""
        )

        display_name = (
            user_data.get("name")
            or post.get("name")
            or username
        )

        record = {
            "source": f"discourse:{base_url.replace('https://', '').replace('http://', '')}",
            "username": username,
            "display_name": clean_text(display_name),
            "bio": clean_text(bio),
            "location": clean_text(user_data.get("location", "")),
            "followers_count": "",
            "activity_count": user_data.get("post_count") or user_data.get("profile_view_count") or "",
            "created_at": user_data.get("created_at", ""),
            "profile_url": f"{base_url}/u/{quote(username)}",
            "matched_keyword": keyword,
            "source_url": source_url,
        }

        records.append(record)

    return records


def save_record_to_supabase(client, record: Dict[str, Any]) -> str:
    result = insert_candidate_with_profile_and_evidence(client, record)

    status = result.get("status")

    if status == "created":
        print(
            f"  + created {record.get('source')}:{record.get('username')} "
            f"candidate_id={result.get('candidate_id')} "
            f"score={result.get('relevance_score')}"
        )

    elif status == "exists":
        print(
            f"  = exists {record.get('source')}:{record.get('username')} "
            f"candidate_id={result.get('candidate_id')}"
        )

    else:
        print(
            f"  - skipped {record.get('source')}:{record.get('username')} "
            f"reason={result.get('reason')}"
        )

    return status


def run_discovery(client, keywords: List[str], heartbeat=None) -> int:
    created_count = 0
    seen_count = 0
    skipped_count = 0
    processed_count = 0

    for keyword in keywords:
        if heartbeat is not None and not heartbeat():
            raise RuntimeError("parser job lease lost")
        if created_count >= MAX_RESULTS:
            break

        if "github" in SOURCES:
            github_records = []

            github_records.extend(github_search_users(keyword))
            polite_sleep()

            github_records.extend(github_search_repositories_and_owners(keyword))
            polite_sleep()

            for record in github_records:
                if created_count >= MAX_RESULTS:
                    break

                status = save_record_to_supabase(client, record)
                processed_count += 1

                if status == "created":
                    created_count += 1
                elif status == "exists":
                    seen_count += 1
                else:
                    skipped_count += 1

        if "discourse" in SOURCES:
            for forum in DISCOURSE_FORUMS:
                if heartbeat is not None and not heartbeat():
                    raise RuntimeError("parser job lease lost")
                if created_count >= MAX_RESULTS:
                    break

                records = discourse_search_forum(forum, keyword)

                for record in records:
                    if created_count >= MAX_RESULTS:
                        break

                    status = save_record_to_supabase(client, record)
                    processed_count += 1

                    if status == "created":
                        created_count += 1
                    elif status == "exists":
                        seen_count += 1
                    else:
                        skipped_count += 1

                polite_sleep()

    print("=" * 72)
    print("Discovery finished")
    print(f"Processed: {processed_count}")
    print(f"Created: {created_count}")
    print(f"Already existed: {seen_count}")
    print(f"Skipped: {skipped_count}")
    print("=" * 72)
    return created_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one durable discovery job.")
    parser.add_argument(
        "--idempotency-key",
        default=f"manual-{uuid.uuid4().hex}",
        help="Reuse the same value to avoid enqueueing the same request twice",
    )
    parser.add_argument(
        "--worker-id",
        default=f"discovery-cli-{uuid.uuid4().hex[:12]}",
        help="Lease owner shown in parser_jobs",
    )
    parser.add_argument(
        "--worker-only",
        action="store_true",
        help="Claim one queued discovery job without enqueueing a new one",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("Mirae Web3 Discovery → Supabase")
    print("=" * 72)
    print(f"Sources: {SOURCES}")
    print(f"Keywords: {KEYWORDS}")
    print(f"Discourse forums: {DISCOURSE_FORUMS}")
    print(f"MAX_RESULTS: {MAX_RESULTS}")
    print(f"MAX_PER_KEYWORD_PER_SOURCE: {MAX_PER_KEYWORD_PER_SOURCE}")
    print(f"GitHub token present: {bool(GITHUB_TOKEN)}")
    print("=" * 72)

    client = get_supabase_client()
    jobs = SupabaseParserJobRepository(client)
    if not args.worker_only:
        jobs.enqueue_job(
            job_type="discovery",
            query=" | ".join(KEYWORDS),
            idempotency_key=args.idempotency_key,
        )

    def handle(job: Dict[str, Any]) -> int:
        keywords = [
            item.strip()
            for item in str(job.get("query") or "").split("|")
            if item.strip()
        ] or list(KEYWORDS)
        job_id = int(job["id"])
        return run_discovery(
            client,
            keywords,
            heartbeat=lambda: jobs.heartbeat_job(job_id, args.worker_id),
        )

    outcome = run_next_job(jobs, args.worker_id, handle)
    if outcome is None:
        print("No queued discovery jobs.")
    else:
        print(f"Job {outcome.job_id}: {outcome.status}")


if __name__ == "__main__":
    main()
