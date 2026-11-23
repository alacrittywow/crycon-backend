"""Pure identity parsing; display casing is preserved."""
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from .text import clean_text


EVM_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


X_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def normalize_x_handle(value: str) -> str:
    value = clean_text(value)

    if not value:
        return ""

    value = value.strip()

    # https://x.com/handle
    # https://twitter.com/handle
    if value.startswith("http"):
        try:
            parsed = urlparse(value)
            domain = parsed.netloc.lower()
            path_parts = [part for part in parsed.path.split("/") if part]

            if domain in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
                if path_parts:
                    handle = path_parts[0].strip("@")

                    if X_HANDLE_RE.match(handle):
                        return handle
        except Exception:
            return ""

    # @handle
    if value.startswith("@"):
        handle = value[1:].strip()

        if X_HANDLE_RE.match(handle):
            return handle

    # plain handle
    if X_HANDLE_RE.match(value):
        return value

    return ""


def normalize_identity_input(value: str) -> Dict[str, str]:
    raw = clean_text(value)

    result = {
        "raw": raw,
        "kind": "unknown",
        "value": raw,
        "x_handle": "",
    }

    if not raw:
        return result

    x_handle = normalize_x_handle(raw)

    if x_handle:
        result["kind"] = "x"
        result["value"] = x_handle
        result["x_handle"] = x_handle
        return result

    lowered = raw.lower()

    if EVM_RE.match(raw):
        result["kind"] = "evm"
        result["value"] = raw
        return result

    if lowered.endswith(".eth"):
        result["kind"] = "ens"
        result["value"] = lowered
        return result

    if lowered.endswith(".lens"):
        result["kind"] = "lens"
        result["value"] = lowered
        return result

    if lowered.endswith(".sol"):
        result["kind"] = "sns_sol"
        result["value"] = lowered
        return result

    if "farcaster.xyz/" in lowered:
        try:
            parsed = urlparse(raw)
            parts = [part for part in parsed.path.split("/") if part]
            if parts:
                result["kind"] = "farcaster"
                result["value"] = parts[0]
                return result
        except Exception:
            pass

    if is_valid_solana_address(raw):
        result["kind"] = "solana"
        result["value"] = raw
        return result

    result["kind"] = "handle"
    result["value"] = raw.strip("@")

    return result


def base58_decode(value: str) -> bytes:
    number = 0

    for char in value:
        if char not in BASE58_ALPHABET:
            raise ValueError("Invalid base58 char")

        number = number * 58 + BASE58_ALPHABET.index(char)

    combined = number.to_bytes((number.bit_length() + 7) // 8, byteorder="big")

    leading_zero_count = 0

    for char in value:
        if char == "1":
            leading_zero_count += 1
        else:
            break

    return b"\x00" * leading_zero_count + combined


def is_valid_solana_address(value: str) -> bool:
    try:
        decoded = base58_decode(value)
        return len(decoded) == 32
    except Exception:
        return False


def normalize_profiles(data: Any) -> List[Dict[str, Any]]:
    if data is None:
        return []

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    if isinstance(data, dict):
        if data.get("error"):
            return []

        return [data]

    return []
