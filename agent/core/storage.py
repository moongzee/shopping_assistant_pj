from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_data_dir() -> Path:
    env = os.getenv("AGENT_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (Path(__file__).resolve().parents[1] / "data").resolve()


def chat_log_path() -> Path:
    return get_data_dir() / "logs" / "chat.jsonl"


def feedback_log_path() -> Path:
    return get_data_dir() / "logs" / "feedback.jsonl"

