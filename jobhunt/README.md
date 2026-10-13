# jobhunt — autonomous job & recruiter discovery for KSA + Qatar, with a CV tailored per role

Runs every morning (GitHub Actions, 05:00 Riyadh), finds new postings for an applied economist /
research-strategy profile in **Saudi Arabia and Qatar**, scores them, writes a **tailored CV (DOCX + PDF)**, a
cover note and a LinkedIn note for the best ones, surfaces **recruiter leads**, and emails you a digest. Nothing is
ever submitted or sent to an employer or recruiter automatically: discovery and drafting are autonomous, the
*send* is yours (that is deliberate — see "LinkedIn and compliance").

```
jobhunt/
  config.yaml              targets, queries, scoring weights, sources, employers to watch, notification
  profile/cv.yaml          master CV (single source of truth, transcribed from the PDF in the repo root)
  data/recruiters.yaml     sourced agencies / search firms with KSA-Qatar practices
  jobhunt/                 package: sources/, scoring, enrich, tailor (Claude), render (DOCX/PDF), notify, pipeline
  tests/                   pytest, with REAL saved HTML from Bayt, Naukrigulf, GulfTalent as fixtures
  state/seen.json          hashed ids of postings already reported (safe to keep in a public repo)
  out/<date>/              digest.html, jobs.csv, jobs.json, <company>_<role>_Ibrahim_Alsalem_CV.{docx,pdf}, *_notes.md
.github/workflows/jobhunt.yml   daily schedule + manual trigger
```

## Quick start (local)

```bash
cd jobhunt
pip install -r requirements.txt
python -m pytest -q tests                 # parsers against saved HTML, scoring, tailoring guard-rails, rendering
python -m jobhunt sources                 # which sources are on and which keys are present
python -m jobhunt run --offline tests/fixtures --no-llm --no-email   # full dry run, no network
python -m jobhunt run --no-email          # live run, outputs under out/<date>/ (needs network)
python -m jobhunt tailor --url "https://www.bayt.com/en/qatar/jobs/qnb3666-vice-president-economics-74352550/"
python -m jobhunt tailor --title "Senior Economist" --company "QNB" --description-file posting.txt
python -m jobhunt render-master           # master CV as DOCX/PDF from profile/cv.yaml
```

## Secrets (GitHub → Settings → Secrets and variables → Actions)

| Secret | Needed for | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude re-ranking + tailoring (falls back to deterministic tailoring without it) | console.anthropic.com |
| `GMAIL_USER`, `GMAIL_APP_PASSWORD` | digest email (SMTP), reading your job-alert emails (IMAP), outreach drafts | Google app password, requires 2-Step Verification: https://support.google.com/accounts/answer/185833 |
| `CAREERJET_API_KEY` | Careerjet search API, locales `en_SA` and `en_QA` | publisher account: https://www.careerjet.com/partners/api |
| `JOOBLE_API_KEY_SA`, `JOOBLE_API_KEY_QA` | Jooble REST API (one key **per country domain**; free plan is 500 requests *lifetime* per key) | https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation |
| `JSEARCH_API_KEY` | Google-for-Jobs aggregator with a `country` parameter | https://www.openwebninja.com/api/jsearch |
| `SERPAPI_API_KEY` | Google Jobs engine, `gl=sa` / `gl=qa` are supported countries | https://serpapi.com/google-jobs-api , https://serpapi.com/google-jobs-countries |
| `BRIGHTDATA_API_KEY` | LinkedIn Jobs dataset (OFF by default, see below) | https://docs.brightdata.com/products/scrapers/linkedin/introduction |
| `HUNTER_API_KEY` | optional recruiter mailbox lookup per company domain | hunter.io |

The three HTML boards (Bayt, Naukrigulf, GulfTalent) and the employer career pages need no keys.

## Sources, and what was verified (Oct 2026)

