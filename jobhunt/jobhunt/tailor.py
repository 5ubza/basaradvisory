"""Per-role CV tailoring.

Two engines:
  * Claude (default when ANTHROPIC_API_KEY is set): `client.messages.parse` with a Pydantic schema, so the
    output is validated JSON. Every tailored bullet must cite the id of the master-CV bullet it was derived from;
    anything that cannot be traced back is dropped, so the model can rephrase and reorder but not invent.
  * Deterministic fallback: keyword-overlap ordering of the master CV, templated notes. Used when no key is
    present, when the API call fails, or with --no-llm. The pipeline never stalls on the LLM.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from .config import env
from .models import Job

log = logging.getLogger(__name__)

STOP = set("the and for with of to in on at a an or by as is are be this that from into across within".split())


# --------------------------------------------------------------------------------------- schema
class TailoredBullet(BaseModel):
    source_id: str = Field(description="id of the master-CV bullet this is derived from, e.g. 'mep.1'")
    text: str


class TailoredRole(BaseModel):
    role_id: str
    bullets: list[TailoredBullet]


class TailoredCV(BaseModel):
    headline: str
    summary: str
    competency_order: list[str] = Field(description="competency group names, most relevant first")
    highlighted_skills: list[str] = Field(description="8-14 skills/keywords from the master CV that match the posting")
    roles: list[TailoredRole] = Field(description="all roles, most relevant bullets first; may drop weak bullets")
    cover_note: str = Field(description="120-180 word email/cover note, first person, specific to the posting")
    linkedin_note: str = Field(description="<= 300 characters connection note to a recruiter/hiring manager")
    email_subject: str
    keywords_matched: list[str]
    keywords_missing: list[str] = Field(description="requirements in the posting the candidate does not evidence")
    fit_score: int = Field(ge=0, le=100)
    fit_rationale: str


class RerankItem(BaseModel):
    job_id: str
    fit: int = Field(ge=0, le=100)
    note: str
    red_flags: list[str] = []


class RerankResult(BaseModel):
    items: list[RerankItem]


# --------------------------------------------------------------------------------------- helpers
def index_bullets(cv: dict) -> dict[str, str]:
    idx = {}
    for role in cv["experience"]:
        for i, b in enumerate(role["bullets"], 1):
            idx[f"{role['id']}.{i}"] = b
    return idx


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9+#-]{2,}", text.lower()) if w not in STOP}


def overlap(a: str, b_tokens: set[str]) -> int:
    return len(tokens(a) & b_tokens)


def master_text(cv: dict) -> str:
    return json.dumps({k: cv[k] for k in ("name", "headline", "summary", "competencies", "experience", "education",
                                          "credentials", "languages", "mobility", "nationality")}, indent=1)


# --------------------------------------------------------------------------------------- deterministic engine
def tailor_deterministic(cv: dict, job: Job) -> TailoredCV:
    jd = tokens(job.text)
    roles = []
    for role in cv["experience"]:
        scored = sorted(((-overlap(b, jd), i, b) for i, b in enumerate(role["bullets"], 1)))  # ties keep master order
        roles.append(TailoredRole(role_id=role["id"],
                                  bullets=[TailoredBullet(source_id=f"{role['id']}.{i}", text=b) for _, i, b in scored]))
    comps = sorted(cv["competencies"], key=lambda g: -sum(overlap(it, jd) for it in g["items"]))
    skills = sorted({it for g in cv["competencies"] for it in g["items"]}, key=lambda s: -overlap(s, jd))[:12]
    matched = sorted(jd & tokens(master_text(cv)))[:25]
    country_line = ("I am a Saudi national based in Riyadh and available to relocate to Doha."
                    if job.country == "QA" else "I am based in Riyadh.")
    cover = (f"Dear Hiring Team,\n\nI am writing to apply for the {job.title} role"
             f"{(' at ' + job.company) if job.company else ''}. I am a Chartered Economist with 10+ years of applied "
             f"research across Saudi public institutions and the private sector, including labour-market policy at the "
             f"Ministry of Economy and Planning, tourism demand analytics at the Saudi Tourism Authority, and consulting at "
             f"Strategic Gears. I build econometric and forecasting models in R, Stata and Python and translate them into "
             f"decision-ready briefs for senior leadership. {country_line} My CV is attached; I would welcome a conversation "
             f"about how this experience maps to your needs.\n\nKind regards,\nIbrahim H. Alsalem, ChE")
    li = (f"Hello - I saw the {job.title} opening{(' at ' + job.company) if job.company else ''}. Chartered Economist, "
          f"10+ yrs KSA public-sector research (MEP labour market, STA tourism analytics), R/Stata/Python. "
          f"Happy to share a tailored CV.")[:300]
    return TailoredCV(headline=cv["headline"], summary=cv["summary"], competency_order=[g["group"] for g in comps],
                      highlighted_skills=skills, roles=roles, cover_note=cover, linkedin_note=li,
                      email_subject=f"Application - {job.title}{(' - ' + job.company) if job.company else ''} - Ibrahim Alsalem",
                      keywords_matched=matched, keywords_missing=[], fit_score=job.score,
                      fit_rationale="Deterministic keyword-overlap tailoring (no LLM).")


# --------------------------------------------------------------------------------------- Claude engine
SYSTEM = """You tailor a candidate's CV to one job posting. You are given the MASTER CV as JSON (ground truth) and the
POSTING. Rules, in priority order:
1. Never invent. Every bullet you output must be a rephrasing, tightening or re-emphasis of ONE master bullet and must
   carry that bullet's id in source_id. Do not add employers, titles, dates, degrees, certifications, tools, clients,
   metrics or numbers that are not in the master CV. If the posting asks for something the candidate lacks, list it in
   keywords_missing instead of implying it.
