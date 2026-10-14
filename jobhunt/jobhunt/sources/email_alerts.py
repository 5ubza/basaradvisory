"""Ingest the job-alert emails you already receive (LinkedIn, Bayt, GulfTalent, Naukrigulf, Indeed, Glassdoor).

This is the LinkedIn-compliant channel: LinkedIn itself sends job alerts by email
(https://www.linkedin.com/help/linkedin/answer/a511279) and reading your own mailbox needs no automation on
LinkedIn's site. Access is Gmail IMAP with an app password (https://support.google.com/accounts/answer/185833),
read-only (we never move or mark messages).
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import date, timedelta
from email.header import decode_header, make_header
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ..config import env
from ..models import Job

log = logging.getLogger(__name__)

LINK_PATTERNS = {
    "linkedin": re.compile(r"https?://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/(?:[a-z0-9-]*?-)?(\d{6,})", re.I),
    "bayt": re.compile(r"https?://(?:www\.)?bayt\.com/en/[a-z-]+/jobs/[a-z0-9%-]+-(\d{5,})/?", re.I),
    "gulftalent": re.compile(r"https?://(?:www\.)?gulftalent\.com/[a-z-]+/jobs/[a-z0-9-]+-(\d{4,})", re.I),
    "naukrigulf": re.compile(r"https?://(?:www\.)?naukrigulf\.com/[a-z0-9-]+-jid-(\d+)", re.I),
    "indeed": re.compile(r"https?://[a-z.]*indeed\.com/(?:viewjob|rc/clk|pagead/clk)\?[^\s\"']*jk=([a-f0-9]{8,})", re.I),
    "glassdoor": re.compile(r"https?://(?:www\.)?glassdoor\.[a-z.]+/job-listing/[^\s\"']*?jl=(\d+)", re.I),
}
CANONICAL = {
    "linkedin": "https://www.linkedin.com/jobs/view/{id}/",
    "indeed": "https://www.indeed.com/viewjob?jk={id}",
}


def available(cfg):
    ok = bool(env("GMAIL_USER") and env("GMAIL_APP_PASSWORD"))
    return ok, "mailbox configured" if ok else "GMAIL_USER / GMAIL_APP_PASSWORD"


def _unwrap(href: str) -> str:
    """LinkedIn/Indeed wrap links in trackers; pull the real URL out of a `url=` style parameter if present."""
    try:
        qs = parse_qs(urlparse(href).query)
    except ValueError:
        return href
    for k in ("url", "u", "redirect", "target"):
        if k in qs and qs[k][0].startswith("http"):
            return qs[k][0]
    return href


def extract_jobs_from_html(html: str, sender_kind: str, subject: str = "") -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    jobs: dict[str, Job] = {}
    for a in soup.find_all("a", href=True):
        href = _unwrap(a["href"])
        for kind, pat in LINK_PATTERNS.items():
            m = pat.search(href)
            if not m:
                continue
            jid = m.group(1)
            url = CANONICAL.get(kind, "{raw}").format(id=jid, raw=re.sub(r"[?#].*$", "", href))
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 3 or title.lower() in ("view job", "apply", "see job", "view", "apply now"):
                continue
            key = f"{kind}:{jid}"
            if key in jobs:
                continue
            # best-effort context: next ~3 short text lines after the link are usually company / location
            ctx = []
            for s in a.find_all_next(string=True, limit=12):
                t = s.strip()
                if t and t != title and len(t) < 80:
                    ctx.append(t)
                if len(ctx) >= 3:
                    break
            company = ctx[0] if ctx else ""
            location = ctx[1] if len(ctx) > 1 else ""
            jobs[key] = Job(source=f"email:{kind}", title=title, company=company, location=location, url=url,
                            snippet=f"From alert email: {subject}"[:200], meta={"alert_sender": sender_kind})
    return list(jobs.values())


def fetch(cfg, http) -> list[Job]:
    opts = cfg["sources"]["email_alerts"]
    since = (date.today() - timedelta(days=int(opts.get("days_back", 2)))).strftime("%d-%b-%Y")
    out: list[Job] = []
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=60)
        M.login(env("GMAIL_USER"), env("GMAIL_APP_PASSWORD"))
        M.select("INBOX", readonly=True)
        for kind, senders in opts.get("senders", {}).items():
            for snd in senders:
                typ, data = M.search(None, f'(SINCE {since} FROM "{snd}")')
                if typ != "OK":
                    continue
                for num in data[0].split()[-40:]:
                    typ, msg_data = M.fetch(num, "(BODY.PEEK[])")
                    if typ != "OK":
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    subject = str(make_header(decode_header(msg.get("Subject", ""))))
                    html = ""
                    for part in msg.walk():
                        if part.get_content_type() == "text/html":
                            html += part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                    if html:
                        out.extend(extract_jobs_from_html(html, kind, subject))
        M.logout()
    except (imaplib.IMAP4.error, OSError) as e:
        log.warning("IMAP failed: %s", e)
    return out
