#!/usr/bin/env python3
"""
发现阶段。

对 channels.txt 中的每个频道：
- [videos] 段 → content_type="video"
- [live] 段 → content_type="live"
- 支持 count 模式（回溯 N 条）和 time 模式（日期范围）
- flat extraction（不下载媒体）
- archive/state 去重
- 网络失败可重试（指数退避）
- 输出稳定 JSONL
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
import tomllib
from typing import Any

import yt_dlp

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHANNELS = ROOT / "channels.txt"
CONFIG_PATH = ROOT / "config.toml"
STATE_DIR = ROOT / "state"
WORK_DIR = ROOT / "work"
OUT = WORK_DIR / "candidates.jsonl"

MAX_RETRIES = 3
RETRY_BASE_DELAY = 5


def load_config() -> dict[str, Any]:
    return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _build_url(handle: str, content_type: str) -> str:
    handle = handle.strip().lstrip("@")
    if content_type == "live":
        return f"https://www.youtube.com/@{handle}/streams"
    return f"https://www.youtube.com/@{handle}/videos"


def parse_channels() -> dict[str, list[str]]:
    """解析 channels.txt，返回 {"video": [...], "live": [...]}。"""
    result: dict[str, list[str]] = {"video": [], "live": []}
    current_section = "video"
    section_re = re.compile(r"^\[(videos|live)\]$")

    for line in CHANNELS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = section_re.match(line)
        if m:
            current_section = "video" if m.group(1) == "videos" else "live"
            continue
        result[current_section].append(line)

    return result


def load_archive() -> set[str]:
    archive_file = STATE_DIR / "archive.json"
    if not archive_file.exists():
        return set()
    try:
        data = json.loads(archive_file.read_text(encoding="utf-8"))
        return set(data.get("video_ids", []))
    except (json.JSONDecodeError, KeyError):
        return set()


def save_archive(video_ids: set[str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    archive_file = STATE_DIR / "archive.json"
    tmp = archive_file.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {
                "video_ids": sorted(video_ids),
                "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tmp.replace(archive_file)


def extract_with_retry(url: str, ydl_opts: dict[str, Any]) -> dict[str, Any] | None:
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            last_err = e
            if "HTTP Error 429" in str(e) or "HTTP Error 5" in str(e):
                delay = RETRY_BASE_DELAY * (2**attempt)
                print(f"[WARN] 可重试错误 ({url}): {e}，{delay}s 后重试", file=sys.stderr)
                time.sleep(delay)
                continue
            print(f"[WARN] 不可重试错误 ({url}): {e}", file=sys.stderr)
            return None
        except Exception as e:
            last_err = e
            delay = RETRY_BASE_DELAY * (2**attempt)
            print(f"[WARN] 瞬时错误 ({url}): {e}，{delay}s 后重试", file=sys.stderr)
            time.sleep(delay)
    print(f"[ERROR] 重试耗尽 ({url}): {last_err}", file=sys.stderr)
    return None


def main() -> None:
    config = load_config()
    discovery_cfg = config.get("discovery", {})

    mode = os.environ.get("DISCOVERY_MODE") or discovery_cfg.get("mode", "count")
    max_count = (
        int(os.environ["MAX_HISTORY_COUNT"])
        if "MAX_HISTORY_COUNT" in os.environ
        else discovery_cfg.get("max_history_count", 10)
    )
    publish_after = os.environ.get("PUBLISH_AFTER") or discovery_cfg.get("publish_after", "")
    publish_before = os.environ.get("PUBLISH_BEFORE") or discovery_cfg.get("publish_before", "")

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    known_ids = load_archive()
    channels_map = parse_channels()

    ydl_base_opts: dict[str, Any] = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
    }

    if mode == "time" and publish_after:
        ydl_base_opts["dateafter"] = publish_after
    if mode == "time" and publish_before:
        ydl_base_opts["datebefore"] = publish_before
    if mode == "count":
        ydl_base_opts["playlistend"] = max_count

    candidates: list[dict[str, Any]] = []
    new_ids: set[str] = set()

    for content_type in ("video", "live"):
        handles = channels_map.get(content_type, [])
        if not handles:
            continue

        for handle in handles:
            url = _build_url(handle, content_type)
            ydl_opts = dict(ydl_base_opts)

            info = extract_with_retry(url, ydl_opts)
            if not info:
                continue

            entries = info.get("entries") or []
            for entry in entries:
                if not entry:
                    continue
                vid = entry.get("id")
                if not vid:
                    continue
                if vid in known_ids:
                    continue

                candidate: dict[str, Any] = {
                    "id": vid,
                    "url": entry.get("webpage_url")
                    or entry.get("original_url")
                    or (f"https://www.youtube.com/watch?v={vid}"),
                    "title": entry.get("title"),
                    "channel": entry.get("channel") or entry.get("uploader") or handle,
                    "channel_handle": handle,
                    "duration": entry.get("duration"),
                    "live_status": entry.get("live_status"),
                    "upload_date": entry.get("upload_date"),
                    "content_type": content_type,
                }
                candidates.append(candidate)
                new_ids.add(vid)

    with OUT.open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    all_ids = known_ids | new_ids
    save_archive(all_ids)

    print(
        f"[INFO] 发现 {len(candidates)} 个新候选视频 (已知 {len(known_ids)} 个)",
        file=sys.stderr,
    )
    for c in candidates:
        ct = c["content_type"]
        print(f"  [{ct}] {c['id']}: {c.get('title', 'N/A')[:60]}", file=sys.stderr)


if __name__ == "__main__":
    main()
