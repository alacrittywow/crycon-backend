"""Legacy contact eligibility rules used by score recalculation."""
from typing import Any, Dict, List
from urllib.parse import urlparse

from .text import clean_text


BAD_CONTACT_FRAGMENTS = [
    "schema.org",
    "cloudflareinsights",
    "googletagmanager",
    "google-analytics",
    "googleapis",
    "gstatic",
    "sentry.io",
    "discourse.org",
    "opensearch.xml",
    ".rss",
    ".xml",
    ".js",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    "letter_avatar",
    "makerdao-forum-backup.s3",
]


FORUM_DOMAINS = [
    "forum.makerdao.com",
    "forum.skyeco.com",
    "gov.uniswap.org",
    "forum.arbitrum.foundation",
    "governance.aave.com",
    "research.lido.fi",
    "discuss.ens.domains",
]


PLATFORM_DOMAINS = [
    "github.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
    "t.me",
    "telegram.me",
    "discord.gg",
    "etherscan.io",
    "solscan.io",
    "arbiscan.io",
    "basescan.org",
    "polygonscan.com",
    "optimistic.etherscan.io",
]


def get_domain(value: str) -> str:
    value = clean_text(value)

    if not value:
        return ""

    if not value.startswith("http"):
        return ""

    try:
        parsed = urlparse(value)
        return parsed.netloc.lower()
    except Exception:
        return ""


def is_bad_contact_value(value: str) -> bool:
    value = clean_text(value).lower()

    if not value:
        return True

    return any(fragment in value for fragment in BAD_CONTACT_FRAGMENTS)


def is_forum_url(value: str) -> bool:
    domain = get_domain(value)

    if not domain:
        return False

    return any(forum_domain in domain for forum_domain in FORUM_DOMAINS)


def is_platform_url(value: str) -> bool:
    domain = get_domain(value)

    if not domain:
        return False

    return any(platform_domain in domain for platform_domain in PLATFORM_DOMAINS)


def is_source_or_profile_url(value: str, profiles: List[Dict[str, Any]]) -> bool:
    value = clean_text(value).rstrip("/")

    if not value:
        return False

    for profile in profiles:
        profile_url = clean_text(profile.get("profile_url")).rstrip("/")
        source_url = clean_text(profile.get("source_url")).rstrip("/")

        if value and value in {profile_url, source_url}:
            return True

    return False


def is_real_personal_website(value: str, profiles: List[Dict[str, Any]]) -> bool:
    value = clean_text(value)

    if not value.startswith("http"):
        return False

    if is_bad_contact_value(value):
        return False

    if is_forum_url(value):
        return False

    if is_platform_url(value):
        return False

    if is_source_or_profile_url(value, profiles):
        return False

    domain = get_domain(value)

    if not domain or "." not in domain:
        return False

    return True


def is_useful_contact(contact: Dict[str, Any], profiles: List[Dict[str, Any]]) -> bool:
    contact_type = clean_text(contact.get("contact_type")).lower()
    value = clean_text(contact.get("value"))

    if not value:
        return False

    if is_bad_contact_value(value):
        return False

    if contact_type == "email":
        return "@" in value

    if contact_type == "x":
        return "x.com/" in value or "twitter.com/" in value

    if contact_type == "linkedin":
        return "linkedin.com/" in value

    if contact_type == "github":
        lowered = value.lower()

        if "github.com/discourse" in lowered:
            return False

        return "github.com/" in lowered

    if contact_type == "website":
        return is_real_personal_website(value, profiles)

    return False
