"""Deterministic relevance scoring (0-100). Transparent, cheap, runs before any LLM call."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable

from .models import Job


def _has(word: str, text: str) -> bool:
    return re.search(r"\b" + re.escape(word.lower()) + r"\b", text) is not None


def _recent(posted: str | None, days: int = 7) -> bool:
    if not posted:
        return False
    p = posted.lower()
    if re.search(r"\b(today|just now|hours? ago|yesterday)\b", p):
        return True
    m = re.search(r"(\d+)\s+days? ago", p)
    if m:
        return int(m.group(1)) <= days
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d %b %Y", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            d = datetime.strptime(posted[:len(datetime.now().strftime(fmt))], fmt).date()
            return (date.today() - d).days <= days
        except ValueError:
            continue
    return False


def score_job(job: Job, cfg: dict) -> Job:
    sc = cfg.get("scoring", {})
    title = job.title.lower()
    body = job.text.lower()
    reasons: list[str] = []
    score = 0

    # hard excludes on title
    for w in sc.get("exclude_title_words", []):
        if _has(w, title):
            job.score = 0
            job.score_reasons = [f"excluded: title contains '{w}'"]
            return job

    # title keywords (weighted; best 3)
    hits = []
    for w, pts in sc.get("title_keywords", {}).items():
        if _has(w, title):
            hits.append((pts, w))
    hits.sort(reverse=True)
    for pts, w in hits[:3]:
        score += pts
        reasons.append(f"title:{w}+{pts}")

    # location
    target = {c["code"] for c in cfg.get("targets", {}).get("countries", [])}
    if job.country in target:
        score += sc.get("target_country_bonus", 15)
        reasons.append(f"country:{job.country}")
        cities = [c.lower() for c in next((x for x in cfg["targets"]["countries"] if x["code"] == job.country), {}).get("cities", [])]
        if any(_has(c, job.location.lower()) for c in cities):
            score += sc.get("preferred_city_bonus", 5)
            reasons.append("preferred-city")
    elif job.country is None:
        score += sc.get("unknown_country_bonus", 5)
    else:
        score -= sc.get("other_country_penalty", 40)
        reasons.append(f"other-country:{job.country}")

    # skill / domain overlap in body (cap)
    overlap = [w for w in sc.get("skill_keywords", []) if _has(w, body)]
    pts = min(len(overlap) * sc.get("skill_points_each", 3), sc.get("skill_cap", 20))
    if pts:
        score += pts
        reasons.append("skills:" + ",".join(overlap[:6]))

    # seniority
    for w in sc.get("junior_words", []):
        if _has(w, title):
            score -= sc.get("junior_penalty", 15)
            reasons.append(f"junior:{w}")
            break

    # recency & source
    if _recent(job.posted):
        score += sc.get("recency_bonus", 5)
        reasons.append("recent")
    score += sc.get("source_bonus", {}).get(job.source.split(":")[0], 0)

    # nationality red flags (information only, still scored)
    for pat, msg in sc.get("red_flag_patterns", {}).items():
        if re.search(pat, body, flags=re.I):
            job.red_flags.append(msg)

    job.score = max(0, min(100, score))
    job.score_reasons = reasons
    return job


def score_all(jobs: Iterable[Job], cfg: dict) -> list[Job]:
    scored = [score_job(j, cfg) for j in jobs]
    scored.sort(key=lambda j: (j.score, j.first_seen or ""), reverse=True)
    return scored
