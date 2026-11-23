import pytest

from crycon.normalization import normalize_x_handle, normalize_identity_input, normalize_profiles, is_valid_solana_address


@pytest.mark.parametrize("value,expected", [
    (" Alice_1 ", "Alice_1"), ("@Alice_1", "Alice_1"),
    ("https://x.com/Alice_1/status/123?x=1", "Alice_1"),
    ("https://www.twitter.com/Alice_1/", "Alice_1"),
    ("https://x.com.evil.example/alice", ""), ("https://evil.example/alice", ""),
    ("@bad-name", ""), ("a" * 16, ""), ("", ""), (None, ""),
])
def test_x_username_normalization(value, expected):
    assert normalize_x_handle(value) == expected


@pytest.mark.parametrize("value,kind,normalized", [
    ("@Alice", "x", "Alice"), (" Alice.ETH ", "ens", "alice.eth"),
    ("Alice.LENS", "lens", "alice.lens"), ("Alice.SOL", "sns_sol", "alice.sol"),
    ("0x" + "Ab" * 20, "evm", "0x" + "Ab" * 20),
    ("11111111111111111111111111111111", "solana", "11111111111111111111111111111111"),
    ("https://farcaster.xyz/alice", "farcaster", "alice"),
    ("long-handle-name", "handle", "long-handle-name"), ("", "unknown", ""),
])
def test_identity_normalization(value, kind, normalized):
    result = normalize_identity_input(value)
    assert (result["kind"], result["value"]) == (kind, normalized)


def test_solana_validation_and_api_shapes():
    assert not is_valid_solana_address("0OIl")
    assert not is_valid_solana_address("111")
    assert normalize_profiles(None) == []
    assert normalize_profiles({"error": "missing"}) == []
    assert normalize_profiles([None, {"platform": "ens"}, "junk"]) == [{"platform": "ens"}]
