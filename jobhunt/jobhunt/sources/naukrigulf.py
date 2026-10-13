"""Naukrigulf keyword/country listing pages.
URL pattern (verified Oct 2026): https://www.naukrigulf.com/{keyword}-jobs-in-{country}
robots.txt (Oct 2026) does not disallow these listing paths.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..models import Job

BASE = "https://www.naukrigulf.com"


def available(cfg):
    return True, "no key needed"


def slug(q: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")


def parse_listing(html: str, country_code: str, source="naukrigulf") -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    jobs: list[Job] = []
    for box in soup.select("div.ng-box.srp-tuple, div.ng-box"):
        a = box.select_one("a.info-position[href], a[href*='-jid-']")
        if not a:
            continue
        url = a["href"]
        if url.startswith("/"):
            url = BASE + url
        t = box.select_one(".designation-title")
        title = t.get_text(" ", strip=True) if t else a.get_text(" ", strip=True)
        org = box.select_one(".info-org")
        company = (org.get("title") or org.get_text(" ", strip=True)) if org else ""
        loc = box.select_one(".info-loc span:last-child, .info-loc")
        location = loc.get_text(" ", strip=True) if loc else ""
        exp = box.select_one(".info-exp span:last-child")
        d = box.select_one(".description")
        tm = box.select_one(".foot .time")
        jobs.append(Job(source=source, title=title, company=company, location=location, url=url,
                        posted=tm.get_text(strip=True) if tm else None,
                        snippet=d.get_text(" ", strip=True) if d else "",
                        meta={"experience": exp.get_text(strip=True) if exp else ""}))
    if not jobs:
        for sc in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(sc.string or "")
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                for it in data.get("itemListElement", []):
                    u = it.get("url", "")
                    if "-jid-" in u:
                        jobs.append(Job(source=source, title=it.get("name", "").strip(),
                                        url=(BASE + u) if u.startswith("/") else u, country=country_code))
    for j in jobs:
        if not j.country:
            j.country = country_code
    return jobs


def fetch(cfg, http) -> list[Job]:
    out: list[Job] = []
    for c in cfg["targets"]["countries"]:
        for q in cfg["targets"]["queries"]:
            url = f"{BASE}/{slug(q)}-jobs-in-{c['naukrigulf_slug']}"
            r = http.get(url, fixture=f"naukrigulf_{c['code'].lower()}_{slug(q)}.html")
            if r is None:
                continue
            out.extend(parse_listing(r.text, c["code"]))
    return out