| Source | KSA | Qatar | Access | Verified |
|---|---|---|---|---|
| Bayt.com | yes | yes | HTML listing `bayt.com/en/{country}/jobs/{keyword}-jobs/` | parsed live page (4 SA results for "economist"); robots.txt disallows `/en/jobs/*-jobs/` and filter URLs, not the country-scoped path used here; robots is re-checked at runtime |
| Naukrigulf | yes | yes | HTML `naukrigulf.com/{keyword}-jobs-in-{country}` | parsed live page (15 results); robots.txt allows |
| GulfTalent | yes | yes | HTML `gulftalent.com/{country}/jobs/title/{keyword}` | parsed live pages; `User-agent: * Allow: /`; when a country has 0 hits it shows "nearby" GCC jobs, which the scorer down-ranks |
| Careerjet API | `en_SA` | `en_QA` | official partner API | locale list in Careerjet's own client repo |
| Jooble API | `sa.jooble.org` | `qa.jooble.org` | official REST API | docs read; regional key rule and 500-request lifetime quota noted |
| JSearch (Google for Jobs) | `country=sa` | `country=qa` | API | vendor docs |
| SerpApi Google Jobs | `gl=sa` | `gl=qa` | API | both countries on SerpApi's supported list |
| Indeed | weak | none | n/a | Indeed's own search returned 1 irrelevant result for "economist, Riyadh" and 0 for Doha, so it is not wired in |
| LinkedIn | via **your alert emails** | same | IMAP on your Gmail | LinkedIn's job alerts arrive by email (https://www.linkedin.com/help/linkedin/answer/a511279) |
| Employer career pages | KAPSARC, PIF, Aramco | QNB (Bayt company page) | HTML watch | URLs checked; add more under `employers:` once you have verified a URL |
| Jadarat (jadarat.sa) | Saudi citizens only | — | manual | HRDF states jobs are exclusively for Saudi citizens — you qualify; register and set alerts there yourself |
| Kawader (kawader.gov.qa) | — | yes | manual | Qatar MoL's unified platform, described as aimed at "attracting national talent"; app is JS-only, so monitor manually |

## LinkedIn and compliance (read before enabling anything LinkedIn-related)

