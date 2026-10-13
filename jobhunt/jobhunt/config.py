from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PKG_DIR = Path(__file__).resolve().parent
ROOT = PKG_DIR.parent  # jobhunt/ project dir (contains config.yaml, profile/, data/, state/)


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = load_yaml(Path(path) if path else ROOT / "config.yaml")
    cfg.setdefault("paths", {})
    cfg["paths"].setdefault("cv", str(ROOT / "profile" / "cv.yaml"))
    cfg["paths"].setdefault("recruiters", str(ROOT / "data" / "recruiters.yaml"))
    cfg["paths"].setdefault("state", str(ROOT / "state" / "seen.json"))
    cfg["paths"].setdefault("out", str(ROOT / "out"))
    return cfg


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def has_env(*names: str) -> bool:
    return all(env(n) for n in names)
