"""Crash-safe local progress storage, retaining the legacy JSON format."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

PROGRESS_FILE = Path(__file__).resolve().parents[1] / "progress.json"


def _empty_progress() -> dict[str, Any]:
    return {"completed": [], "failed": [], "current_page": 1}


def _normalise_progress(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _empty_progress()
    completed = data.get("completed", [])
    failed = data.get("failed", [])
    if not isinstance(completed, list):
        completed = []
    if not isinstance(failed, list):
        failed = []
    page = data.get("current_page", 1)
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    return {
        "completed": list(dict.fromkeys(x for x in completed if isinstance(x, str))),
        "failed": list(dict.fromkeys(x for x in failed if isinstance(x, str))),
        "current_page": page,
    }


def load_progress(path: str | Path = PROGRESS_FILE) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return _empty_progress()
    try:
        return _normalise_progress(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        # Leave a damaged file untouched so that potentially useful data is not lost.
        return _empty_progress()


def save_progress(progress: dict[str, Any], path: str | Path = PROGRESS_FILE) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = _normalise_progress(progress)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n",
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(clean, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def mark_completed(progress: dict[str, Any], question_name: str) -> None:
    progress.setdefault("completed", [])
    progress.setdefault("failed", [])
    if question_name not in progress["completed"]:
        progress["completed"].append(question_name)
    if question_name in progress["failed"]:
        progress["failed"].remove(question_name)


def mark_failed(progress: dict[str, Any], question_name: str, error: str = "") -> None:
    progress.setdefault("failed", [])
    if question_name not in progress["failed"]:
        progress["failed"].append(question_name)


def is_completed(progress: dict[str, Any], question_name: str) -> bool:
    return question_name in progress.get("completed", [])
