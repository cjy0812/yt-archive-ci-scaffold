#!/usr/bin/env python3
"""
字幕管线。

优先级：手动/原生字幕 > YouTube 自动字幕 > faster-whisper ASR
- yt-dlp 下载字幕（手动 → 自动）
- 无字幕时，faster-whisper ASR（仅限 < max_asr_duration_seconds）
- 输出到 subtitles/<video_id>.<lang>.vtt
"""

from __future__ import annotations

import argparse
import json
import pathlib
import tomllib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config.toml"
SUBTITLE_DIR = ROOT / "subtitles"


def load_config(path: pathlib.Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_CONFIG
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def download_subtitles(
    video_id: str,
    video_url: str,
    config: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    import yt_dlp

    result: dict[str, Any] = {
        "video_id": video_id,
        "source": None,
        "language": None,
        "path": None,
        "dry_run": dry_run,
    }

    if dry_run:
        return result

    subtitle_cfg = config.get("subtitle", {})
    langs = subtitle_cfg.get("languages", ["en"])

    SUBTITLE_DIR.mkdir(parents=True, exist_ok=True)

    for subtitle_mode in ["manual", "auto"]:
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writesubtitles": subtitle_mode == "manual",
            "writeautomaticsub": subtitle_mode == "auto",
            "subtitleslangs": langs,
            "subtitlesformat": "vtt",
            "outtmpl": str(SUBTITLE_DIR / f"{video_id}"),
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(video_url, download=True)

            for lang in langs:
                vtt_path = SUBTITLE_DIR / f"{video_id}.{lang}.vtt"
                if vtt_path.exists():
                    source_name = "native" if subtitle_mode == "manual" else "youtube_auto"
                    result["source"] = source_name
                    result["language"] = lang
                    result["path"] = str(vtt_path)
                    return result
        except Exception:
            continue

    return _asr_fallback(video_id, video_url, config, result)


def _asr_fallback(
    video_id: str,
    video_url: str,
    config: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    import yt_dlp

    subtitle_cfg = config.get("subtitle", {})
    max_duration = subtitle_cfg.get("max_asr_duration_seconds", 3600)
    langs = subtitle_cfg.get("languages", ["en"])

    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception as e:
        result["error"] = str(e)
        return result

    if not info:
        result["error"] = "无元数据"
        return result

    duration = info.get("duration") or 0
    if duration > max_duration:
        result["source"] = "none"
        result["reason"] = f"视频时长 {duration}s 超过 ASR 限制 {max_duration}s"
        return result

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        result["source"] = "none"
        result["reason"] = "faster-whisper 未安装"
        return result

    audio_ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(SUBTITLE_DIR / f"{video_id}.audio.%(ext)s"),
    }

    audio_path = None
    try:
        with yt_dlp.YoutubeDL(audio_ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            if info:
                audio_path = info.get("requested_downloads", [{}])[0].get("filepath")
    except Exception as e:
        result["error"] = f"音频下载失败: {e}"
        return result

    if not audio_path or not pathlib.Path(audio_path).exists():
        result["error"] = "音频文件未找到"
        return result

    try:
        model_size = subtitle_cfg.get("whisper_model", "small")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(audio_path, beam_size=5)

        vtt_path = SUBTITLE_DIR / f"{video_id}.{langs[0]}.vtt"
        with vtt_path.open("w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for seg in segments:
                start = seg.start
                end = seg.end
                text = seg.text.strip()
                f.write(f"{_fmt_ts(start)} --> {_fmt_ts(end)}\n{text}\n\n")

        result["source"] = "whisper_asr"
        result["language"] = langs[0]
        result["path"] = str(vtt_path)
        result["segments"] = len(list(segments))
    except Exception as e:
        result["error"] = f"ASR 失败: {e}"
    finally:
        if audio_path:
            pathlib.Path(audio_path).unlink(missing_ok=True)

    return result


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def process_subtitles(
    video_id: str,
    video_url: str,
    config: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    from state import get_state, set_state

    state = get_state(video_id)
    if state and state.get("status") == "subtitle_ready":
        return {"video_id": video_id, "skipped": True, "reason": "字幕已就绪"}

    result = download_subtitles(video_id, video_url, config, dry_run=dry_run)

    if result.get("path") or dry_run:
        existing = state or {}
        set_state(
            video_id,
            "subtitle_ready",
            {
                "subtitle_source": result.get("source"),
                "media_mode": existing.get("media_mode"),
                "content_type": existing.get("content_type"),
                "thumbnail": existing.get("thumbnail"),
            },
        )
    elif result.get("source") == "none":
        existing = state or {}
        set_state(
            video_id,
            "subtitle_ready",
            {
                "subtitle_source": "none",
                "media_mode": existing.get("media_mode"),
                "content_type": existing.get("content_type"),
                "thumbnail": existing.get("thumbnail"),
            },
        )
    else:
        set_state(video_id, "failed", {"error": result.get("error", "未知错误")})

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="字幕管线")
    parser.add_argument("--video-id", type=str)
    parser.add_argument("--video-url", type=str)
    parser.add_argument("--candidates", type=str, help="candidates.jsonl 路径（批量处理）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    config = load_config(pathlib.Path(args.config))

    if args.candidates:
        candidates_path = pathlib.Path(args.candidates)
        candidates: list[dict[str, Any]] = []
        if candidates_path.exists():
            for line in candidates_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    candidates.append(json.loads(line))

        results = []
        for c in candidates:
            r = process_subtitles(
                video_id=c["id"],
                video_url=c.get("url", f"https://www.youtube.com/watch?v={c['id']}"),
                config=config,
                dry_run=args.dry_run,
            )
            results.append(r)

        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if not args.video_id:
        print(json.dumps({"error": "需要 --video-id 或 --candidates"}, ensure_ascii=False))
        return

    result = process_subtitles(
        args.video_id,
        args.video_url or f"https://www.youtube.com/watch?v={args.video_id}",
        config,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
