from copy import deepcopy

from crycon.deduplication import deduplicate_web3_profiles


def test_duplicates_keep_first_source_and_order_without_mutation():
    records = [
        {"platform": "ENS", "identity": "Alice.ETH", "address": "0xAB", "_api_url": "first"},
        {"platform": "ens", "identity": "alice.eth", "address": "0xab", "_api_url": "second"},
        {"platform": "lens", "identity": "alice.lens", "address": "0xab"},
    ]
    before = deepcopy(records)
    assert deduplicate_web3_profiles(iter(records)) == [records[0], records[2]]
    assert records == before


def test_case_sensitive_solana_identifiers_are_not_merged():
    a = {"platform": "solana", "identity": "AbCd", "address": "AbCd"}
    b = {"platform": "solana", "identity": "abcd", "address": "abcd"}
    assert deduplicate_web3_profiles([a, b, a]) == [a, b]


def test_different_wallets_and_platforms_remain_separate():
    records = [{"platform": "ens", "identity": "alice.eth", "address": "0x1"},
               {"platform": "ens", "identity": "alice.eth", "address": "0x2"},
               {"platform": "lens", "identity": "alice.eth", "address": "0x1"}]
    assert deduplicate_web3_profiles(records) == records
    assert deduplicate_web3_profiles([]) == []
