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


def test_hls_tuning_defaults_and_env_overrides(monkeypatch):
    default = make_settings(monkeypatch)
    assert default.EVO_HLS_PREFETCH_AHEAD == 1
    assert default.EVO_HLS_MAX_CONCURRENCY is None
    assert default.EVO_HLS_CACHE_MAX_MB == 2048

    overridden = make_settings(
        monkeypatch,
        EVO_HLS_PREFETCH_AHEAD="2",
        EVO_HLS_MAX_CONCURRENCY="6",
        EVO_HLS_CACHE_MAX_MB="4096",
    )
    assert overridden.EVO_HLS_PREFETCH_AHEAD == 2
    assert overridden.EVO_HLS_MAX_CONCURRENCY == 6
    assert overridden.EVO_HLS_CACHE_MAX_MB == 4096


def test_cors_middleware_exposes_seek_and_streaming_headers():
    from main import app
    from starlette.middleware.cors import CORSMiddleware

    cors_middleware = next(
        (m for m in app.user_middleware if m.cls == CORSMiddleware), None
    )
    assert cors_middleware is not None
    exposed = cors_middleware.kwargs.get("expose_headers", [])
    assert "X-Evo-Seek-Keyframe" in exposed
    assert "Content-Range" in exposed
    assert "Accept-Ranges" in exposed
    assert "Content-Length" in exposed

