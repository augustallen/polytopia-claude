"""Per-game JSONL log: every state, prompt, decision, action and result, for replay and analysis."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class GameLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.path.open("a", encoding="utf-8")

    def log(self, event: str, **fields: Any) -> None:
        record = {"ts": round(time.time(), 3), "event": event, **fields}
        self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> "GameLogger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_log(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
