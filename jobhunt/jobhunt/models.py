from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field

COUNTRY_ALIASES = {
    "SA": ["saudi arabia", "saudi", "ksa", "riyadh", "jeddah", "dammam", "khobar", "al khobar", "jubail",
           "neom", "medina", "madinah", "al madina", "mecca", "makkah", "tabuk", "dhahran", "eastern province"],
    "QA": ["qatar", "doha", "lusail", "al rayyan", "al wakrah", "mesaieed", "ras laffan"],
}


def detect_country(text: str | None) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    for code, words in COUNTRY_ALIASES.items():
        for w in words:
            if re.search(r"\b" + re.escape(w) + r"\b", t):
                return code
    return None


def canonical_id(source: str, url: str, title: str = "", company: str = "") -> str:
    """Stable id for de-duplication. URLs are normalised (no query string / fragment, no trailing slash)."""
    base = re.sub(r"[?#].*$", "", url or "").rstrip("/").lower()
    if not base:
        base = f"{source}|{title}|{company}".lower()
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


class Job(BaseModel):
    id: str = ""
    source: str
    title: str
    company: str = ""
    location: str = ""
    country: Optional[str] = None  # ISO-2 (SA / QA) or None
    url: str
    posted: Optional[str] = None  # free text or ISO date
    snippet: str = ""
    description: str = ""  # full text when enriched
    meta: dict[str, Any] = Field(default_factory=dict)
    # filled by the pipeline
    score: int = 0
    score_reasons: list[str] = Field(default_factory=list)
    llm_fit: Optional[int] = None
    llm_notes: str = ""
    red_flags: list[str] = Field(default_factory=list)
    first_seen: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:  # noqa: D401
        if not self.id:
            self.id = canonical_id(self.source, self.url, self.title, self.company)
        if not self.country:
            self.country = detect_country(f"{self.location} {self.title} {self.url}")
        if not self.first_seen:
            self.first_seen = date.today().isoformat()

    @property
    def text(self) -> str:
        return " ".join([self.title, self.company, self.location, self.snippet, self.description])


class RecruiterLead(BaseModel):
    name: str
    kind: str  # agency | in-house | registry
    country: str = ""
    url: str = ""
    email: str = ""
    note: str = ""
    source: str = ""
    related_job_ids: list[str] = Field(default_factory=list)
