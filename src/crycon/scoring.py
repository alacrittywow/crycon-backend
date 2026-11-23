"""Versioned, pure scoring. No database, environment, or network access."""
from typing import Any, Dict

from .text import clean_text
from .contacts import is_useful_contact


STRONG_KEYWORDS = (
    "validator",
    "governance",
    "delegate",
    "dao",
    "defi",
    "protocol",
    "staking",
    "solana",
    "ethereum",
    "web3",
    "grant",
    "proposal",
)


SPAM_WORDS = (
    "scam",
    "malware",
    "drained",
    "recovery",
    "guaranteed profit",
    "airdrop scam",
)


def status_from_score(score: int) -> str:
    if score >= 80:
        return "strong"

    if score >= 60:
        return "valid"

    if score >= 40:
        return "needs_review"

    return "weak"



def explain_relevance_score(record: Dict[str, Any]) -> dict:
    """Discovery v1: substring matches, bonuses and penalties are unchanged."""
    text = " ".join(clean_text(record.get(field)) for field in (
        "username", "display_name", "bio", "matched_keyword", "source"
    )).lower()
    signals = []
    for keyword in STRONG_KEYWORDS:
        if keyword in text:
            signals.append({"signal": f"keyword:{keyword}", "points": 10})
    source = clean_text(record.get("source")).lower()
    if source == "github":
        signals.append({"signal": "source:github", "points": 20})
    if source.startswith("discourse"):
        signals.append({"signal": "source:discourse", "points": 25})
    for field in ("bio", "profile_url", "source_url"):
        if clean_text(record.get(field)):
            signals.append({"signal": f"present:{field}", "points": 10})
    for word in SPAM_WORDS:
        if word in text:
            signals.append({"signal": f"spam:{word}", "points": -40})
    raw = sum(item["points"] for item in signals)
    score = max(0, min(raw, 100))
    return {"version": "discovery-v1", "score": score, "raw_score": raw,
            "signals": signals, "clamp_adjustment": score - raw}


def calculate_relevance_score(record: Dict[str, Any]) -> int:
    return explain_relevance_score(record)["score"]


def explain_scores(candidate, profiles, contacts, wallets, *, policy="recalculation-v1") -> dict:
    """Explain both historical policies without silently unifying their formulas.

    Profiles are counted as rows, not independent sources. Changing that requires
    a separately versioned scoring policy and migration/recalculation decision.
    """
    if policy not in {"recalculation-v1", "enrichment-v1"}:
        raise ValueError("Unknown scoring policy")
    recalculation = policy == "recalculation-v1"
    relevance = int(candidate.get("relevance_score") or 0)
    identity_signals = [{"signal": "baseline", "points": 50}]
    if len(profiles) >= 2:
        identity_signals.append({"signal": "at_least_two_profile_rows", "points": 15})
    if len(profiles) >= 3:
        identity_signals.append({"signal": "at_least_three_profile_rows", "points": 10})

    eligible_contacts = [c for c in contacts if is_useful_contact(c, profiles)] if recalculation else contacts
    has_contact_signal = bool(eligible_contacts) if recalculation else any(
        int(c.get("confidence") or 0) >= 70 for c in contacts
    )
    if has_contact_signal:
        identity_signals.append({"signal": "useful_contact" if recalculation else "contact_confidence_at_least_70", "points": 10})
    if recalculation and wallets:
        identity_signals.append({"signal": "wallet_present", "points": 5})
    identity = min(sum(s["points"] for s in identity_signals), 100)
    contact = max([0] + [int(c.get("confidence") or 0) for c in eligible_contacts])
    wallet = max([0] + [int(w.get("confidence") or 0) for w in wallets])

    source_signals = [{"signal": "baseline", "points": 50}]
    platforms = {clean_text(p.get("platform")).lower() for p in profiles} if recalculation else {
        p.get("platform", "") for p in profiles
    }
    if "github" in platforms:
        source_signals.append({"signal": "source:github", "points": 15})
    if any(str(p).startswith("discourse") for p in platforms):
        source_signals.append({"signal": "source:discourse", "points": 15})
    source = min(sum(s["points"] for s in source_signals), 100)

    terms = [
        {"signal": "relevance", "value": relevance, "weight": 0.40, "points": relevance * 0.40},
        {"signal": "identity", "value": identity, "weight": 0.30, "points": identity * 0.30},
        {"signal": "source_trust", "value": source, "weight": 0.20, "points": source * 0.20},
        {"signal": "max_contact_wallet", "value": max(contact, wallet), "weight": 0.10, "points": max(contact, wallet) * 0.10},
    ]
    raw = sum(term["points"] for term in terms)
    truncated = int(raw)
    overall = max(0, min(truncated, 100)) if recalculation else truncated
    scores = {"identity_score": identity, "wallet_score": wallet, "contact_score": contact,
              "overall_trust_score": overall, "status": status_from_score(overall)}
    return {
        "version": policy,
        "scores": scores,
        "identity_signals": identity_signals,
        "source_trust_score": source,
        "source_signals": source_signals,
        "contact_selection": {"total": len(contacts), "eligible": len(eligible_contacts),
                              "ignored": len(contacts) - len(eligible_contacts), "maximum_confidence": contact},
        "wallet_selection": {"total": len(wallets), "maximum_confidence": wallet},
        "overall_terms": terms,
        "raw_overall": raw,
        "truncation_adjustment": truncated - raw,
        "clamp_adjustment": overall - truncated,
    }


def calculate_scores(candidate, profiles, contacts, wallets) -> dict:
    """Historical recalculate_scores.py return shape, suitable for DB updates."""
    return explain_scores(candidate, profiles, contacts, wallets)["scores"]


def calculate_enrichment_scores(candidate, profiles, contacts, wallets) -> dict:
    return explain_scores(candidate, profiles, contacts, wallets, policy="enrichment-v1")["scores"]