2. Mirror the posting's own vocabulary where it is truthful (e.g. 'labour market' vs 'labor market', 'policy analysis',
   'forecasting'), so ATS keyword matching works. Keep spelling consistent with the posting (UK vs US).
3. Order: most relevant bullets first inside each role; you may drop weak bullets but keep at least one per role and
   keep role order chronological (the renderer keeps the master order of roles).
4. Summary: 60-110 words, third-person-free (no 'I'), opening with the strongest match to this posting.
5. GCC context: the candidate is a Saudi national in Riyadh. For Qatar postings mention relocation readiness in the
   cover note, not in the summary. Never mention salary. Never mention nationality in the summary unless the posting
   restricts eligibility (then state it plainly in the cover note).
6. cover_note 120-180 words, specific to the employer; linkedin_note <= 300 characters, no hashtags.
7. fit_score is your honest estimate (0-100) of interview likelihood given the gaps; fit_rationale is 1-2 sentences."""


def _claude_client():
    import anthropic  # imported lazily so the package works without the SDK installed
    return anthropic.Anthropic(timeout=180.0, max_retries=1)


def tailor_with_claude(cv: dict, job: Job, model: str) -> Optional[TailoredCV]:
    client = _claude_client()
    posting = {"title": job.title, "company": job.company, "location": job.location, "country": job.country,
               "url": job.url, "description": (job.description or job.snippet)[:12000]}
    user = f"MASTER CV (JSON):\n{master_text(cv)}\n\nPOSTING (JSON):\n{json.dumps(posting, indent=1)}"
    try:
        resp = client.messages.parse(model=model, max_tokens=16000, system=SYSTEM,
                                     messages=[{"role": "user", "content": user}], output_format=TailoredCV)
    except Exception as e:  # noqa: BLE001 - any API failure falls back to the deterministic engine
        log.warning("Claude tailoring failed for %s: %s", job.title, e)
        return None
    if getattr(resp, "stop_reason", None) == "refusal" or resp.parsed_output is None:
        log.warning("Claude returned no parsed output (stop_reason=%s)", getattr(resp, "stop_reason", None))
        return None
    return resp.parsed_output


def validate_against_master(t: TailoredCV, cv: dict) -> TailoredCV:
    """Drop any bullet that does not trace back to the master CV; restore roles the model omitted."""
    idx = index_bullets(cv)
    by_role: dict[str, TailoredRole] = {r.role_id: r for r in t.roles}
    roles_out = []
    for role in cv["experience"]:
        r = by_role.get(role["id"])
        bullets: list[TailoredBullet] = []
        if r:
            for b in r.bullets:
                if b.source_id in idx and b.source_id.startswith(role["id"] + "."):
                    # rewritten text must not introduce new numbers
                    src_nums = set(re.findall(r"\d+(?:[.,]\d+)?", idx[b.source_id]))
                    new_nums = set(re.findall(r"\d+(?:[.,]\d+)?", b.text))
                    if new_nums - src_nums:
                        log.info("dropping bullet with new numbers: %s", b.text[:80])
                        continue
                    bullets.append(b)
        if not bullets:
            bullets = [TailoredBullet(source_id=f"{role['id']}.1", text=role["bullets"][0])]
        roles_out.append(TailoredRole(role_id=role["id"], bullets=bullets))
    t.roles = roles_out
    groups = [g["group"] for g in cv["competencies"]]
    t.competency_order = [g for g in t.competency_order if g in groups] + [g for g in groups if g not in t.competency_order]
    master_skills = {it.lower() for g in cv["competencies"] for it in g["items"]}
    t.highlighted_skills = [s for s in t.highlighted_skills if s.lower() in master_skills or s.lower() in master_text(cv).lower()][:14]
    t.linkedin_note = t.linkedin_note[:300]
    return t


def tailor(cv: dict, job: Job, cfg: dict, use_llm: bool = True) -> tuple[TailoredCV, str]:
    """Returns (tailored_cv, engine_name)."""
    llm_cfg = cfg.get("llm", {})
    if use_llm and llm_cfg.get("enabled", True) and env("ANTHROPIC_API_KEY"):
        t = tailor_with_claude(cv, job, llm_cfg.get("model", "claude-opus-5-5"))
        if t is not None:
            return validate_against_master(t, cv), "claude"
    return tailor_deterministic(cv, job), "deterministic"


# --------------------------------------------------------------------------------------- shortlist re-rank
RERANK_SYSTEM = """You are screening job postings for one candidate. For each posting give fit (0-100 = probability the
candidate would be shortlisted for interview), a one-sentence note, and red_flags (eligibility restrictions such as
'Qatari nationals only', hard requirements the candidate lacks such as a PhD or 15+ years, or a clearly different
profession despite a matching keyword, e.g. 'economics teacher'). Be strict: a keyword match is not a fit."""


def rerank_with_claude(cv: dict, jobs: list[Job], cfg: dict) -> dict[str, RerankItem]:
    if not (cfg.get("llm", {}).get("enabled", True) and cfg.get("llm", {}).get("rerank", True) and env("ANTHROPIC_API_KEY")):
        return {}
    if not jobs:
        return {}
    client = _claude_client()
    items = [{"job_id": j.id, "title": j.title, "company": j.company, "location": j.location,
              "text": (j.description or j.snippet)[:1500]} for j in jobs]
    user = f"CANDIDATE PROFILE (JSON):\n{master_text(cv)}\n\nPOSTINGS (JSON list):\n{json.dumps(items, indent=0)}"
    try:
        resp = client.messages.parse(model=cfg["llm"].get("model", "claude-opus-5-5"), max_tokens=16000,
                                     system=RERANK_SYSTEM, messages=[{"role": "user", "content": user}],
                                     output_format=RerankResult)
    except Exception as e:  # noqa: BLE001
        log.warning("Claude rerank failed: %s", e)
        return {}
    if resp.parsed_output is None:
        return {}
    return {it.job_id: it for it in resp.parsed_output.items}