LinkedIn's User Agreement §8.2 prohibits scraping or copying the Services and "bots or other unauthorized
automated methods to access the Services, add or download contacts, send or redirect messages", and LinkedIn's
help centre says third-party tools that scrape or automate activity put the account at risk of restriction
(https://www.linkedin.com/help/linkedin/answer/a1341387). Therefore this system **never logs into LinkedIn,
never scrapes it, never sends messages or connection requests**. What it does instead:

1. Reads the **job-alert emails LinkedIn sends you** (set alerts for "economist", "economic analyst", "policy
   analyst", "research manager" in Riyadh and Doha; daily frequency).
2. Builds a **people-search URL** per shortlisted employer (`<company> talent acquisition`) that you click.
3. Drafts the ≤300-character connection note for you to paste.

`brightdata_linkedin` (LinkedIn Jobs dataset via Bright Data's API) is included but **disabled**. It does not touch
your account, but §8.2 also covers data "obtained through third parties such as data aggregators or brokers";
enabling it is your call.

Bayt / Naukrigulf / GulfTalent: one request per query per country per day (~18 requests per board), honest
User-Agent with contact address, 2-second per-host delay, robots.txt honoured. Still, prefer their own email alerts
as the primary feed (they are parsed too) and keep the query list short.

## Qatar eligibility note

The GCC Economic Agreement (2001), Chapter II Article 3, provides that GCC citizens "shall be accorded, in any
Member State, the same treatment accorded to its own citizens … in all economic activities, especially …
work in private and government jobs" (GCC Secretariat-General text:
https://www.gcc-sg.org/en/MediaCenter/DigitalLibrary/Documents/1274258747.pdf). Commercial relocation guides
consistently say GCC nationals do not need the sponsorship / work permit that non-GCC foreigners need in Qatar,
but I did not find a primary Qatar Ministry of Labour page stating the current procedure, so confirm it with the
employer. The scorer flags postings that say "Qatari nationals only" and skips tailoring for them.

## How ranking works

1. **Rule score (0-100)** — transparent weights in `config.yaml`: title keywords (economist 45, econometric 35,
   labour market 30, policy 25, research/strategy 20 …), target-country bonus, preferred-city bonus, skill overlap
   with the master CV, junior/other-country penalties, recency. Title hard-excludes (teacher, technician,
   coordinator …) remove noise like "Economics Teacher" or "ECONOMIC CONTRACTING CENTER" technician ads.
2. **Claude screen** (optional) — one batched call over the shortlist returns an interview-likelihood estimate,
   a one-line note and red flags (nationality restriction, PhD required, different profession).
3. **Tailoring** — for the top N (default 5, score ≥ 55) Claude rewrites summary/ordering/wording against the
   posting. **Anti-fabrication guard:** every tailored bullet must cite the id of the master-CV bullet it came
   from; bullets with unknown ids or with numbers that are not in the source are dropped, roles the model omitted
   are restored, skills not in the master CV are removed. With no API key (or `--no-llm`) a deterministic
   keyword-overlap tailoring runs instead, so the pipeline never blocks on the LLM. Model: `claude-opus-5-5`
   through `client.messages.parse` with a Pydantic schema (validated JSON output). The server-side refusal
   fallback parameter is not wired because the `parse` helper does not expose it; a refusal simply falls back to
   the deterministic engine.

## Recruiters

`data/recruiters.yaml` lists agencies/search firms whose own pages state KSA and/or Qatar coverage (Michael Page
Middle East, Robert Walters Saudi desk, Horton International, AP Executive Qatar, Keller, ACCUR) plus posters seen
on the boards (Ethra HR Consulting, Dar Masarat). The pipeline also flags **intermediaries detected in postings**
("Client of …", "… Recruitment", "… HR Consulting") and prints the LinkedIn people-search link per employer.
Outreach emails are created as **Gmail drafts** (IMAP append) with the tailored CV attached; you review and send.

## Visibility playbook (manual, one-time, 60-90 minutes)

- LinkedIn: set **Open to Work** (choose "recruiters only" or "all members"), titles "Economist, Economic Analyst,
  Policy Analyst, Research Manager, Strategy Analyst", locations Riyadh + Doha + Saudi Arabia + Qatar + Remote;
  create daily **job alerts** for the same titles so the email ingestion has a feed
  (https://www.linkedin.com/help/linkedin/answer/67405 , https://www.linkedin.com/help/linkedin/answer/a511279).
- Bayt, GulfTalent, Naukrigulf: complete the profile, upload the master CV PDF, switch on daily email alerts for
  the same titles in both countries (GulfTalent: https://www.gulftalent.com/register/jobalert).
- Jadarat: register (Saudi citizens) and set alerts. Kawader: register if the platform accepts GCC nationals.
- basaradvisory.com: `index.html` now carries schema.org `Person` JSON-LD (name, job title, LinkedIn, skills) so
  search engines can associate the site with your professional identity; link the site from your LinkedIn
  "Featured" section.
- Keep the master CV in `profile/cv.yaml` current; every tailored CV is generated from it.

## Suggested connectors / automations

- **Gmail** (already connected in Claude): the pipeline's digest, alert ingestion and drafts all go through Gmail.
- **Google Drive**: if you prefer the tailored CVs in Drive, add a step that uploads `out/<date>/` (the Artifacts
  tab of each workflow run keeps them for 30 days as-is).
- **Make.com or Zapier** (both connected): can replace the GitHub Actions cron if you want a visual scheduler, or
  push the digest into Notion/Sheets.
- **Notion**: a tracker database (status: new → applied → interview) is the natural next step; the Notion connector
  failed to connect in this session so it is not wired.

## Operating notes

- Each run: ~18 HTTP requests per HTML board, 1 request per API per query/country, up to 8 detail-page fetches,
  2 Claude calls (screen + tailoring per selected job). Typical GitHub Actions run: 3-6 minutes.
- Outputs are uploaded as a workflow artifact (30 days). Only `state/seen.json` (hashes + dates) is committed back.
- The repo is public: never put keys, recruiter emails or private notes in `config.yaml` or `data/`.
