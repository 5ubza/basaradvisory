from pathlib import Path

from jobhunt.sources import bayt, gulftalent, naukrigulf
from jobhunt.sources.career_pages import parse_html_page
from jobhunt.sources.email_alerts import extract_jobs_from_html
from jobhunt.enrich import extract_description
import re

FX = Path(__file__).parent / "fixtures"


def test_bayt_listing_parses_cards():
    jobs = bayt.parse_listing((FX / "bayt_sa_economist.html").read_text("utf-8"), "SA")
    assert len(jobs) == 4
    j = jobs[0]
    assert j.title == "Senior Development Manager"
    assert j.company == "Ethra For Human Resources Consulting"
    assert "Khobar" in j.location and j.country == "SA"
    assert j.url.startswith("https://www.bayt.com/en/saudi-arabia/jobs/") and j.posted
    assert all(x.id for x in jobs) and len({x.id for x in jobs}) == 4


def test_naukrigulf_listing_parses_tuples():
    jobs = naukrigulf.parse_listing((FX / "naukrigulf_sa_economist.html").read_text("utf-8"), "SA")
    assert len(jobs) == 15
    titles = [j.title for j in jobs]
    assert any("Economic" in t for t in titles)
    j = jobs[0]
    assert j.company and j.location and j.url.startswith("https://www.naukrigulf.com/")
    assert j.country == "SA" and j.posted


def test_gulftalent_nearby_results_keep_real_country():
    jobs = gulftalent.parse_listing((FX / "gulftalent_qa_economist.html").read_text("utf-8"), "QA")
    assert len(jobs) == 5
    j = next(x for x in jobs if "614668" in x.url)
    assert j.title == "Africa Economist" and j.company == "Pharo Management"
    assert j.location.startswith("Abu Dhabi") and j.country == "AE" and j.posted == "26 Jul"


def test_gulftalent_empty_page_yields_nothing_or_nearby_only():
    jobs = gulftalent.parse_listing((FX / "gulftalent_sa_economist.html").read_text("utf-8"), "SA")
    assert all(j.country != "SA" for j in jobs)


def test_email_alert_extraction_linkedin_and_bayt():
    html = """<html><body>
    <a href="https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=abc">Senior Economist</a>
    <p>Qatar National Bank</p><p>Doha, Qatar</p>
    <a href="https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=abc">View job</a>
    <a href="https://www.bayt.com/en/qatar/jobs/qnb3666-vice-president-economics-74352550/?utm=1">Vice President - Economics</a>
    <span>QNB</span><span>Doha</span>
    </body></html>"""
    jobs = extract_jobs_from_html(html, "linkedin", "New jobs for economist")
    assert len(jobs) == 2
    li = next(j for j in jobs if j.source == "email:linkedin")
    assert li.url == "https://www.linkedin.com/jobs/view/4123456789/"
    assert li.title == "Senior Economist" and li.company == "Qatar National Bank" and li.country == "QA"
    b = next(j for j in jobs if j.source == "email:bayt")
    assert b.url.endswith("74352550/") and "utm" not in b.url


def test_career_page_keyword_links():
    html = """<ul><li><a href="/jobs/123">Senior Economist - Energy Markets</a></li>
    <li><a href="/jobs/124">Facilities Technician</a></li><li><h3>Research Fellow - Policy</h3></li></ul>"""
    kw = re.compile(r"\b(economist|policy|research)\b", re.I)
    jobs = parse_html_page(html, "https://example.org/careers/", {"name": "Example", "country": "SA"}, kw)
    titles = {j.title for j in jobs}
    assert "Senior Economist - Energy Markets" in titles and "Research Fellow - Policy" in titles
    assert "Facilities Technician" not in titles
    assert all(j.source == "career_page" and j.company == "Example" for j in jobs)


def test_jobposting_jsonld_extraction():
    html = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
    "title":"Economist","description":"<p>Build <b>forecasting</b> models.</p><p>Requirements: MSc Economics.</p>",
    "hiringOrganization":{"@type":"Organization","name":"ACME"},"datePosted":"2026-10-01"}</script></head>
    <body><p>short</p></body></html>"""
    desc, meta = extract_description(html)
    assert "forecasting" in desc and meta["company"] == "ACME" and meta["datePosted"] == "2026-10-01"
