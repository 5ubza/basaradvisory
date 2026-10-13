"""Seen-job state. Only hashed ids and dates are stored, so the file is safe in a public repo."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


class SeenState:
    def __init__(self, path: str | Path, keep_days: int = 120):
        self.path = Path(path)
        self.keep_days = keep_days
        self.data: dict[str, str] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text("utf-8"))
            except json.JSONDecodeError:
                self.data = {}

    def is_new(self, job_id: str) -> bool:
        return job_id not in self.data

    def mark(self, job_id: str) -> None:
        self.data.setdefault(job_id, date.today().isoformat())

    def prune(self) -> None:
        cutoff = (date.today() - timedelta(days=self.keep_days)).isoformat()
        self.data = {k: v for k, v in self.data.items() if v >= cutoff}

    def save(self) -> None:
        self.prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=0, sort_keys=True), "utf-8")
