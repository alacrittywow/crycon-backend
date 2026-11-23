import pytest

import bot
from bot import parse_allowed_user_ids


def test_allowed_user_ids_accept_common_separators_and_deduplicate():
    assert parse_allowed_user_ids("42, 7|42\n99") == frozenset({7, 42, 99})


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_allowed_user_ids_fail_closed_when_empty(value):
    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_USER_IDS is required"):
        parse_allowed_user_ids(value)


@pytest.mark.parametrize("value", ["42,alice", "0", "-7"])
def test_allowed_user_ids_reject_invalid_values(value):
    with pytest.raises(ValueError, match="TELEGRAM_ALLOWED_USER_IDS"):
        parse_allowed_user_ids(value)


def test_application_builds_with_allowlisted_command_handlers(monkeypatch):
    class FakeSettings:
        values = {
            "TELEGRAM_BOT_TOKEN": "123:TEST",
            "TELEGRAM_ALLOWED_USER_IDS": "42,99",
        }

        def require(self, name):
            return self.values[name]

    monkeypatch.setattr(bot, "load_settings", lambda: FakeSettings())

    application = bot.build_application()

    assert len(application.handlers[0]) == 10
