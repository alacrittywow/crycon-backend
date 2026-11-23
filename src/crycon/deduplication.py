"""Stable deduplication of API profiles, without merging candidate identities."""
from collections.abc import Iterable
from typing import Any

from .text import clean_text


def web3_profile_key(profile: dict[str, Any]) -> tuple[str, str, str]:
    platform = clean_text(profile.get("platform")).lower()
    identity = clean_text(profile.get("identity"))
    address = clean_text(profile.get("address"))
    # EVM addresses are case insensitive for comparison. Base58 is not.
    if address.startswith("0x"):
        address = address.lower()
    if platform != "solana":
        identity = identity.lower()
    return platform, identity, address


def deduplicate_web3_profiles(profiles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first source and its metadata, preserving encounter order."""
    seen = set()
    result = []
    for profile in profiles:
        key = web3_profile_key(profile)
        if key not in seen:
            seen.add(key)
            result.append(profile)
    return result
