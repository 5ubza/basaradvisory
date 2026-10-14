"""Key-based job APIs. Each one is skipped cleanly when its key is missing.

careerjet  - https://www.careerjet.com/partners/api  (Basic auth: key as username, empty password;
             endpoint https://search.api.careerjet.net/v4/query; locales en_SA and en_QA exist)
jooble     - https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation
             (POST https://{country-domain}/api/{key}; one key per country domain; free plan = 500 requests
             LIFETIME per key, so we run at most 1 request per query per country per day)
jsearch    - https://www.openwebninja.com/api/jsearch (Google for Jobs aggregator; `country` ISO param)
serpapi    - https://serpapi.com/google-jobs-api (engine=google_jobs, gl=sa / gl=qa are supported countries)
brightdata - https://docs.brightdata.com/products/scrapers/linkedin/introduction (LinkedIn Jobs dataset
             gd_lpfll7v5hcqtkxl6l, discover by keyword). OFF by default - see README on LinkedIn's User Agreement.
"""
from __future__ import annotations

import logging
import time
from base64 import b64encode

from ..config import env
from ..models import Job

log = logging.getLogger(__name__)


# ------------------------------------------------------------------------------------------ Careerjet
def available_careerjet(cfg):
    return (bool(env("CAREERJET_API_KEY")), "CAREERJET_API_KEY" if not env("CAREERJET_API_KEY") else "key present")


def fetch_careerjet(cfg, http) -> list[Job]:
    key = env("CAREERJET_API_KEY")
    out: list[Job] = []
    auth_header = {"Authorization": "Basic " + b64encode(f"{key}:".encode()).decode()}
    for c in cfg["targets"]["countries"]:
        for q in cfg["targets"]["queries"]:
            params = {"locale_code": c["careerjet_locale"], "keywords": q, "sort": "date", "page_size": 50,
                      "user_ip": env("JOBHUNT_PUBLIC_IP", "127.0.0.1"), "user_agent": http.s.headers["User-Agent"]}
            data = http.get_json("https://search.api.careerjet.net/v4/query", params=params, headers=auth_header)
            if not data or data.get("type") != "JOBS":
                continue
            for j in data.get("jobs", []):
                out.append(Job(source="careerjet", title=j.get("title", ""), company=j.get("company", "") or "",
                               location=j.get("locations", "") or "", url=j.get("url", ""), posted=j.get("date"),
                               snippet=j.get("description", "") or "", country=c["code"],
                               meta={"salary": j.get("salary")}))
    return out


# ------------------------------------------------------------------------------------------ Jooble
def available_jooble(cfg):
    keys = [k for k in ("JOOBLE_API_KEY_SA", "JOOBLE_API_KEY_QA") if env(k)]
    return (bool(keys), ", ".join(keys) if keys else "JOOBLE_API_KEY_SA / JOOBLE_API_KEY_QA")


def fetch_jooble(cfg, http) -> list[Job]:
    out: list[Job] = []
    for c in cfg["targets"]["countries"]:
        key = env(f"JOOBLE_API_KEY_{c['code']}")
        if not key:
            continue
        for q in cfg["targets"]["queries"]:
            payload = {"keywords": q, "location": c["name"], "page": 1, "ResultOnPage": 50}
            data = http.post_json(f"https://{c['jooble_host']}/api/{key}", payload)
            if not data:
                continue
            for j in data.get("jobs", []):
                out.append(Job(source="jooble", title=j.get("title", ""), company=j.get("company", "") or "",
                               location=j.get("location", "") or "", url=j.get("link", ""), posted=j.get("updated"),
                               snippet=j.get("snippet", "") or "", country=c["code"],
                               meta={"salary": j.get("salary"), "via": j.get("source")}))
    return out


# ------------------------------------------------------------------------------------------ JSearch
def available_jsearch(cfg):
    return (bool(env("JSEARCH_API_KEY")), "key present" if env("JSEARCH_API_KEY") else "JSEARCH_API_KEY")


