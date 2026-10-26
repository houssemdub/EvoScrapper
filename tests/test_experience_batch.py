"""Experience batch: P9 language-aware ranking, P10 stream explain, P7 sprite sheets."""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.stream_resolver import apply_language_preference, detect_title_languages
from models.stream import StreamItem


def _stream(title: str, score: float = 100.0) -> StreamItem:
    return StreamItem(name="badge", title=title, info_hash="a" * 40, score=score)


class TestLanguageDetection:
    def test_common_language_tags(self):
        assert "fre" in detect_title_languages("Movie.2023.FRENCH.1080p.BluRay")
        assert "multi" in detect_title_languages("Show.S01.MULTI.2160p.WEB-DL")
        assert "ger" in detect_title_languages("Film.GERMAN.DL.1080p")
        assert "eng" in detect_title_languages("Film.ENGLISH.720p")

    def test_untagged_title_has_no_signal(self):
        assert detect_title_languages("Movie.2023.1080p.BluRay.x264") == set()


class TestLanguageRanking:
    def test_preferred_language_partitions_ahead_of_foreign(self):
        streams = [
            _stream("Movie.2023.GERMAN.1080p", score=200.0),
            _stream("Movie.2023.FRENCH.1080p", score=100.0),
        ]
        ranked = apply_language_preference(streams, "french")
        assert ranked[0].title.startswith("Movie.2023.FRENCH")
        assert ranked[1].title.startswith("Movie.2023.GERMAN")

    def test_preferred_language_buries_foreign_single_language(self):
        streams = [
            _stream("Movie.2023.FRENCH.1080p", score=200.0),
            _stream("Movie.2023.1080p.BluRay", score=100.0),  # no signal
        ]
        ranked = apply_language_preference(streams, "english")
        assert ranked[0].title == "Movie.2023.1080p.BluRay"
        assert ranked[1].title == "Movie.2023.FRENCH.1080p"
        assert ranked[1].score == 200.0  # scores untouched: partition, not mutation

    def test_multi_audio_stays_in_preferred_group(self):
        streams = [
            _stream("Show.S01.FRENCH.1080p", score=200.0),
            _stream("Show.S01.MULTI.1080p", score=50.0),
        ]
        ranked = apply_language_preference(streams, "german")
        assert ranked[0].title.startswith("Show.S01.MULTI")
        assert ranked[1].title.startswith("Show.S01.FRENCH")

    def test_unknown_preference_is_noop(self):
        streams = [_stream("Movie.2023.1080p", score=10.0)]
        assert apply_language_preference(streams, "klingon")[0].score == 10.0


class TestStreamExplain:
    @pytest.mark.asyncio
    async def test_explain_combines_coverage_engine_and_keyframes(self, monkeypatch, tmp_path):
        import core.swarm_intelligence as si
        from core.debrid.manager import get_debrid_manager
        from routers.stream import explain_stream_decision

        monkeypatch.setattr(si, "_coverage_store", si.DebridCoverageIndex(path=str(tmp_path / "cov.json")))
        si.get_coverage_index().record("f" * 40, "torbox")

        manager = get_debrid_manager()
        monkeypatch.setattr(type(manager), "active_providers", property(lambda self: [MagicMock(provider_name="RealDebrid")]))

        daemon_status = {
            "sessions": [{
                "info_hash": "f" * 40,
                "health_state": "healthy",
                "seconds_ahead": 45.0,
                "numPeers": 12,
                "swarm_paused": False,
                "avg_bitrate_bps": 14000000,
                "first_byte_ms": 900,
            }]
        }

        with patch("routers.stream.get_daemon_status", new=AsyncMock(return_value=daemon_status)), \
             patch("core.transmuxer.load_cached_keyframes", return_value=[1.0, 2.0, 3.0]):
            result = await explain_stream_decision(info_hash="f" * 40, file_idx=0)

        assert result["debrid"]["mesh_hints"][0]["provider"] == "torbox"
        assert result["debrid"]["configured"] == ["RealDebrid"]
        assert result["engine"]["health_state"] == "healthy"
        assert result["engine"]["seconds_ahead"] == 45.0
        assert result["keyframes_cached"] == 3
        assert result["prediction"]["time_to_first_frame"] == "likely-instant"

    @pytest.mark.asyncio
    async def test_explain_works_without_daemon_session(self, monkeypatch, tmp_path):
        import core.swarm_intelligence as si
        from routers.stream import explain_stream_decision

        monkeypatch.setattr(si, "_coverage_store", si.DebridCoverageIndex(path=str(tmp_path / "cov.json")))
        with patch("routers.stream.get_daemon_status", new=AsyncMock(return_value={"sessions": []})), \
             patch("core.transmuxer.load_cached_keyframes", return_value=None):
            result = await explain_stream_decision(info_hash="e" * 40, file_idx=0)

        assert result["engine"] is None
        assert result["prediction"]["time_to_first_frame"] == "unknown"
        assert "factors" in result


class TestSpriteSheets:
    @pytest.mark.asyncio
    async def test_sprite_generated_then_cached(self, tmp_path, monkeypatch):
        import core.transmuxer as tm
        from routers.stream import get_or_generate_sprite as get_stream_sprites

        sprites_dir = tmp_path / "sprites"
        monkeypatch.setattr(tm, "SPRITES_CACHE_DIR", str(sprites_dir))

        captured_cmd = {}

        async def mock_exec(*cmd, **kwargs):
            captured_cmd["cmd"] = list(cmd)
            out_path = cmd[-1]  # ffmpeg output file is the last argument

            class Proc:
                returncode = 0

                async def communicate(self):
                    sprites_dir.mkdir(parents=True, exist_ok=True)
                    with open(out_path, "wb") as f:
                        f.write(b"jpegdata")
                    return b"", b""

            return Proc()

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec), \
             patch("core.transmuxer.find_ffmpeg", return_value="ffmpeg"):
            first = await get_stream_sprites(info_hash="f" * 40, file_idx=0, duration=1800.0)

        assert first["cached"] is False
        assert first["path"].endswith(".jpg")
        assert os.path.isfile(first["path"])
        # vf chain must produce a tiled contact sheet bounded to the scan window
        assert "-t" in captured_cmd["cmd"]
        assert "tile=" in " ".join(captured_cmd["cmd"])

        second = await get_stream_sprites(info_hash="f" * 40, file_idx=0, duration=1800.0)
        assert second["cached"] is True

    @pytest.mark.asyncio
    async def test_sprite_failure_returns_error(self, tmp_path, monkeypatch):
        import core.transmuxer as tm
        from routers.stream import get_or_generate_sprite as get_stream_sprites

        monkeypatch.setattr(tm, "SPRITES_CACHE_DIR", str(tmp_path / "sprites"))

        async def mock_exec(*cmd, **kwargs):
            class Proc:
                returncode = 1

                async def communicate(self):
                    return b"", b"boom"

                async def wait(self):
                    return 1

            return Proc()

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec), \
             patch("core.transmuxer.find_ffmpeg", return_value="ffmpeg"):
            result = await get_stream_sprites(info_hash="e" * 40, file_idx=0, duration=600.0)

        assert result["cached"] is False
        assert result["error"]
