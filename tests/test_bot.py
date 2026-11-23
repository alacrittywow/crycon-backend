import pytest

import bot
from bot import parse_allowed_user_ids


def test_allowed_user_ids_accept_common_separators_and_deduplicate():
    assert parse_allowed_user_ids("42, 7|42\n99") == frozenset({7, 42, 99})


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_allowed_user_ids_are_optional(value):
    assert parse_allowed_user_ids(value) == frozenset()


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

        def text(self, name, default=""):
            return self.values.get(name, default)

    monkeypatch.setattr(bot, "load_settings", lambda: FakeSettings())

    application = bot.build_application()

    assert len(application.handlers[0]) == 10


def test_application_builds_without_allowlist(monkeypatch):
    class FakeSettings:
        def require(self, name):
            assert name == "TELEGRAM_BOT_TOKEN"
            return "123:TEST"

        def text(self, name, default=""):
            return default

    monkeypatch.setattr(bot, "load_settings", lambda: FakeSettings())

    application = bot.build_application()

    assert len(application.handlers[0]) == 9
