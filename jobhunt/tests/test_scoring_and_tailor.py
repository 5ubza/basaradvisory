from pathlib import Path

import yaml

from jobhunt.config import load_config
from jobhunt.models import Job, detect_country
from jobhunt.scoring import score_job
from jobhunt.tailor import TailoredBullet, TailoredCV, TailoredRole, tailor_deterministic, validate_against_master
from jobhunt.render import render_docx, render_pdf, render_notes_md
from jobhunt.state import SeenState

CFG = load_config()
CV = yaml.safe_load(open(CFG["paths"]["cv"], encoding="utf-8"))


def test_detect_country():
    assert detect_country("Riyadh, Saudi Arabia") == "SA"
    assert detect_country("Doha - Qatar") == "QA"
    assert detect_country("Dubai, UAE") is None


def test_scoring_prefers_economist_in_target_country():
    good = score_job(Job(source="bayt", title="Senior Economist", company="X", location="Riyadh, Saudi Arabia", url="https://a/1",
                         snippet="econometric forecasting stata python vision 2030"), CFG)
    teacher = score_job(Job(source="bayt", title="Economics Teacher", company="School", location="Riyadh", url="https://a/2"), CFG)
    abroad = score_job(Job(source="gulftalent", title="Senior Economist", company="Y", location="Dubai, UAE", country="AE", url="https://a/3"), CFG)
    assert good.score >= 70 and teacher.score == 0 and abroad.score < good.score - 30


def test_red_flag_detection():
    j = score_job(Job(source="x", title="Economist", url="https://a/4", location="Doha, Qatar",
                      snippet="Open to Qatari nationals only. PhD required."), CFG)
    assert any("Qatari" in f for f in j.red_flags) and any("PhD" in f for f in j.red_flags)


def test_deterministic_tailoring_only_uses_master_bullets_and_renders(tmp_path: Path):
    job = Job(source="bayt", title="Labour Market Economist", company="Ministry of Labour", location="Doha, Qatar",
              url="https://example/5", description="Forecast unemployment, analyse labour market policy, Stata, R, Python.")
    t = tailor_deterministic(CV, job)
    master = {b for r in CV["experience"] for b in r["bullets"]}
    assert all(b.text in master for r in t.roles for b in r.bullets)
    assert t.roles[1].bullets[0].source_id.startswith("mep.")  # labour-market bullets float to the top
    assert "relocate to Doha" in t.cover_note and len(t.linkedin_note) <= 300
    docx = render_docx(CV, t, tmp_path / "cv.docx")
    pdf = render_pdf(CV, t, tmp_path / "cv.pdf")
    md = render_notes_md(job, t, "deterministic", tmp_path / "notes.md")
    assert docx.stat().st_size > 10_000 and pdf.read_bytes()[:4] == b"%PDF" and "Cover note" in md.read_text()


def test_validation_drops_fabricated_bullets():
    t = TailoredCV(headline="h", summary="s", competency_order=["Domain", "Bogus"], highlighted_skills=["R", "Quantum computing"],
                   roles=[TailoredRole(role_id="mep", bullets=[
                       TailoredBullet(source_id="mep.1", text="Led national labour-market research methodology."),
                       TailoredBullet(source_id="mep.9", text="Invented bullet"),
                       TailoredBullet(source_id="mep.2", text="Managed 50+ government bodies and a $3bn budget."),
                   ])], cover_note="c", linkedin_note="l" * 400, email_subject="e", keywords_matched=[],
                   keywords_missing=[], fit_score=50, fit_rationale="r")
    v = validate_against_master(t, CV)
    mep = next(r for r in v.roles if r.role_id == "mep")
    assert [b.source_id for b in mep.bullets] == ["mep.1"]           # fabricated id and new numbers dropped
    assert len(v.roles) == len(CV["experience"])                      # omitted roles restored
    assert "Bogus" not in v.competency_order and "Quantum computing" not in v.highlighted_skills
    assert len(v.linkedin_note) == 300


def test_state_roundtrip(tmp_path: Path):
    s = SeenState(tmp_path / "seen.json")
    assert s.is_new("abc")
    s.mark("abc")
    s.save()
    assert not SeenState(tmp_path / "seen.json").is_new("abc")