def fetch_jsearch(cfg, http) -> list[Job]:
    out: list[Job] = []
    headers = {"x-api-key": env("JSEARCH_API_KEY")}
    for c in cfg["targets"]["countries"]:
        for q in cfg["targets"]["queries"]:
            params = {"query": f"{q} jobs in {c['name']}", "country": c["code"].lower(), "language": "en",
                      "date_posted": "week", "num_pages": 1}
            data = http.get_json("https://api.openwebninja.com/jsearch/search-v2", params=params, headers=headers)
            if not data:
                continue
            for j in data.get("data", []):
                loc = ", ".join(x for x in [j.get("job_city"), j.get("job_state"), j.get("job_country")] if x)
                out.append(Job(source="jsearch", title=j.get("job_title", ""), company=j.get("employer_name", "") or "",
                               location=loc, url=j.get("job_apply_link") or j.get("job_google_link", ""),
                               posted=j.get("job_posted_at_datetime_utc"), snippet=(j.get("job_description") or "")[:600],
                               description=j.get("job_description") or "", country=c["code"],
                               meta={"publisher": j.get("job_publisher")}))
    return out


# ------------------------------------------------------------------------------------------ SerpApi
def available_serpapi(cfg):
    return (bool(env("SERPAPI_API_KEY")), "key present" if env("SERPAPI_API_KEY") else "SERPAPI_API_KEY")


def fetch_serpapi(cfg, http) -> list[Job]:
    out: list[Job] = []
    for c in cfg["targets"]["countries"]:
        for q in cfg["targets"]["queries"]:
            params = {"engine": "google_jobs", "q": q, "location": c["name"], "gl": c["google_gl"], "hl": "en",
                      "api_key": env("SERPAPI_API_KEY")}
            data = http.get_json("https://serpapi.com/search.json", params=params)
            if not data:
                continue
            for j in data.get("jobs_results", []):
                link = ""
                for opt in j.get("apply_options", []) or []:
                    link = opt.get("link") or link
                    if link:
                        break
                link = link or j.get("share_link", "")
                ext = j.get("detected_extensions", {}) or {}
                out.append(Job(source="google_jobs", title=j.get("title", ""), company=j.get("company_name", "") or "",
                               location=j.get("location", "") or "", url=link, posted=ext.get("posted_at"),
                               snippet=(j.get("description") or "")[:600], description=j.get("description") or "",
                               country=c["code"], meta={"via": j.get("via")}))
    return out


# ------------------------------------------------------------------------------------------ Bright Data (LinkedIn Jobs dataset)
BD_DATASET = "gd_lpfll7v5hcqtkxl6l"


def available_brightdata_linkedin(cfg):
    return (bool(env("BRIGHTDATA_API_KEY")), "key present" if env("BRIGHTDATA_API_KEY") else "BRIGHTDATA_API_KEY")


def fetch_brightdata_linkedin(cfg, http) -> list[Job]:
    key = env("BRIGHTDATA_API_KEY")
    headers = {"Authorization": f"Bearer {key}"}
    opts = cfg["sources"]["brightdata_linkedin"]
    inputs = []
    for c in cfg["targets"]["countries"]:
        for q in cfg["targets"]["queries"][:4]:
            inputs.append({"location": c["cities"][0] + ", " + c["name"], "keyword": q, "country": c["code"],
                           "time_range": opts.get("time_range", "Past week")})
    trig = http.post_json(f"https://api.brightdata.com/datasets/v3/trigger?dataset_id={BD_DATASET}"
                          "&type=discover_new&discover_by=keyword&format=json", inputs, headers=headers)
    if not trig or "snapshot_id" not in trig:
        return []
    sid = trig["snapshot_id"]
    for _ in range(40):  # up to ~10 minutes
        prog = http.get_json(f"https://api.brightdata.com/datasets/v3/progress/{sid}", headers=headers)
        if prog and prog.get("status") == "ready":
            break
        if prog and prog.get("status") == "failed":
            return []
        time.sleep(15)
    rows = http.get_json(f"https://api.brightdata.com/datasets/v3/snapshot/{sid}?format=json", headers=headers)
    out: list[Job] = []
    for r in rows or []:
        out.append(Job(source="linkedin_brightdata", title=r.get("job_title", ""), company=r.get("company_name", "") or "",
                       location=r.get("job_location", "") or "", url=r.get("url") or r.get("job_posting_url", ""),
                       posted=r.get("job_posted_date"), snippet=(r.get("job_summary") or "")[:600],
                       description=r.get("job_summary") or "", meta={"seniority": r.get("job_seniority_level")}))
    return out
