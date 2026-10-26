import pytest

from config import Settings


def make_settings(monkeypatch, **env):
    for key in ("ALLOWED_ORIGINS", "COMETNET_RELAYS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_empty_and_wildcard_list_values_from_env(monkeypatch):
    loaded = make_settings(monkeypatch, ALLOWED_ORIGINS="*", COMETNET_RELAYS="")

    assert loaded.ALLOWED_ORIGINS == ["*"]
    assert loaded.COMETNET_RELAYS == []


def test_json_and_comma_separated_list_values_from_env(monkeypatch):
    loaded = make_settings(
        monkeypatch,
        ALLOWED_ORIGINS='["https://ui.example","https://tv.example"]',
        COMETNET_RELAYS="wss://one.example, wss://two.example",
    )

    assert loaded.ALLOWED_ORIGINS == ["https://ui.example", "https://tv.example"]
    assert loaded.COMETNET_RELAYS == ["wss://one.example", "wss://two.example"]


def test_list_defaults_are_used_when_env_is_unset(monkeypatch):
    loaded = make_settings(monkeypatch)

    assert loaded.ALLOWED_ORIGINS == ["*"]
    assert loaded.COMETNET_RELAYS == [
        "wss://relay.comet.cache",
        "wss://cometnet.peer.evo",
    ]


def test_invalid_json_list_value_is_rejected(monkeypatch):
    with pytest.raises(Exception):
        make_settings(monkeypatch, COMETNET_RELAYS="[not-json")


def test_stream_control_plane_defaults_are_loopback_and_signed(monkeypatch):
    loaded = make_settings(monkeypatch)

    assert loaded.STREAM_BIND_HOST == "127.0.0.1"
    assert loaded.STREAMER_TOKEN is None
    assert loaded.STREAM_URL_TTL_SECONDS == 1800


def test_stream_control_plane_env_overrides(monkeypatch):
    loaded = make_settings(
        monkeypatch,
        STREAM_BIND_HOST="127.0.0.2",
        STREAMER_TOKEN="configured-secret",
        STREAM_URL_TTL_SECONDS="60",
    )

    assert loaded.STREAM_BIND_HOST == "127.0.0.2"
    assert loaded.STREAMER_TOKEN == "configured-secret"
    assert loaded.STREAM_URL_TTL_SECONDS == 60
