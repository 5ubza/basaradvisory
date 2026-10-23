"""GulfTalent title/country listing pages.
URL pattern (verified Oct 2026): https://www.gulftalent.com/{country}/jobs/title/{keyword}
robots.txt (Oct 2026): `User-agent: * Allow: /` (AI *training* crawlers are blocked; this is not one).
When a country has no match GulfTalent shows "Jobs found in nearby locations" (other GCC countries); those are
kept but tagged with their real country so the scorer can down-rank them.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Job, detect_country

BASE = "https://www.gulftalent.com"
JOB_RE = re.compile(r"^https?://www\.gulftalent\.com/([a-z-]+)/jobs/([a-z0-9-]+)-(\d+)/?$")
COUNTRY_FROM_PATH = {"saudi-arabia": "SA", "qatar": "QA", "uae": "AE", "kuwait": "KW", "oman": "OM", "bahrain": "BH"}


def available(cfg):
    return True, "no key needed"


def slug(q: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")


def parse_listing(html: str, country_code: str, source="gulftalent") -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    jobs: list[Job] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            href = BASE + href
        m = JOB_RE.match(href)
        if not m or href in seen:
            continue
        seen.add(href)
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        row = a.find_parent("tr")
        company, location, posted = "", "", None
        if row:
            tds = row.find_all("td")
            if tds:
                # company is the trailing text node of the first cell
                texts = [t.strip() for t in tds[0].find_all(string=True, recursive=True) if t.strip()]
                texts = [t for t in texts if t != title]
                company = texts[-1] if texts else ""
            if len(tds) > 1:
                loc_span = tds[1].find("span")
                location = (loc_span.get("title") or loc_span.get_text(strip=True)) if loc_span else tds[1].get_text(strip=True)
            if len(tds) > 2:
                posted = tds[2].get_text(strip=True) or None
        country = COUNTRY_FROM_PATH.get(m.group(1)) or detect_country(location) or country_code
        jobs.append(Job(source=source, title=title, company=company, location=location, url=href,
                        posted=posted, country=country, meta={"gulftalent_id": m.group(3)}))
    return jobs


def fetch(cfg, http) -> list[Job]:
    out: list[Job] = []
    max_q = int(cfg["sources"].get("gulftalent", {}).get("max_queries", 0) or 0)
    queries = cfg["targets"]["queries"][:max_q] if max_q else cfg["targets"]["queries"]
    for c in cfg["targets"]["countries"]:
        for q in queries:
            url = f"{BASE}/{c['gulftalent_slug']}/jobs/title/{slug(q)}"
            r = http.get(url, fixture=f"gulftalent_{c['code'].lower()}_{slug(q)}.html")
            if r is None:
                continue
            out.extend(parse_listing(r.text, c["code"]))
    return out
