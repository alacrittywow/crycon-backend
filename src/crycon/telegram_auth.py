"""Verify the signed launch data supplied by Telegram Mini Apps."""

import hmac
import json
import re
import time
from urllib.parse import parse_qsl


def parse_allowed_user_ids(value: str) -> frozenset[int]:
    items = [item for item in re.split(r"[\s,|]+", value.strip()) if item]
    try:
        user_ids = frozenset(int(item) for item in items)
    except ValueError:
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain only numeric user IDs") from None
    if any(user_id <= 0 for user_id in user_ids):
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain only positive user IDs")
    return user_ids


def telegram_user_id(init_data: str, token: str) -> int | None:
    if not init_data or len(init_data) > 8192:
        return None
    try:
        pairs = parse_qsl(
            init_data, keep_blank_values=True, strict_parsing=True,
            encoding="utf-8", errors="strict", max_num_fields=32,
        )
        fields = dict(pairs)
        if len(fields) != len(pairs) or any(
            "\n" in key or "\r" in key or "\n" in value or "\r" in value
            for key, value in pairs
        ):
            return None
        received_hash = fields.pop("hash").encode("ascii")
        check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.digest(b"WebAppData", token.encode(), "sha256")
        expected_hash = hmac.digest(secret, check_string.encode(), "sha256").hex()
        if not hmac.compare_digest(received_hash, expected_hash.encode("ascii")):
            return None
        age = time.time() - int(fields["auth_date"])
        if not -30 <= age <= 3600:
            return None
        user = json.loads(fields["user"])
    except (KeyError, ValueError, RecursionError):
        return None
    user_id = user.get("id") if isinstance(user, dict) else None
    return user_id if type(user_id) is int and user_id > 0 else None
