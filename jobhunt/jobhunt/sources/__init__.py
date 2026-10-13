"""Source registry. Each adapter exposes `fetch(cfg, http) -> list[Job]` and `available(cfg) -> (bool, reason)`."""
from __future__ import annotations

import importlib
import logging
from typing import Callable

from ..models import Job

log = logging.getLogger(__name__)

ADAPTERS = {
    "bayt": "jobhunt.sources.bayt",
    "naukrigulf": "jobhunt.sources.naukrigulf",
    "gulftalent": "jobhunt.sources.gulftalent",
    "careerjet": "jobhunt.sources.apis",
    "jooble": "jobhunt.sources.apis",
    "jsearch": "jobhunt.sources.apis",
    "serpapi": "jobhunt.sources.apis",
    "brightdata_linkedin": "jobhunt.sources.apis",
    "email_alerts": "jobhunt.sources.email_alerts",
    "career_pages": "jobhunt.sources.career_pages",
}


def _fn(name: str, kind: str) -> Callable:
    mod = importlib.import_module(ADAPTERS[name])
    return getattr(mod, f"{kind}_{name}", None) or getattr(mod, kind)


def source_status(cfg: dict) -> list[tuple[str, bool, str]]:
    out = []
    for name in ADAPTERS:
        enabled = cfg.get("sources", {}).get(name, {}).get("enabled", False)
        if not enabled:
            out.append((name, False, "disabled in config.yaml"))
            continue
        ok, why = _fn(name, "available")(cfg)
        out.append((name, ok, why))
    return out


def run_sources(cfg: dict, http, only: list[str] | None = None) -> tuple[list[Job], dict[str, int]]:
    jobs: list[Job] = []
    counts: dict[str, int] = {}
    for name, ok, why in source_status(cfg):
        if only and name not in only:
            continue
        if not ok:
            log.info("skip %-20s %s", name, why)
            continue
        try:
            got = _fn(name, "fetch")(cfg, http)
        except Exception as e:  # one broken source must not kill the run
            log.exception("source %s failed: %s", name, e)
            got = []
        counts[name] = len(got)
        log.info("%-20s %d jobs", name, len(got))
        jobs.extend(got)
    return jobs, counts
