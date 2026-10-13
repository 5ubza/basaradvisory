"""Bayt.com country/keyword listing pages.
URL pattern (verified Oct 2026): https://www.bayt.com/en/{country}/jobs/{keyword}-jobs/
robots.txt (Oct 2026) disallows /en/jobs/*-jobs/ and any *filters[ URLs; the country-scoped path above is not
listed. We still check robots at runtime, send one request per query/country, and never use filters.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..models import Job

BASE = "https://www.bayt.com"


def available(cfg):
    return True, "no key needed"


def slug(q: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")


def parse_listing(html: str, country_code: str, source="bayt") -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    jobs: list[Job] = []
    for li in soup.select("li[data-js-job]"):
        a = li.select_one("h2 a[href]")
        if not a:
            continue
        url = a["href"]
        if url.startswith("/"):
            url = BASE + url
        title = a.get_text(" ", strip=True)
        comp_el = li.select_one(".job-company-location-wrapper a, .jb-company, b.jb-company")
        company = comp_el.get_text(" ", strip=True) if comp_el else ""
        loc_el = li.select_one("dt.jb-label-location, .jb-loc")
        location = re.sub(r"\s+", " ", loc_el.get_text(" ", strip=True)) if loc_el else ""
        desc_el = li.select_one(".jb-descr")
        snippet = desc_el.get_text(" ", strip=True).replace("Summary:", "").strip() if desc_el else ""
        posted = None
        d = li.select_one("[data-automation-jobactivedate]")
        if d and d.get("data-automation-jobactivedate", "").isdigit():
            posted = datetime.fromtimestamp(int(d["data-automation-jobactivedate"]), tz=timezone.utc).date().isoformat()
        else:
            dt = li.select_one(".jb-date")
            posted = dt.get_text(" ", strip=True) if dt else None
        jobs.append(Job(source=source, title=title, company=company, location=location, url=url,
                        posted=posted, snippet=snippet, country=None,
                        meta={"bayt_job_id": li.get("data-job-id")}))
    if not jobs:  # fallback: schema.org ItemList of job URLs
        for sc in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(sc.string or "")
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                for it in data.get("itemListElement", []):
                    u = it.get("url", "")
                    if "/jobs/" in u:
                        t = u.rstrip("/").split("/")[-1]
                        t = re.sub(r"-\d+$", "", t).replace("-", " ").title()
                        jobs.append(Job(source=source, title=t, url=u, country=country_code))
    for j in jobs:
        if not j.country:
            j.country = country_code
    return jobs


def fetch(cfg, http) -> list[Job]:
    out: list[Job] = []
    for c in cfg["targets"]["countries"]:
        for q in cfg["targets"]["queries"]:
            url = f"{BASE}/en/{c['bayt_slug']}/jobs/{slug(q)}-jobs/"
            r = http.get(url, fixture=f"bayt_{c['code'].lower()}_{slug(q)}.html")
            if r is None:
                continue
            out.extend(parse_listing(r.text, c["code"]))
    return out
