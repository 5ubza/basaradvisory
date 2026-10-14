"""Recruiter discovery without touching LinkedIn programmatically.

1. Registry: sourced agencies in data/recruiters.yaml.
2. Detection: postings whose poster looks like an intermediary (agency markers) become leads with the job link.
3. Manual LinkedIn links: for each shortlisted job we build a LinkedIn *people search URL* for the hiring company
   ("<company> talent acquisition"); you click it yourself. No automation runs on LinkedIn.
4. Optional: Hunter.io domain search (HUNTER_API_KEY) to find a recruiter mailbox pattern for a company domain.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus

import yaml

from .config import env
from .models import Job, RecruiterLead

log = logging.getLogger(__name__)


def load_registry(path: str) -> tuple[list[RecruiterLead], list[str]]:
    data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    leads = [RecruiterLead(name=r["name"], kind=r.get("kind", "agency"), country=str(r.get("country", "")),
                           url=r.get("url", ""), email=r.get("email", ""), note=r.get("note", ""), source=r.get("source", ""))
             for r in data.get("registry", [])]
    return leads, [m.lower() for m in data.get("agency_markers", [])]


def detect_agency_posters(jobs: list[Job], markers: list[str]) -> list[RecruiterLead]:
    by_name: dict[str, RecruiterLead] = {}
    for j in jobs:
        c = (j.company or "").strip()
        if not c:
            continue
        cl = c.lower()
        if any(m in cl for m in markers):
            lead = by_name.setdefault(cl, RecruiterLead(name=c, kind="agency (detected)", country=j.country or "",
                                                         url=j.url, source=j.source, note="Posted a matching role"))
            lead.related_job_ids.append(j.id)
    return list(by_name.values())


def linkedin_people_search(company: str, extra: str = "talent acquisition") -> str:
    return "https://www.linkedin.com/search/results/people/?keywords=" + quote_plus(f"{company} {extra}")


def linkedin_company_jobs_search(company: str) -> str:
    return "https://www.linkedin.com/jobs/search/?keywords=" + quote_plus(company)


def hunter_domain_search(domain: str, http) -> list[dict]:
    key = env("HUNTER_API_KEY")
    if not key or not domain:
        return []
    data = http.get_json("https://api.hunter.io/v2/domain-search",
                         params={"domain": domain, "department": "hr", "limit": 5, "api_key": key})
    return (data or {}).get("data", {}).get("emails", []) or []


def guess_domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)/", url + "/")
    host = m.group(1) if m else ""
    if any(b in host for b in ("bayt.com", "gulftalent.com", "naukrigulf.com", "linkedin.com", "jooble", "careerjet",
                               "indeed", "glassdoor", "jobviewtrack")):
        return ""
    return host
