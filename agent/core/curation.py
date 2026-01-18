from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from .storage import ensure_dir, get_data_dir, utc_now_iso


@dataclass
class CurationState:
    excluded_message_ids: List[str]
    quality_labels: Dict[str, str]  # message_id -> "good" | "bad" | "unknown"
    updated_at: str


def curation_state_path() -> Path:
    return get_data_dir() / "curation" / "state.json"


def load_curation_state() -> CurationState:
    path = curation_state_path()
    if not path.exists():
        return CurationState(excluded_message_ids=[], quality_labels={}, updated_at=utc_now_iso())
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return CurationState(excluded_message_ids=[], quality_labels={}, updated_at=utc_now_iso())

    excluded = obj.get("excluded_message_ids", [])
    if not isinstance(excluded, list):
        excluded = []
    excluded = [x for x in excluded if isinstance(x, str) and x]

    q = obj.get("quality_labels", {})
    if not isinstance(q, dict):
        q = {}
    quality: Dict[str, str] = {}
    for k, v in q.items():
        if not isinstance(k, str) or not k:
            continue
        if v not in {"good", "bad", "unknown"}:
            continue
        quality[k] = v

    updated_at = obj.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at:
        updated_at = utc_now_iso()

    return CurationState(excluded_message_ids=excluded, quality_labels=quality, updated_at=updated_at)


def save_curation_state(state: CurationState) -> Path:
    path = curation_state_path()
    ensure_dir(path.parent)
    payload = {
        "excluded_message_ids": sorted(set(state.excluded_message_ids)),
        "quality_labels": state.quality_labels,
        "updated_at": utc_now_iso(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path

