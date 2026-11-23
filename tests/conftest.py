"""Isolate tests from credentials and block external I/O in unit tests."""
import socket

import pytest


def deny_network(*args, **kwargs):
    raise AssertionError("Network access is forbidden in unit tests")


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch, request):
    monkeypatch.setenv("CRYCON_ENV_FILE", "")
    for name in (
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "GITHUB_TOKEN",
        "WEB3BIO_API_KEY",
        "TELEGRAM_BOT_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    # PostgreSQL integration tests explicitly opt into their isolated database.
    # Every other test keeps a hard socket/DNS guard.
    if request.node.get_closest_marker("integration") is not None:
        return

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, deny_network)
    for name in ("create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, deny_network)
