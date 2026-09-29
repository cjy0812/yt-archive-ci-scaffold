#!/usr/bin/env python3
"""
周度 Release 聚合器。

1. 下载最近 7 天的 staging artifacts
2. 解压聚合媒体文件
3. 根据 video ID 去重
4. 按视频/直播分组生成 release-manifest.json
5. 上传到 GitHub Release（通过 gh CLI）
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tarfile
import tomllib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.toml"
RELEASE_DIR = ROOT / "release"


def load_config() -> dict[str, Any]:
    return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def download_artifacts() -> list[pathlib.Path]:
    work_dir = ROOT / "work"
    artifacts_dir = work_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            "daily.yml",
            "--limit",
            "7",
            "--status",
            "success",
            "--json",
            "databaseId",
            "-L",
            "7",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"[WARN] gh run list 失败: {result.stderr}", file=sys.stderr)
        return []

    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    downloaded: list[pathlib.Path] = []
    for run in runs:
        run_id = run["databaseId"]
        out_dir = artifacts_dir / str(run_id)
        out_dir.mkdir(parents=True, exist_ok=True)

        dl = subprocess.run(
            ["gh", "run", "download", str(run_id), "--dir", str(out_dir)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        if dl.returncode == 0:
            downloaded.append(out_dir)
            print(f"[INFO] 下载 run {run_id} 的 artifacts → {out_dir}")

    return downloaded


def _collect_media_files(
    media_root: pathlib.Path,
) -> dict[str, list[pathlib.Path]]:
    """扫描 media 目录，按视频/直播分组。"""
    grouped: dict[str, list[pathlib.Path]] = {"video": [], "live": []}
    if not media_root.exists():
        return grouped

    for item in media_root.rglob("*"):
        if item.is_file():
            for ct in ("video", "live"):
                if f"/{ct}/" in item.as_posix() or f"\\{ct}\\" in item.as_posix():
                    grouped[ct].append(item)
                    break
            else:
                grouped["video"].append(item)

    return grouped


def aggregate_media(artifact_dirs: list[pathlib.Path]) -> dict[str, Any]:
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    media_dest = RELEASE_DIR / "media"
    media_dest.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "videos": [],
        "live": [],
        "total_video_count": 0,
        "total_live_count": 0,
        "total_video_size_mb": 0,
        "total_live_size_mb": 0,
    }

    seen: set[str] = set()

    for ad in artifact_dirs:
        for tgz in sorted(ad.rglob("*.tar.gz")):
            try:
                with tarfile.open(tgz, "r:gz") as tar:
                    for member in tar.getmembers():
                        if member.name in seen:
                            continue
                        seen.add(member.name)

                        name = pathlib.Path(member.name).name
                        if not name or name == ".":
                            continue

                        dest = media_dest / name
                        if dest.exists():
                            continue

                        f = tar.extractfile(member)
                        if f:
                            dest.write_bytes(f.read())
            except Exception as e:
                print(f"[WARN] 解压 {tgz} 失败: {e}", file=sys.stderr)

    grouped = _collect_media_files(media_dest)

    for ct in ("video", "live"):
        entries: list[dict[str, Any]] = []
        total = 0.0
        for mf in sorted(grouped[ct]):
            vid_id = mf.stem.rsplit(".", 1)[0] if "." in mf.stem else mf.stem
            size_mb = mf.stat().st_size / (1024 * 1024)
            entries.append(
                {
                    "video_id": vid_id,
                    "filename": mf.name,
                    "size_mb": round(size_mb, 2),
                }
            )
            total += size_mb

        if ct == "video":
            manifest["videos"] = entries
            manifest["total_video_count"] = len(entries)
            manifest["total_video_size_mb"] = round(total, 2)
        else:
            manifest["live"] = entries
            manifest["total_live_count"] = len(entries)
            manifest["total_live_size_mb"] = round(total, 2)

    manifest_path = RELEASE_DIR / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return manifest


def create_release(manifest: dict[str, Any]) -> str | None:
    import datetime

    tag = f"v{datetime.datetime.utcnow().strftime('%Y.%m.%d')}"
    title = f"YouTube Archive - {datetime.datetime.utcnow().strftime('%Y-%m-%d')}"
    body = "## 本周归档\n\n"
    body += "### 视频 (Video)\n"
    body += f"- 数量: {manifest['total_video_count']}\n"
    body += f"- 大小: {manifest['total_video_size_mb']} MB\n"
    body += "### 直播 (Live)\n"
    body += f"- 数量: {manifest['total_live_count']}\n"
    body += f"- 大小: {manifest['total_live_size_mb']} MB\n\n"

    body += "### 视频详情\n\n"
    for v in manifest.get("videos", [])[:10]:
        body += f"- `{v['video_id']}`: {v['filename']} ({v['size_mb']} MB)\n"
    if len(manifest.get("videos", [])) > 10:
        body += f"\n... 及 {len(manifest['videos']) - 10} 个视频\n"

    body += "\n### 直播详情\n\n"
    for v in manifest.get("live", [])[:10]:
        body += f"- `{v['video_id']}`: {v['filename']} ({v['size_mb']} MB)\n"
    if len(manifest.get("live", [])) > 10:
        body += f"\n... 及 {len(manifest['live']) - 10} 个直播\n"

    result = subprocess.run(
        ["gh", "release", "create", tag, "--title", title, "--notes", body, "--draft"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"[WARN] 创建 Release 失败: {result.stderr}", file=sys.stderr)
        return None

    media_dir = RELEASE_DIR / "media"
    if media_dir.exists():
        for f in sorted(media_dir.iterdir()):
            if f.is_file():
                subprocess.run(
                    ["gh", "release", "upload", tag, str(f)],
                    capture_output=True,
                    text=True,
                    cwd=str(ROOT),
                )

    manifest_path = RELEASE_DIR / "release-manifest.json"
    subprocess.run(
        ["gh", "release", "upload", tag, str(manifest_path)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )

    return tag


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="周度 Release 聚合器")
    parser.add_argument("--dry-run", action="store_true", help="仅聚合，不创建 Release")
    args = parser.parse_args()

    artifact_dirs = download_artifacts()
    if not artifact_dirs:
        print("[INFO] 无可用 artifacts，跳过")
        return

    manifest = aggregate_media(artifact_dirs)

    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        print("[INFO] dry-run 模式，不创建 Release")
        return

    tag = create_release(manifest)
    if tag:
        print(f"[INFO] Release 创建成功: {tag}")


if __name__ == "__main__":
    main()
