"""Watch employer career pages listed under `employers:` in config.yaml.

type html           - fetch page, keep links whose text matches the configured keywords.
type workday        - POST {url}/jobs (Workday CXS JSON, community-documented pattern:
                      https://<host>/wday/cxs/<tenant>/<site>/jobs with {"searchText": ..., "limit": 20, "offset": 0}).
type successfactors - same as html (SuccessFactors career sites render job links server-side).
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Job

log = logging.getLogger(__name__)


def available(cfg):
    return bool(cfg.get("employers")), "employers list present" if cfg.get("employers") else "no employers configured"


def _kw_re(cfg) -> re.Pattern:
    kws = cfg["sources"]["career_pages"].get("keywords", ["economist"])
    return re.compile("|".join(r"\b" + re.escape(k) + r"\b" for k in kws), re.I)


def parse_html_page(html: str, base_url: str, employer: dict, kw: re.Pattern) -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, Job] = {}
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if not text or len(text) > 120 or not kw.search(text):
            continue
        href = urljoin(base_url, a["href"])
        if href.rstrip("/") == base_url.rstrip("/") or href.startswith("mailto:") or "#" == a["href"].strip():
            continue
        if href in out:
            continue
        out[href] = Job(source="career_page", title=text, company=employer["name"], location=employer.get("country", ""),
                        url=href, country=employer.get("country"), meta={"employer_page": base_url})
    # also catch headings that are not links (e.g. KAPSARC lists titles in <h3> inside a card)
    for h in soup.find_all(["h2", "h3", "h4"]):
        text = h.get_text(" ", strip=True)
        if text and len(text) < 120 and kw.search(text):
            a = h.find("a", href=True) or (h.find_parent("a", href=True))
            href = urljoin(base_url, a["href"]) if a else base_url + "#" + re.sub(r"\W+", "-", text.lower())
            if href not in out:
                out[href] = Job(source="career_page", title=text, company=employer["name"],
                                location=employer.get("country", ""), url=href, country=employer.get("country"),
                                meta={"employer_page": base_url})
    return list(out.values())


def fetch(cfg, http) -> list[Job]:
    kw = _kw_re(cfg)
    out: list[Job] = []
    for emp in cfg.get("employers", []):
        t = emp.get("type", "html")
        fixture = "career_" + re.sub(r"\W+", "_", emp["name"].lower()) + ".html"
        if t in ("html", "successfactors"):
            r = http.get(emp["url"], fixture=fixture)
            if r is not None:
                out.extend(parse_html_page(r.text, emp["url"], emp, kw))
        elif t == "workday":
            for q in cfg["sources"]["career_pages"].get("workday_queries", ["economist"]):
                data = http.post_json(emp["url"].rstrip("/") + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": 0,
                                                                          "searchText": q},
                                      headers={"Accept": "application/json"})
                base = emp["url"].split("/wday/")[0]
                for p in (data or {}).get("jobPostings", []):
                    out.append(Job(source="career_page", title=p.get("title", ""), company=emp["name"],
                                   location=p.get("locationsText", ""), url=urljoin(base, p.get("externalPath", "")),
                                   posted=p.get("postedOn"), country=emp.get("country")))
    return out
