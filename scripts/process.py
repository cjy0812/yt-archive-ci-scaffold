#!/usr/bin/env python3
"""
媒体策略引擎 + 下载管线。

metadata-first 原则：
1. 先获取 duration/live status/formats/filesize 等元数据
2. 决策 media_mode（不先下载视频再判断）
3. 输出确定性 JSON 决策
4. 根据决策执行下载 / HEVC 转码 / 清理临时文件
5. 封面下载 → WebP 98% 压缩 → Git 追踪
6. 视频 URL 存档 → Git 追踪
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config.toml"
WORK_DIR = ROOT / "work"
MEDIA_DIR = ROOT / "media"
THUMBNAIL_DIR = ROOT / "thumbnails"
URL_DIR = ROOT / "urls"


@dataclass
class MediaDecision:
    video_id: str
    media_mode: str
    reason: str
    estimated_mb: float
    details: dict[str, Any] = field(default_factory=dict)


def load_config(path: pathlib.Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_CONFIG
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def estimate_size_from_formats(
    formats: list[dict[str, Any]],
    target_height: int | None = None,
    target_vcodec: str | None = None,
    duration: float | None = None,
) -> float | None:
    best_est: float | None = None
    for f in formats:
        if target_height is not None and f.get("height") != target_height:
            continue
        if target_vcodec is not None:
            vcodec = f.get("vcodec", "") or ""
            if vcodec != target_vcodec and vcodec not in (target_vcodec,):
                continue

        filesize = f.get("filesize") or f.get("filesize_approx")
        if filesize and filesize > 0:
            size_mb = filesize / (1024 * 1024)
            if best_est is None or size_mb > best_est:
                best_est = size_mb

        tbr = f.get("tbr")
        if tbr and tbr > 0 and duration and duration > 0:
            size_mb = (tbr * 1000 * duration) / (8 * 1024 * 1024)
            if best_est is None or size_mb > best_est:
                best_est = size_mb

    return best_est


def has_format_at_height(
    formats: list[dict[str, Any]],
    height: int,
) -> bool:
    return any(f.get("height") == height for f in formats)


def estimate_hevc_size(duration: float, height: int, crf: int = 28) -> float:
    base_bps = 3_500_000
    height_factor = (height / 720) ** 2
    crf_factor = max(0.1, 1.0 - (crf - 23) * 0.06)
    estimated_bits = base_bps * height_factor * crf_factor * duration
    return estimated_bits / (8 * 1024 * 1024)


def decide(
    video_id: str,
    duration: float | None,
    live_status: str | None,
    formats: list[dict[str, Any]],
    config: dict[str, Any],
) -> MediaDecision:
    budget = config["budget"]
    video_cfg = config["video"]
    discovery = config["discovery"]

    duration = duration or 0
    is_live = bool(live_status and live_status in ("is_live", "is_upcoming", "was_live"))

    if is_live and discovery.get("audio_only_live", True):
        est = estimate_size_from_formats(formats, duration=duration)
        return MediaDecision(
            video_id=video_id,
            media_mode="audio",
            reason="live_audio_only",
            estimated_mb=est or 0,
            details={"live_status": live_status},
        )

    long_form_min = discovery.get("long_form_minutes", 60)
    if duration >= long_form_min * 60:
        est = estimate_size_from_formats(formats, duration=duration)
        return MediaDecision(
            video_id=video_id,
            media_mode="audio",
            reason="long_form_audio_only",
            estimated_mb=est or 0,
            details={"duration_minutes": duration / 60},
        )

    preferred_720p_min = discovery.get("preferred_720p_minutes", 18)
    native_720p_budget = budget.get("native_720p_mb", 300)
    hevc_720p_budget = budget.get("hevc_720p_mb", 200)
    fallback_480p_budget = budget.get("fallback_480p_mb", 150)
    audio_budget = budget.get("audio_mb", 100)
    fallback_height = video_cfg.get("fallback_height", 480)
    min_video_height = video_cfg.get("minimum_video_height", 420)
    hevc_crf = video_cfg.get("hevc_crf", 28)

    if duration <= preferred_720p_min * 60:
        has_720 = has_format_at_height(formats, 720)
        if has_720:
            est_720 = estimate_size_from_formats(formats, target_height=720, duration=duration)
            if est_720 is not None and est_720 <= native_720p_budget:
                return MediaDecision(
                    video_id=video_id,
                    media_mode="native_720p",
                    reason="native_720p_within_budget",
                    estimated_mb=est_720,
                    details={"height": 720, "budget_mb": native_720p_budget},
                )
            if est_720 is not None and est_720 > native_720p_budget:
                est_hevc = estimate_hevc_size(duration, 720, hevc_crf)
                if est_hevc <= hevc_720p_budget:
                    return MediaDecision(
                        video_id=video_id,
                        media_mode="hevc_720p",
                        reason="720p_too_large_hevc_viable",
                        estimated_mb=est_hevc,
                        details={"native_est_mb": est_720, "hevc_est_mb": est_hevc},
                    )

    has_480 = has_format_at_height(formats, fallback_height)
    if has_480:
        est_480 = estimate_size_from_formats(formats, target_height=fallback_height, duration=duration)
        if est_480 is None:
            est_480 = estimate_hevc_size(duration, fallback_height, hevc_crf)
        if est_480 <= fallback_480p_budget:
            return MediaDecision(
                video_id=video_id,
                media_mode="fallback_480p",
                reason="fallback_to_480p",
                estimated_mb=est_480,
                details={"height": fallback_height, "budget_mb": fallback_480p_budget},
            )

    has_420 = has_format_at_height(formats, min_video_height)
    if has_420:
        est_420 = estimate_size_from_formats(formats, target_height=min_video_height, duration=duration)
        if est_420 is None:
            est_420 = estimate_hevc_size(duration, min_video_height, hevc_crf)
        if est_420 <= fallback_480p_budget:
            return MediaDecision(
                video_id=video_id,
                media_mode="fallback_420p",
                reason="fallback_to_420p",
                estimated_mb=est_420,
                details={"height": min_video_height, "budget_mb": fallback_480p_budget},
            )

    est_audio = estimate_size_from_formats(formats, duration=duration)
    if est_audio is None:
        est_audio = (duration * 128_000) / (8 * 1024 * 1024)
    return MediaDecision(
        video_id=video_id,
        media_mode="audio",
        reason="video_too_large_audio_fallback",
        estimated_mb=est_audio,
        details={"audio_budget_mb": audio_budget},
    )


def video_to_dict(d: MediaDecision) -> dict[str, Any]:
    return {
        "video_id": d.video_id,
        "media_mode": d.media_mode,
        "reason": d.reason,
        "estimated_mb": round(d.estimated_mb, 2),
        "details": d.details,
    }


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return True
    except FileNotFoundError:
        return False


def _sanitize_path(name: str) -> str:
    """清理文件名中的非法字符，保留中文。"""
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip().rstrip(".")
    return name[:80]


def _video_output_dir(
    channel: str,
    content_type: str,
    upload_date: str | None,
    title: str,
) -> pathlib.Path:
    """构建输出路径: media/{channel}/videos(或live)/{YYYY}/{MM}/{YYYYMMDD}_{title}/"""
    clean_channel = _sanitize_path(channel)
    clean_title = _sanitize_path(title or "untitled")
    date_str = upload_date or "00000000"
    year = date_str[:4] if len(date_str) >= 4 else "0000"
    month = date_str[4:6] if len(date_str) >= 6 else "00"
    folder = f"{date_str}_{clean_title}"
    return MEDIA_DIR / clean_channel / content_type / year / month / folder


def _thumb_output_dir(
    channel: str,
    content_type: str,
    upload_date: str | None,
    title: str,
) -> pathlib.Path:
    """构建封面路径: thumbnails/{channel}/videos(或live)/{YYYY}/{MM}/{YYYYMMDD}_{title}/"""
    clean_channel = _sanitize_path(channel)
    clean_title = _sanitize_path(title or "untitled")
    date_str = upload_date or "00000000"
    year = date_str[:4] if len(date_str) >= 4 else "0000"
    month = date_str[4:6] if len(date_str) >= 6 else "00"
    folder = f"{date_str}_{clean_title}"
    return THUMBNAIL_DIR / clean_channel / content_type / year / month / folder


def _save_video_url(
    channel: str,
    content_type: str,
    video_id: str,
    video_url: str,
    title: str,
    upload_date: str | None,
) -> None:
    """保存视频 URL 到 urls/ 目录（Git 追踪）。"""
    clean_channel = _sanitize_path(channel)
    date_str = upload_date or "00000000"
    year = date_str[:4] if len(date_str) >= 4 else "0000"
    month = date_str[4:6] if len(date_str) >= 6 else "00"
    url_path = URL_DIR / clean_channel / content_type / year / month
    url_path.mkdir(parents=True, exist_ok=True)
    url_file = url_path / f"{video_id}.json"
    data: dict[str, Any] = {
        "video_id": video_id,
        "url": video_url,
        "title": title,
        "upload_date": upload_date,
        "content_type": content_type,
        "channel": channel,
    }
    url_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _download_thumbnail(
    video_url: str,
    out_dir: pathlib.Path,
    video_id: str,
) -> str | None:
    """下载封面并转换为 WebP 98% 质量。返回文件路径。"""
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_dir / f"{video_id}.%(ext)s")
    jpg_path = out_dir / f"{video_id}.jpg"
    webp_path = out_dir / f"{video_id}.webp"

    try:
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writethumbnail": True,
            "outtmpl": out_tmpl,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(video_url, download=True)
    except Exception as e:
        print(f"[WARN] 封面下载失败: {e}", file=sys.stderr)
        return None

    if not jpg_path.exists():
        alt = list(out_dir.glob(f"{video_id}.*"))
        if alt and alt[0].suffix.lower() in (".jpg", ".png", ".webp"):
            jpg_path = alt[0]

    if not jpg_path.exists():
        print("[WARN] 封面文件未找到", file=sys.stderr)
        return None

    if _ffmpeg_available() and jpg_path.suffix.lower() != ".webp":
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    str(jpg_path),
                    "-quality",
                    "98",
                    "-y",
                    str(webp_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            jpg_path.unlink()
            return str(webp_path)
        except subprocess.CalledProcessError as e:
            print(f"[WARN] WebP 转换失败: {e.stderr.decode()[:200]}", file=sys.stderr)

    return str(jpg_path)


def _video_format_spec(media_mode: str) -> str:
    specs: dict[str, str] = {
        "native_720p": (
            "bestvideo[height<=720][vcodec!*=vp9]+bestaudio[ext=m4a]/"
            "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
        ),
        "hevc_720p": (
            "bestvideo[height<=720]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best"
        ),
        "fallback_480p": (
            "bestvideo[height<=480]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]/best"
        ),
        "fallback_420p": (
            "bestvideo[height<=420]+bestaudio[ext=m4a]/bestvideo[height<=420]+bestaudio/best[height<=420]/best"
        ),
        "audio": "bestaudio[ext=m4a]/bestaudio",
    }
    return specs.get(media_mode, specs["audio"])


def download_media(
    video_url: str,
    decision: MediaDecision,
    config: dict[str, Any],
    output_dir: pathlib.Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    import yt_dlp

    result: dict[str, Any] = {
        "video_id": decision.video_id,
        "media_mode": decision.media_mode,
        "downloaded": False,
        "final_path": None,
        "filesize_mb": 0,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(output_dir / "%(id)s.%(ext)s")

    if decision.media_mode == "audio":
        format_spec = _video_format_spec("audio")
    else:
        format_spec = _video_format_spec(decision.media_mode)

    if dry_run:
        result["dry_run"] = True
        return result

    video_cfg = config.get("video", {})
    hevc_crf = video_cfg.get("hevc_crf", 28)

    ydl_opts: dict[str, Any] = {
        "format": format_spec,
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "merge_output_format": "mp4",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
    except Exception as e:
        result["error"] = str(e)
        return result

    if not info:
        result["error"] = "yt-dlp 返回空结果"
        return result

    filename = info.get("requested_downloads") or []
    if filename:
        result["final_path"] = filename[0].get("filepath")
    elif info.get("_filename"):
        result["final_path"] = info["_filename"]

    if decision.media_mode == "hevc_720p" and result["final_path"] and _ffmpeg_available():
        result = _reencode_hevc(result, decision.video_id, hevc_crf)

    if result["final_path"] and pathlib.Path(result["final_path"]).exists():
        result["filesize_mb"] = pathlib.Path(result["final_path"]).stat().st_size / (1024 * 1024)
        result["downloaded"] = True

    return result


def _reencode_hevc(result: dict[str, Any], video_id: str, crf: int) -> dict[str, Any]:
    src = pathlib.Path(result["final_path"])
    dst = src.with_suffix(".hevc.mp4")

    cmd = [
        "ffmpeg",
        "-i",
        str(src),
        "-c:v",
        "libx265",
        "-crf",
        str(crf),
        "-preset",
        "medium",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        "-y",
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        src.unlink()
        result["final_path"] = str(dst)
    except subprocess.CalledProcessError as e:
        print(
            f"[WARN] HEVC 转码失败，保留原始文件: {e.stderr.decode()[:200]}",
            file=sys.stderr,
        )

    return result


def process_video(
    video_id: str,
    video_url: str,
    config: dict[str, Any],
    dry_run: bool = False,
    channel: str = "",
    content_type: str = "video",
    upload_date: str | None = None,
    title: str = "",
) -> dict[str, Any]:
    import yt_dlp

    from state import get_state, set_state

    existing = get_state(video_id)
    if existing and existing.get("status") in (
        "media_ready",
        "subtitle_ready",
        "staged",
        "released",
    ):
        return {
            "video_id": video_id,
            "skipped": True,
            "reason": f"已处于 {existing['status']}",
        }

    set_state(video_id, "processing")

    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "skip_download": True,
        "ignoreerrors": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception as e:
        set_state(video_id, "failed", {"error": str(e)})
        return {"video_id": video_id, "error": str(e), "stage": "metadata"}

    if not info:
        set_state(video_id, "failed", {"error": "无元数据"})
        return {"video_id": video_id, "error": "无元数据", "stage": "metadata"}

    channel = channel or info.get("channel") or info.get("uploader") or ""
    upload_date = upload_date or info.get("upload_date")
    title = title or info.get("title") or ""

    decision = decide(
        video_id=video_id,
        duration=info.get("duration"),
        live_status=info.get("live_status"),
        formats=info.get("formats") or [],
        config=config,
    )

    output_dir = _video_output_dir(channel, content_type, upload_date, title)
    dl_result = download_media(video_url, decision, config, output_dir, dry_run=dry_run)

    thumb_result: dict[str, Any] = {}
    if not dry_run and dl_result.get("downloaded"):
        thumb_dir = _thumb_output_dir(channel, content_type, upload_date, title)
        thumb_path = _download_thumbnail(video_url, thumb_dir, video_id)
        if thumb_path:
            thumb_result["thumbnail_path"] = thumb_path

        _save_video_url(channel, content_type, video_id, video_url, title, upload_date)

    if dl_result.get("downloaded") or dry_run:
        set_state(
            video_id,
            "media_ready",
            {
                "media_mode": decision.media_mode,
                "final_path": dl_result.get("final_path"),
                "filesize_mb": dl_result.get("filesize_mb"),
                "estimated_mb": decision.estimated_mb,
                "content_type": content_type,
                "thumbnail": thumb_result.get("thumbnail_path"),
            },
        )
    elif dl_result.get("error"):
        set_state(video_id, "failed", {"error": dl_result["error"]})
    else:
        set_state(video_id, "failed", {"error": "下载未完成"})

    return {**video_to_dict(decision), **dl_result, **thumb_result}


def main() -> None:
    parser = argparse.ArgumentParser(description="媒体策略引擎 + 下载管线")
    parser.add_argument("--dry-run", action="store_true", help="仅输出决策，不下载")
    parser.add_argument("--video-id", type=str, help="按 video ID 决策")
    parser.add_argument("--video-url", type=str, help="视频 URL（下载模式必需）")
    parser.add_argument("--download", action="store_true", help="执行实际下载")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--metadata", type=str, help="视频元数据 JSON 文件（离线模式）")
    parser.add_argument("--candidates", type=str, help="candidates.jsonl 路径（批量处理）")
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
            r = process_video(
                video_id=c["id"],
                video_url=c.get("url", f"https://www.youtube.com/watch?v={c['id']}"),
                config=config,
                dry_run=args.dry_run,
                channel=c.get("channel_handle", c.get("channel", "")),
                content_type=c.get("content_type", "video"),
                upload_date=c.get("upload_date"),
                title=c.get("title", ""),
            )
            results.append(r)

        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if args.metadata:
        metadata = json.loads(pathlib.Path(args.metadata).read_text(encoding="utf-8"))
        if isinstance(metadata, dict) and "id" in metadata:
            metadata = [metadata]

        decisions = []
        for video in metadata if isinstance(metadata, list) else [metadata]:
            decision = decide(
                video_id=video.get("id", ""),
                duration=video.get("duration"),
                live_status=video.get("live_status"),
                formats=video.get("formats", []),
                config=config,
            )
            decisions.append(video_to_dict(decision))

        print(json.dumps(decisions, ensure_ascii=False, indent=2))
        return

    if args.video_id:
        if args.download and args.video_url:
            result = process_video(
                video_id=args.video_id,
                video_url=args.video_url,
                config=config,
                dry_run=args.dry_run,
            )
        else:
            result = video_to_dict(
                decide(
                    video_id=args.video_id,
                    duration=None,
                    live_status=None,
                    formats=[],
                    config=config,
                )
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(
        json.dumps(
            {
                "status": "dry_run_ready",
                "message": "提供 --metadata / --video-id / --candidates 参数",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
