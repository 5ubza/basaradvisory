"""Orchestration: sources -> dedupe -> score -> enrich -> rerank -> tailor -> render -> digest -> state."""
from __future__ import annotations

import csv
import json
import logging
import time
from datetime import date
from pathlib import Path

import yaml

from . import health
from .config import env, load_config
from .enrich import enrich
from .http import PoliteSession
from .models import Job
from .notify import build_digest_html, create_gmail_draft, send_digest
from .recruiters import detect_agency_posters, linkedin_people_search, load_registry
from .render import render_docx, render_notes_md, render_pdf, slugify
from .scoring import score_all
from .sources import run_sources
from .state import SeenState
from .tailor import rerank_with_claude, tailor

log = logging.getLogger("jobhunt")


def dedupe(jobs: list[Job]) -> list[Job]:
    seen: dict[str, Job] = {}
    for j in jobs:
        key = j.id
        # cross-source dedupe on normalised title+company when URLs differ
        alt = (j.title.lower().strip(), j.company.lower().strip())
        if key in seen:
            continue
        if j.company and alt in {(x.title.lower().strip(), x.company.lower().strip()) for x in seen.values()}:
            continue
        seen[key] = j
    return list(seen.values())


def run(config_path: str | None = None, offline_dir: str | None = None, use_llm: bool = True,
        send_email: bool = True, only_sources: list[str] | None = None, max_tailor: int | None = None) -> dict:
    cfg = load_config(config_path)
    health.reset()
    pc = cfg["pipeline"]
    out_dir = Path(cfg["paths"]["out"]) / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    cv = yaml.safe_load(open(cfg["paths"]["cv"], encoding="utf-8"))
    fetch_cfg = cfg.get("fetch", {})
    http = PoliteSession(offline_dir=Path(offline_dir) if offline_dir else None,
                         deadline_seconds=int(pc.get("network_budget_seconds", 900)),
                         proxied_hosts=fetch_cfg.get("proxied_hosts", []), backend=fetch_cfg.get("backend", "auto"))
    t0 = time.time()
    state = SeenState(cfg["paths"]["state"], keep_days=pc.get("keep_state_days", 120))

    raw, counts = run_sources(cfg, http, only=only_sources)
    log.info("sources done in %.0fs", time.time() - t0)
    jobs = dedupe(raw)
    new_jobs = [j for j in jobs if state.is_new(j.id)]
    log.info("%d raw -> %d unique -> %d new", len(raw), len(jobs), len(new_jobs))

    scored = score_all(new_jobs, cfg)
    shortlist = [j for j in scored if j.score >= pc["min_score_to_report"]][: pc["max_jobs_in_digest"]]

    for j in shortlist[: pc["enrich_top_n"]]:
        enrich(j, http)

    if use_llm:
        rr = rerank_with_claude(cv, shortlist[: cfg["llm"].get("rerank_top_n", 25)], cfg)
        for j in shortlist:
            if j.id in rr:
                j.llm_fit, j.llm_notes = rr[j.id].fit, rr[j.id].note
                j.red_flags.extend(f for f in rr[j.id].red_flags if f not in j.red_flags)
        shortlist.sort(key=lambda j: (j.llm_fit if j.llm_fit is not None else j.score, j.score), reverse=True)

    log.info("scoring/enrich/rerank done in %.0fs", time.time() - t0)
    # ---- tailoring ------------------------------------------------------------------------------
    limit = pc["tailor_top_n"] if max_tailor is None else max_tailor
    candidates = [j for j in shortlist if j.score >= pc["min_score_to_tailor"]
                  and not any("restricted to Qatari" in f for f in j.red_flags)][:limit]
    tailored = []
    attachments: list[Path] = []
    for j in candidates:
        t, engine = tailor(cv, j, cfg, use_llm=use_llm)
        base = f"{slugify(j.company or j.source, 24)}_{slugify(j.title, 32)}_Ibrahim_Alsalem_CV"
        files = [render_docx(cv, t, out_dir / f"{base}.docx"), render_pdf(cv, t, out_dir / f"{base}.pdf"),
                 render_notes_md(j, t, engine, out_dir / f"{base}_notes.md")]
        attachments += files[:2]
        tailored.append({"job": j, "cv": t, "engine": engine, "files": [f.name for f in files],
                         "people_url": linkedin_people_search(j.company) if j.company else linkedin_people_search(j.title)})
        if cfg["notify"].get("create_outreach_drafts") and send_email:
            create_gmail_draft(to="", subject=t.email_subject, body=t.cover_note, attachments=files[:2])

    # ---- recruiters -----------------------------------------------------------------------------
    registry, markers = load_registry(cfg["paths"]["recruiters"])
    detected = detect_agency_posters(shortlist, markers)
    recruiters = detected + ([r for r in registry] if not state.data else [])  # registry shown in full on first run only

    # ---- outputs --------------------------------------------------------------------------------
    (out_dir / "jobs.json").write_text(json.dumps([j.model_dump() for j in shortlist], indent=1, ensure_ascii=False), "utf-8")
    with open(out_dir / "jobs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["score", "llm_fit", "title", "company", "location", "country", "source", "posted", "url", "red_flags"])
        for j in shortlist:
            w.writerow([j.score, j.llm_fit, j.title, j.company, j.location, j.country, j.source, j.posted, j.url, "; ".join(j.red_flags)])
    if not env("FIRECRAWL_API_KEY") and not (env("BRIGHTDATA_API_KEY") and env("BRIGHTDATA_UNLOCKER_ZONE")):
        health.warn("No fetch backend configured: Bayt, GulfTalent and Naukrigulf cannot be read from GitHub's servers. "
                    "Add FIRECRAWL_API_KEY, or create email job alerts on those boards so the Gmail feed picks them up.")
    warnings = health.warnings()
    html = build_digest_html(date=date.today().isoformat(), new_count=len(new_jobs), total_seen=len(jobs),
                             counts=", ".join(f"{k}={v}" for k, v in counts.items()) or "none", jobs=shortlist,
                             tailored=tailored, recruiters=recruiters, warnings=warnings)
    (out_dir / "digest.html").write_text(html, "utf-8")
    sent = False
    if send_email and (shortlist or tailored or warnings):
        subject = f"{cfg['notify'].get('subject_prefix', '[JobHunt]')} {len(shortlist)} new matches, {len(tailored)} tailored CVs - {date.today().isoformat()}"
        sent = send_digest(subject, html, attachments, cfg["notify"]["email_to"])

    for j in jobs:
        state.mark(j.id)
    state.save()
    summary = {"raw": len(raw), "unique": len(jobs), "new": len(new_jobs), "shortlist": len(shortlist),
               "tailored": len(tailored), "digest_sent": sent, "out_dir": str(out_dir), "sources": counts,
               "warnings": warnings}
    log.info("summary %s", summary)
    return summary


def tailor_one(url: str, title: str = "", company: str = "", config_path: str | None = None, use_llm: bool = True,
               description_file: str | None = None) -> dict:
    """Ad-hoc: tailor for a single posting URL (or pasted description)."""
    cfg = load_config(config_path)
    cv = yaml.safe_load(open(cfg["paths"]["cv"], encoding="utf-8"))
    fetch_cfg = cfg.get("fetch", {})
    http = PoliteSession(proxied_hosts=fetch_cfg.get("proxied_hosts", []), backend=fetch_cfg.get("backend", "auto"))
    job = Job(source="manual", title=title or "Target role", company=company, url=url,
              description=Path(description_file).read_text("utf-8") if description_file else "")
    if not job.description:
        enrich(job, http)
    if not title and job.description:
        job.title = job.description.splitlines()[0][:90]
    score_all([job], cfg)
    t, engine = tailor(cv, job, cfg, use_llm=use_llm)
    out_dir = Path(cfg["paths"]["out"]) / "manual"
    base = f"{slugify(job.company or 'target', 24)}_{slugify(job.title, 32)}_Ibrahim_Alsalem_CV"
    files = [render_docx(cv, t, out_dir / f"{base}.docx"), render_pdf(cv, t, out_dir / f"{base}.pdf"),
             render_notes_md(job, t, engine, out_dir / f"{base}_notes.md")]
    return {"engine": engine, "fit": t.fit_score, "files": [str(f) for f in files]}
