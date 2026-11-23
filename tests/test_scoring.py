import pytest
from crycon.scoring import (
    calculate_scores, calculate_enrichment_scores, explain_scores,
    explain_relevance_score,
)

from scoring import calculate_relevance_score, clean_text, status_from_score


def test_clean_text_normalizes_empty_values():
    assert clean_text(None) == ""
    assert clean_text(" null ") == ""
    assert clean_text(" alice ") == "alice"


def test_relevance_score_rewards_multiple_independent_signals():
    record = {
        "username": "alice",
        "bio": "Solana validator and governance delegate",
        "matched_keyword": "staking",
        "source": "github",
        "profile_url": "https://github.com/alice",
    }

    assert calculate_relevance_score(record) == 90


def test_relevance_score_penalizes_spam_signals():
    record = {
        "username": "airdrop-recovery",
        "bio": "Guaranteed profit and wallet recovery",
        "source": "github",
    }

    assert calculate_relevance_score(record) == 0


def test_relevance_score_is_capped_at_one_hundred():
    record = {
        "username": "validator-governance-delegate-dao-defi-protocol",
        "bio": "staking solana ethereum web3 grant proposal",
        "source": "discourse:example.org",
        "profile_url": "https://example.org/u/alice",
        "source_url": "https://example.org/t/topic/1",
    }

    assert calculate_relevance_score(record) == 100


def test_status_thresholds():
    assert status_from_score(39) == "weak"
    assert status_from_score(40) == "needs_review"
    assert status_from_score(60) == "valid"
    assert status_from_score(80) == "strong"




@pytest.mark.parametrize("score,status", [
    (-1, "weak"), (0, "weak"), (39, "weak"), (40, "needs_review"),
    (59, "needs_review"), (60, "valid"), (79, "valid"), (80, "strong"),
    (100, "strong"), (101, "strong"),
])
def test_all_status_boundaries(score, status):
    assert status_from_score(score) == status


@pytest.mark.parametrize("record,expected", [
    ({}, 0),
    ({"matched_keyword": "validator"}, 10),
    ({"matched_keyword": "validator validator", "bio": "validator"}, 20),
    ({"source": "github"}, 20),
    ({"source": "discourse:forum.example"}, 25),
    ({"source": " GITHUB ", "bio": "not empty", "profile_url": "p", "source_url": "p"}, 50),
    ({"bio": "airdrop scam"}, 0),
])
def test_discovery_legacy_scores_and_explanation(record, expected):
    detail = explain_relevance_score(record)
    assert calculate_relevance_score(record) == expected == detail["score"]
    assert sum(s["points"] for s in detail["signals"]) == detail["raw_score"]
    assert detail["raw_score"] + detail["clamp_adjustment"] == expected


def test_spam_overlap_is_explicit_not_silently_changed():
    detail = explain_relevance_score({"bio": "airdrop scam"})
    penalties = [s for s in detail["signals"] if s["points"] < 0]
    assert penalties == [
        {"signal": "spam:scam", "points": -40},
        {"signal": "spam:airdrop scam", "points": -40},
    ]


@pytest.mark.parametrize("count,identity,overall", [(0, 50, 25), (1, 50, 25), (2, 65, 29), (3, 75, 32), (4, 75, 32)])
def test_profile_row_thresholds_are_preserved(count, identity, overall):
    # Repeated platforms still count in v1. They are not proven independent sources.
    scores = calculate_scores({}, [{"platform": "other"}] * count, [], [])
    assert scores["identity_score"] == identity
    assert scores["overall_trust_score"] == overall


def test_two_legacy_policies_are_intentionally_different():
    candidate = {"relevance_score": 40}
    contacts = [{"contact_type": "website", "value": "https://schema.org", "confidence": 90}]
    wallets = [{"confidence": 85}]
    recalculated = calculate_scores(candidate, [], contacts, wallets)
    enriched = calculate_enrichment_scores(candidate, [], contacts, wallets)
    assert recalculated == {"identity_score": 55, "wallet_score": 85, "contact_score": 0,
                            "overall_trust_score": 51, "status": "needs_review"}
    assert enriched == {"identity_score": 60, "wallet_score": 85, "contact_score": 90,
                        "overall_trust_score": 53, "status": "needs_review"}


def test_eligible_low_confidence_contact_and_source_casing():
    contacts = [{"contact_type": "email", "value": "alice@personal.dev", "confidence": 20}]
    profiles = [{"platform": " GITHUB "}, {"platform": "DISCOURSE:example"}]
    assert calculate_scores({}, profiles, contacts, []) == {
        "identity_score": 75, "wallet_score": 0, "contact_score": 20,
        "overall_trust_score": 40, "status": "needs_review",
    }
    assert calculate_enrichment_scores({}, profiles, contacts, []) == {
        "identity_score": 65, "wallet_score": 0, "contact_score": 20,
        "overall_trust_score": 31, "status": "weak",
    }


@pytest.mark.parametrize("policy", ["recalculation-v1", "enrichment-v1"])
def test_breakdown_reconciles_to_persisted_score_without_mutation(policy):
    from copy import deepcopy
    inputs = ({"relevance_score": 81}, [{"platform": "github"}, {"platform": "discourse:example"}],
              [{"contact_type": "email", "value": "alice@personal.dev", "confidence": 76}], [{"confidence": 91}])
    before = deepcopy(inputs)
    detail = explain_scores(*inputs, policy=policy)
    assert inputs == before
    assert detail["version"] == policy
    assert sum(s["points"] for s in detail["identity_signals"]) == detail["scores"]["identity_score"]
    assert sum(s["points"] for s in detail["source_signals"]) == detail["source_trust_score"]
    reconstructed = sum(t["points"] for t in detail["overall_terms"]) + detail["truncation_adjustment"] + detail["clamp_adjustment"]
    assert reconstructed == pytest.approx(detail["scores"]["overall_trust_score"])


def test_overall_clamp_preserves_legacy_policy_difference():
    assert calculate_scores({"relevance_score": 1000}, [], [], [])["overall_trust_score"] == 100
    assert calculate_scores({"relevance_score": -1000}, [], [], [])["overall_trust_score"] == 0
    assert calculate_enrichment_scores({"relevance_score": 1000}, [], [], [])["overall_trust_score"] == 425


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError, match="Unknown scoring policy"):
        explain_scores({}, [], [], [], policy="v2")
