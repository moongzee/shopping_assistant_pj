from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional


@dataclass(frozen=True)
class SseEvent:
    event: str
    data: Dict[str, Any]
    id: Optional[str] = None

    def encode(self) -> bytes:
        lines = []
        if self.id:
            lines.append(f"id: {self.id}")
        if self.event:
            lines.append(f"event: {self.event}")
        payload = json.dumps(self.data, ensure_ascii=False)
        lines.append(f"data: {payload}")
        return ("\n".join(lines) + "\n\n").encode("utf-8")


def merge_updates(state: Dict[str, Any], update: Dict[str, Any]) -> None:
    for k, v in update.items():
        state[k] = v


async def chunk_text(text: str, chunk_chars: int) -> AsyncIterator[str]:
    if not text:
        return
    step = max(int(chunk_chars), 1)
    for i in range(0, len(text), step):
        yield text[i : i + step]

