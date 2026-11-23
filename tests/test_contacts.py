import pytest

from crycon.contacts import is_useful_contact


@pytest.mark.parametrize('kind,value,expected', [
    ('email', 'alice@personal.dev', True), ('email', 'invalid', False),
    ('x', 'https://x.com/alice', True), ('x', 'https://twitter.com/alice', True),
    ('linkedin', 'https://linkedin.com/in/alice', True),
    ('github', 'https://github.com/alice', True),
    ('github', 'https://github.com/discourse', False),
    ('website', 'https://personal.dev', True),
    ('website', 'https://schema.org', False),
    ('website', 'https://forum.makerdao.com/u/alice', False),
    ('website', 'https://personal.dev/image.png', False),
    ('website', 'https://x.com/alice', False),
    ('website', 'https://already-saved.dev/', False),
    ('website', 'personal.dev', False),
    ('lens', 'https://lens.xyz/alice', False),
    ('email', None, False),
])
def test_legacy_contact_eligibility(kind, value, expected):
    assert is_useful_contact(
        {'contact_type': kind, 'value': value},
        [{'profile_url': 'https://already-saved.dev'}],
    ) is expected
