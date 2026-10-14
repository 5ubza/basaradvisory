"""Fetch the full posting text for a few top jobs (one request each). Prefers schema.org JobPosting JSON-LD,
falls back to the largest text block."""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .models import Job


def extract_description(html: str) -> tuple[str, dict]:
    soup = BeautifulSoup(html, "lxml")
    meta: dict = {}
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or "")
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                desc = BeautifulSoup(it.get("description", ""), "lxml").get_text("\n", strip=True)
                org = it.get("hiringOrganization", {})
                meta = {"company": org.get("name") if isinstance(org, dict) else "", "datePosted": it.get("datePosted"),
                        "validThrough": it.get("validThrough"), "employmentType": it.get("employmentType")}
                if desc:
                    return desc, meta
    for sel in ("article", "main", "[class*=description]", "[id*=description]", "body"):
        el = soup.select_one(sel)
        if el:
            txt = re.sub(r"\n{3,}", "\n\n", el.get_text("\n", strip=True))
            if len(txt) > 400:
                return txt[:20000], meta
    return "", meta


def enrich(job: Job, http) -> Job:
    if job.description or not job.url.startswith("http"):
        return job
    r = http.get(job.url, fixture=f"detail_{job.id}.html")
    if r is None:
        return job
    desc, meta = extract_description(r.text)
    if desc:
        job.description = desc
    if meta.get("company") and not job.company:
        job.company = meta["company"]
    if meta.get("datePosted") and not job.posted:
        job.posted = meta["datePosted"]
    job.meta.update({k: v for k, v in meta.items() if v})
    return job
