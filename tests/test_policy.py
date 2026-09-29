"""
策略引擎纯函数单元测试。

测试不访问 YouTube，所有数据均为 mock。
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from scripts.process import (
    MediaDecision,
    decide,
    estimate_hevc_size,
    estimate_size_from_formats,
    has_format_at_height,
    load_config,
    video_to_dict,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = load_config(ROOT / "config.toml")


def _f720(filesize: int | None = None, tbr: float | None = None) -> dict:
    f: dict = {
        "height": 720,
        "vcodec": "avc1.64001f",
        "acodec": "mp4a.40.2",
        "ext": "mp4",
    }
    if filesize is not None:
        f["filesize"] = filesize
    if tbr is not None:
        f["tbr"] = tbr
    return f


def _f480(tbr: float | None = None, filesize: int | None = None) -> dict:
    f: dict = {
        "height": 480,
        "vcodec": "avc1.64001f",
        "acodec": "mp4a.40.2",
        "ext": "mp4",
    }
    if tbr is not None:
        f["tbr"] = tbr
    if filesize is not None:
        f["filesize"] = filesize
    return f


def _f420(tbr: float | None = None) -> dict:
    f: dict = {
        "height": 420,
        "vcodec": "avc1.64001f",
        "acodec": "mp4a.40.2",
        "ext": "mp4",
    }
    if tbr is not None:
        f["tbr"] = tbr
    return f


class TestEstimateSize:
    def test_filesize_direct(self):
        formats = [_f720(filesize=50_000_000)]
        est = estimate_size_from_formats(formats, target_height=720, duration=600)
        assert est == pytest.approx(47.68, rel=0.1)

    def test_tbr_fallback(self):
        formats = [_f720(tbr=1000)]
        est = estimate_size_from_formats(formats, target_height=720, duration=600)
        assert est == pytest.approx(71.53, rel=0.1)

    def test_filesize_approx(self):
        formats = [{"height": 720, "filesize_approx": 80_000_000}]
        est = estimate_size_from_formats(formats, target_height=720, duration=600)
        assert est == pytest.approx(76.29, rel=0.1)

    def test_zero_duration(self):
        formats = [_f720(tbr=1000)]
        est = estimate_size_from_formats(formats, target_height=720, duration=0)
        assert est is None

    def test_zero_tbr(self):
        formats = [_f720(tbr=0)]
        est = estimate_size_from_formats(formats, target_height=720, duration=600)
        assert est is None

    def test_no_matching_height(self):
        formats = [_f480(tbr=500)]
        est = estimate_size_from_formats(formats, target_height=720, duration=600)
        assert est is None

    def test_unknown_size_tbr_estimate(self):
        formats = [_f720(tbr=1500)]
        est = estimate_size_from_formats(formats, target_height=720, duration=300)
        assert est is not None
        assert est > 0


class TestHasFormatAtHeight:
    def test_has_720(self):
        assert has_format_at_height([_f720()], 720)

    def test_no_720(self):
        assert not has_format_at_height([_f480()], 720)

    def test_empty_formats(self):
        assert not has_format_at_height([], 720)


class TestEstimateHevc:
    def test_basic_hevc_estimate(self):
        est = estimate_hevc_size(600, 720, 28)
        assert est > 50
        assert est < 250

    def test_hevc_lower_crf_smaller(self):
        est_28 = estimate_hevc_size(600, 720, 28)
        est_35 = estimate_hevc_size(600, 720, 35)
        assert est_35 < est_28

    def test_hevc_longer_larger(self):
        est_short = estimate_hevc_size(60, 720, 28)
        est_long = estimate_hevc_size(600, 720, 28)
        assert est_long > est_short

    def test_hevc_480_smaller_than_720(self):
        est_720 = estimate_hevc_size(600, 720, 28)
        est_480 = estimate_hevc_size(600, 480, 28)
        assert est_480 < est_720


class TestDecide:
    @pytest.mark.parametrize(
        "test_name,duration,formats,expected_mode",
        [
            pytest.param(
                "t1",
                600,
                [_f720(filesize=90_000_000)],
                "native_720p",
                id="1_short_small_720p",
            ),
            pytest.param(
                "t2",
                600,
                [_f720(filesize=500_000_000)],
                "hevc_720p",
                id="2_short_large_720p_hevc",
            ),
            pytest.param(
                "t3",
                600,
                [_f720(filesize=90_000_000), _f480(tbr=500)],
                "native_720p",
                id="3_native_720p_preferred",
            ),
            pytest.param(
                "t4",
                900,
                [_f720(filesize=800_000_000), _f480(filesize=30_000_000)],
                "fallback_480p",
                id="4_hevc_exceeds_budget",
            ),
            pytest.param(
                "t5",
                900,
                [_f720(filesize=800_000_000), _f420(tbr=500)],
                "fallback_420p",
                id="5_480p_unavailable",
            ),
            pytest.param(
                "t6",
                600,
                [_f720(filesize=500_000_000)],
                "hevc_720p",
                id="6_hevc_viable",
            ),
            pytest.param(
                "t7",
                1200,
                [_f720(filesize=900_000_000)],
                "audio",
                id="7_audio_only_final",
            ),
            pytest.param(
                "t8",
                1200,
                [_f720(filesize=120_000_000), _f480(filesize=30_000_000)],
                "fallback_480p",
                id="8_20min_normal",
            ),
            pytest.param("t9", 5400, [_f720(filesize=200_000_000)], "audio", id="9_ultra_long"),
        ],
    )
    def test_scenarios(self, test_name, duration, formats, expected_mode):
        decision = decide(
            video_id="test_vid",
            duration=duration,
            live_status=None,
            formats=formats,
            config=DEFAULT_CONFIG,
        )
        assert decision.media_mode == expected_mode, (
            f"expected {expected_mode}, got {decision.media_mode}: {decision.reason}"
        )

    def test_live_video_gets_normal_treatment(self):
        """直播视频在 audio_only_live=false 时按普通视频处理。"""
        d = decide("v1", 600, "is_live", [_f720(filesize=50_000_000)], DEFAULT_CONFIG)
        assert d.media_mode == "native_720p"
        assert d.reason == "native_720p_within_budget"

    def test_live_was_live_normal(self):
        d = decide("v2", 600, "was_live", [_f720(filesize=50_000_000)], DEFAULT_CONFIG)
        assert d.media_mode == "native_720p"

    def test_live_upcoming_no_formats(self):
        d = decide("v3", None, "is_upcoming", [], DEFAULT_CONFIG)
        assert d.media_mode == "audio"

    def test_live_long_duration_audio_only(self):
        """直播超长内容仍按长视频规则处理。"""
        d = decide("v4", 5400, "is_live", [_f720(filesize=200_000_000)], DEFAULT_CONFIG)
        assert d.media_mode == "audio"
        assert d.reason == "long_form_audio_only"

    def test_long_form_audio_only(self):
        d = decide("v4", 4000, None, [_f720(filesize=50_000_000)], DEFAULT_CONFIG)
        assert d.media_mode == "audio"
        assert d.reason == "long_form_audio_only"

    def test_no_formats_audio(self):
        d = decide("v5", 300, None, [], DEFAULT_CONFIG)
        assert d.media_mode == "audio"

    def test_none_duration_treated_zero(self):
        d = decide("v6", None, None, [_f720(filesize=50_000_000)], DEFAULT_CONFIG)
        assert d.media_mode == "native_720p"

    def test_over_18min_falls_to_lower_res(self):
        d = decide(
            "v7",
            1200,
            None,
            [_f720(filesize=180_000_000), _f480(tbr=500)],
            DEFAULT_CONFIG,
        )
        assert d.media_mode in ("fallback_480p", "fallback_420p", "audio")

    def test_exact_18min_720p(self):
        d = decide("v8", 18 * 60, None, [_f720(filesize=90_000_000)], DEFAULT_CONFIG)
        assert d.media_mode == "native_720p"
        assert d.reason == "native_720p_within_budget"

    def test_custom_config_hevc_fails(self):
        custom = dict(DEFAULT_CONFIG)
        custom["budget"] = dict(custom["budget"])
        custom["budget"]["hevc_720p_mb"] = 50
        d = decide(
            "v9",
            600,
            None,
            [_f720(filesize=800_000_000), _f480(filesize=30_000_000)],
            custom,
        )
        assert d.media_mode == "fallback_480p"

    def test_duplicate_same_decision(self):
        fmts = [_f720(filesize=90_000_000)]
        d1 = decide("dup", 600, None, fmts, DEFAULT_CONFIG)
        d2 = decide("dup", 600, None, fmts, DEFAULT_CONFIG)
        assert d1.media_mode == d2.media_mode
        assert d1.estimated_mb == d2.estimated_mb

    def test_video_to_dict_rounding(self):
        md = MediaDecision("v1", "native_720p", "test", 123.456)
        dct = video_to_dict(md)
        assert dct["estimated_mb"] == 123.46


class TestLoadConfig:
    def test_load_default_config(self):
        c = load_config(ROOT / "config.toml")
        assert "general" in c
        assert "budget" in c
        assert c["budget"]["native_720p_mb"] == 300


class TestDryRunCLI:
    def test_dry_run_with_metadata_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(
                {
                    "id": "test123",
                    "duration": 600,
                    "live_status": None,
                    "formats": [{"height": 720, "filesize": 90_000_000}],
                },
                f,
            )
            f.flush()
            path = f.name

        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "process.py"), "--metadata", path],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert isinstance(output, list)
        assert output[0]["media_mode"] == "native_720p"

        pathlib.Path(path).unlink()


class TestEdgeCases:
    def test_negative_duration(self):
        d = decide("neg", -1, None, [_f720(filesize=50_000_000)], DEFAULT_CONFIG)
        assert d.media_mode == "native_720p"

    def test_very_short_video(self):
        d = decide("short", 5, None, [_f720(tbr=500)], DEFAULT_CONFIG)
        assert d.media_mode == "native_720p"
        assert d.estimated_mb < 10

    def test_very_high_tbr(self):
        d = decide("high", 600, None, [_f720(tbr=10000)], DEFAULT_CONFIG)
        assert d.media_mode in ("hevc_720p", "fallback_480p", "fallback_420p", "audio")

    def test_unknown_size_estimation(self):
        d = decide("unk", 600, None, [{"height": 720}], DEFAULT_CONFIG)
        assert d.media_mode in ("native_720p", "hevc_720p", "audio")
