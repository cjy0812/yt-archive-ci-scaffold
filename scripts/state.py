"""
视频处理状态机。

状态流转：
  discovered → processing → media_ready → subtitle_ready → staged → released
  (任意阶段 → failed)

幂等保证：同一个 video_id 不会重复处理已完成步骤。
"""

from __future__ import annotations

import json
import pathlib
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"

VALID_STATES = frozenset(
    {
        "discovered",
        "processing",
        "media_ready",
        "subtitle_ready",
        "staged",
        "released",
        "failed",
    }
)


def _state_path(video_id: str) -> pathlib.Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"{video_id}.json"


def get_state(video_id: str) -> dict[str, Any] | None:
    p = _state_path(video_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def set_state(video_id: str, status: str, extra: dict[str, Any] | None = None) -> None:
    if status not in VALID_STATES:
        raise ValueError(f"无效状态: {status}，合法值: {VALID_STATES}")

    current = get_state(video_id) or {}
    current["video_id"] = video_id
    current["status"] = status
    current["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    if extra:
        current.update(extra)

    p = _state_path(video_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def is_completed(video_id: str, min_status: str = "staged") -> bool:
    state = get_state(video_id)
    if not state:
        return False
    status_order = [
        "discovered",
        "processing",
        "media_ready",
        "subtitle_ready",
        "staged",
        "released",
    ]
    current_idx = status_order.index(state.get("status", "discovered")) if state.get("status") in status_order else -1
    min_idx = status_order.index(min_status)
    return current_idx >= min_idx


def list_by_status(status: str) -> list[str]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    result: list[str] = []
    for f in sorted(STATE_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("status") == status:
                result.append(f.stem)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return result


def list_ready_for_subtitle() -> list[str]:
    return list_by_status("media_ready")
