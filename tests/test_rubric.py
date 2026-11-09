import sys

import pytest

from jobveyra import config, queue
from jobveyra.evaluate import lang, rubric
from jobveyra.models import Evaluation, Posting

POSTING = """About us
Example Labs builds forecasting tools for grocery retailers. Our mission is to cut food waste.

What you'll do
- Build demand forecasting models in Python
- Present results to product teams

Requirements:
- 3+ years of experience in data science or analytics
- Strong Python and SQL
- Experience with Kubernetes or Docker
- Master's degree in Statistics or a related field

Nice to have
- Spark
- Portuguese is a plus

Salary: €50,000 - €65,000 per year
"""


def make_cfg(tmp_path, **over):
    raw = {
        "candidate": {"name": "Alex Rivera", "email": "alex.rivera@example.com",
                      "languages": {"en": "C2", "pt": "native", "es": "B2"},
                      "work_authorization": ["EU"], "master_cv": "cv/master.md"},
        "focus": {
            "regions": [{"name": "Lisbon", "match": ["lisbon", "lisboa", "portugal"], "weight": 1.0},
                        {"name": "Madrid", "match": ["madrid"], "weight": 0.8}],
            "tracks": [{"key": "ds", "label": "Data science", "titles": ["data scientist", "machine learning"],
                        "skills": ["python", "sql", "statistics", "forecasting"]}],
            "seniority_min": "junior", "seniority_max": "senior", "employment": ["full_time"],
            "salary_floor": 40000, "salary_currency": "EUR", "languages_ok": ["en", "pt", "es"],
            "flagship_employers": ["Example Labs"], "avoid_employers": ["Initech"]},
    }
    for k, v in over.items():
        sec, key = k.split("__")
        raw[sec][key] = v
    (tmp_path / "cv").mkdir(exist_ok=True)
    (tmp_path / "cv" / "master.md").write_text(
        "Alex Rivera\nM.Sc. Statistics, University of Example (2021)\nSkills: Python, SQL, pandas, Docker\n",
        encoding="utf-8")
    return config.from_dict(raw, tmp_path)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setenv("JOBQUEUE_NOW", "2026-11-09T12:00:00")


@pytest.fixture
def no_legitimacy(monkeypatch):
    monkeypatch.setitem(sys.modules, "jobveyra.evaluate.legitimacy", None)


def posting(**kw):
    base = dict(source="greenhouse", employer="Example Labs", title="Data Scientist",
                url="https://boards.example/1", location="Lisbon, Portugal", posted="2026-11-05", text=POSTING)
    base.update(kw)
    return Posting(**base)


# ---------------------------------------------------------------- requirements

def test_extract_requirements_sections_and_cues():
    reqs = rubric.extract_requirements(POSTING)
    kinds = {r.text: r.kind for r in reqs}
    assert kinds["Strong Python and SQL"] == "required"
    assert kinds["Spark"] == "preferred"
    assert kinds["Portuguese is a plus"] == "preferred"
    yrs = [r for r in reqs if r.years]
    assert yrs and yrs[0].years == 3
    deg = [r for r in reqs if r.degree]
    assert deg and deg[0].degree == 2
    k8s = next(r for r in reqs if "Kubernetes" in r.text)
    assert k8s.any_of and set(k8s.terms) == {rubric.norm_term("kubernetes"), "docker"}
    # responsibilities are not requirements
    assert not any("Present results" in r.text for r in reqs)


def test_extract_inline_cues_without_headings():
    text = "We need someone great. Python is required. Experience with Tableau is a plus. We have snacks."
    reqs = rubric.extract_requirements(text)
    assert [(r.kind, r.terms) for r in reqs] == [("required", ["python"]), ("preferred", ["tableau"])]


def test_extract_falls_back_to_mentions():
    reqs = rubric.extract_requirements("You will work with Python and Airflow every day")
    assert {r.source for r in reqs} == {"mention"}
    assert {t for r in reqs for t in r.terms} == {"python", "airflow"}


def test_inline_heading_with_content():
    reqs = rubric.extract_requirements("Must have: Python, SQL and dbt\nBonus: Looker")
    assert reqs[0].kind == "required" and set(reqs[0].terms) == {"python", "sql", "dbt"}
    assert reqs[1].kind == "preferred" and reqs[1].terms == ["looker"]


def test_synonyms_and_accent_folding():
    assert rubric.has_term(rubric.norm("Strong ML and k8s skills"), "machine learning")
    assert rubric.has_term(rubric.norm("Strong ML and k8s skills"), "kubernetes")
    assert rubric.has_term(rubric.norm("Estadística aplicada"), "statistics")
    assert rubric.has_term(rubric.norm("Node.js and JS"), "javascript")
    # single-letter R only as a standalone capitalised word
    assert rubric.find_terms("Fluent in R and Python", ["r"]) == ["r"]
    assert rubric.find_terms("R&D budget review", ["r"]) == []


# ---------------------------------------------------------------- evaluate

def test_evaluate_strong_match(tmp_path, no_legitimacy):
    cfg = make_cfg(tmp_path)
    ev = rubric.evaluate(posting(), cfg, job_id="example-labs:1")
    assert isinstance(ev, Evaluation)
    assert [d.key for d in ev.dimensions] == ["skills", "track", "seniority", "location", "language",
                                              "compensation", "freshness", "employer"]
    assert abs(sum(d.weight for d in ev.dimensions) - 1) < 1e-6
    assert ev.track == "ds" and not ev.blockers
    assert ev.fit >= 70 and ev.lane == "full"          # flagship at >= 70
    assert ev.stars == round(1 + 4 * ev.fit / 100, 1)
    skills = next(d for d in ev.dimensions if d.key == "skills")
    notes = " ".join(e.note for e in skills.evidence)
    assert "python (track skills)" in notes and "docker (CV)" in notes
    assert "not evidenced" in notes and "spark" in notes
    for d in ev.dimensions:
        assert d.evidence and all(e.basis in ("text", "structure", "estimate") for e in d.evidence)
    assert ev.summary.endswith(".") and "Data science" in ev.summary


def test_estimate_only_dimension_is_capped(tmp_path, no_legitimacy):
    cfg = make_cfg(tmp_path, focus__flagship_employers=[])
    p = posting(employer="Globex", posted="", text="We are hiring. Join us.")
    ev = rubric.evaluate(p, cfg, job_id="globex:1")
    by = {d.key: d for d in ev.dimensions}
    for key in ("compensation", "freshness", "employer"):
        assert all(e.basis == "estimate" for e in by[key].evidence)
        assert by[key].score <= rubric.ESTIMATE_CAP


def test_cap_applies_even_to_high_estimates():
    from jobveyra.models import Dimension, Evidence
    d = rubric._cap(Dimension("x", 0.95, 0.1, [Evidence("guess", "estimate")]))
    assert d.score == rubric.ESTIMATE_CAP
    d = rubric._cap(Dimension("x", 0.95, 0.1, [Evidence("guess", "estimate"), Evidence("quote", "text")]))
    assert d.score == 0.95


def test_no_sponsorship_blocker(tmp_path, no_legitimacy):
    text = POSTING + "\nWe are unable to sponsor visas. Applicants must be authorized to work in Canada."
    cfg = make_cfg(tmp_path)
    ev = rubric.evaluate(posting(location="Toronto, ON", text=text), cfg, job_id="x")
    assert "no_sponsorship" in ev.blockers and ev.lane == "excluded"
    assert "sponsorship" in ev.summary
    # authorised there: no blocker
    cfg2 = make_cfg(tmp_path)
    cfg2.candidate.work_authorization = ["EU", "CA"]
    ev2 = rubric.evaluate(posting(location="Toronto, ON", text=text), cfg2, job_id="x")
    assert "no_sponsorship" not in ev2.blockers
    # EU bloc covers Portugal
    ev3 = rubric.evaluate(posting(text=POSTING + "\nNo visa sponsorship."), cfg, job_id="x")
    assert "no_sponsorship" not in ev3.blockers
    # needs_sponsorship always blocks
    cfg.candidate.needs_sponsorship = True
    ev4 = rubric.evaluate(posting(text=POSTING + "\nNo visa sponsorship."), cfg, job_id="x")
    assert "no_sponsorship" in ev4.blockers


def test_unknown_country_sponsorship_is_a_flag(tmp_path, no_legitimacy):
    ev = rubric.evaluate(posting(location="", text=POSTING + "\nNo sponsorship available."), make_cfg(tmp_path),
                         job_id="x")
    assert "no_sponsorship" not in ev.blockers and "sponsorship_unclear" in ev.flags


def test_language_blocker(tmp_path, no_legitimacy):
    text = POSTING + "\nFluent German is required for this role."
    ev = rubric.evaluate(posting(text=text), make_cfg(tmp_path), job_id="x")
    assert "language:de" in ev.blockers and ev.lane == "excluded"
    lang_dim = next(d for d in ev.dimensions if d.key == "language")
    assert lang_dim.score == 0.0


def test_preferred_language_is_not_a_blocker(tmp_path, no_legitimacy):
    ev = rubric.evaluate(posting(text=POSTING + "\nGerman is an asset."), make_cfg(tmp_path), job_id="x")
    assert not any(b.startswith("language:") for b in ev.blockers)


def test_clearance_employment_and_avoid_blockers(tmp_path, no_legitimacy):
    cfg = make_cfg(tmp_path)
    ev = rubric.evaluate(posting(text=POSTING + "\nAn active Secret clearance is required."), cfg, job_id="x")
    assert "clearance" in ev.blockers
    ev = rubric.evaluate(posting(employment="contract"), cfg, job_id="x")
    assert "employment:contract" in ev.blockers
    ev = rubric.evaluate(posting(title="Data Science Intern"), cfg, job_id="x")
    assert "employment:internship" in ev.blockers
    ev = rubric.evaluate(posting(employer="Initech Inc."), cfg, job_id="x")
    assert "avoid_employer" in ev.blockers
    assert ev.lane == "excluded"


def test_legitimacy_flags_penalise_and_closed_blocks(tmp_path, monkeypatch):
    from jobveyra.evaluate import legitimacy
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(legitimacy, "check", lambda p, history, http=None, **k: [])
    base = rubric.evaluate(posting(), cfg, job_id="x").fit
    monkeypatch.setattr(legitimacy, "check", lambda p, history, http=None, **k: ["repost:3", "stale:90", "no_salary"])
    ev = rubric.evaluate(posting(), cfg, job_id="x")
    assert ev.fit == base - 20
    assert "repost:3" in ev.flags and "no_salary" in ev.flags
    monkeypatch.setattr(legitimacy, "check", lambda p, history, http=None, **k: ["closed"])
    ev = rubric.evaluate(posting(), cfg, job_id="x")
    assert "closed" in ev.blockers and ev.lane == "excluded"


def test_history_is_passed_to_legitimacy(tmp_path, monkeypatch):
    from jobveyra.evaluate import legitimacy
    seen = {}
    monkeypatch.setattr(legitimacy, "check", lambda p, history, http=None, **k: seen.setdefault("h", history) and [])
    rubric.evaluate(posting(), make_cfg(tmp_path), job_id="x", history=({"id": "a"},))
    assert seen["h"] == [{"id": "a"}]


def test_location_and_remote(tmp_path, no_legitimacy):
    cfg = make_cfg(tmp_path)
    loc = lambda p: next(d for d in rubric.evaluate(p, cfg, job_id="x").dimensions if d.key == "location")
    assert loc(posting(location="Madrid, Spain")).score == 0.8
    assert loc(posting(location="Berlin, Germany")).score == 0.0
    assert loc(posting(location="", remote=True)).score <= rubric.ESTIMATE_CAP
    cfg.focus.remote = "exclude"
    assert loc(posting(location="Lisbon", remote=True)).score == 0.1


def test_seniority(tmp_path, no_legitimacy):
    cfg = make_cfg(tmp_path)
    sen = lambda p: next(d for d in rubric.evaluate(p, cfg, job_id="x").dimensions if d.key == "seniority")
    assert sen(posting(title="Senior Data Scientist")).score == 1.0
    far = sen(posting(title="Director of Data Science", text="Requirements:\n- 15+ years of experience leading teams"))
    assert far.score < 0.3


def test_compensation_floor(tmp_path, no_legitimacy):
    cfg = make_cfg(tmp_path)
    comp = lambda p: next(d for d in rubric.evaluate(p, cfg, job_id="x").dimensions if d.key == "compensation")
    assert comp(posting()).score == 1.0
    low = comp(posting(text="Requirements:\n- Python\nSalary: €20,000 - €25,000 per year"))
    assert low.score < 0.3
    structured = comp(posting(salary_min=45000, salary_max=55000, salary_currency="EUR", text="Python required"))
    assert structured.score == 1.0 and structured.evidence[0].basis == "structure"
    usd = comp(posting(text="Python required. Pay: $70,000 - $80,000 a year", location="Lisbon"))
    assert any(e.basis == "estimate" and "approximate" in e.note for e in usd.evidence)


def test_freshness(tmp_path, no_legitimacy):
    cfg = make_cfg(tmp_path)
    fr = lambda p: next(d for d in rubric.evaluate(p, cfg, job_id="x").dimensions if d.key == "freshness")
    assert fr(posting(posted="2026-11-08")).score == 1.0
    assert fr(posting(posted="2026-07-01")).score == 0.2
    assert fr(posting(posted="2026-11-08", deadline="2026-11-01")).score == 0.0


def test_lane_uses_policy_thresholds(tmp_path, no_legitimacy):
    cfg = make_cfg(tmp_path, focus__flagship_employers=[])
    ev = rubric.evaluate(posting(employer="Globex"), cfg, job_id="x")
    assert ev.lane == queue.lane(ev.fit, False) == ("fast" if ev.fit >= 45 else "excluded")


def test_off_track_title(tmp_path, no_legitimacy):
    ev = rubric.evaluate(posting(title="Office Manager", text="Organise the office. Excel required."),
                         make_cfg(tmp_path), job_id="x")
    track = next(d for d in ev.dimensions if d.key == "track")
    assert track.score < 0.5 and ev.track == ""


def test_deterministic(tmp_path, no_legitimacy):
    cfg = make_cfg(tmp_path)
    a = rubric.evaluate(posting(), cfg, job_id="x").as_dict()
    b = rubric.evaluate(posting(), cfg, job_id="x").as_dict()
    assert a == b


def test_report_markdown(tmp_path, no_legitimacy):
    p = posting(text=POSTING + "\nFluent German is required.")
    ev = rubric.evaluate(p, make_cfg(tmp_path), job_id="x")
    md = rubric.report_markdown(ev, p)
    assert md.startswith("# Data Scientist — Example Labs")
    assert "| Dimension | Score | Weight | Points | Basis |" in md
    assert "- [text]" in md and "- [structure]" in md
    assert "`language:de`" in md and "## Flags" in md


def test_apply_semantic_only_raises(tmp_path, no_legitimacy):
    from jobveyra.models import Evidence
    cfg = make_cfg(tmp_path)
    ev = rubric.evaluate(posting(), cfg, job_id="x")
    before = next(d.score for d in ev.dimensions if d.key == "skills")
    fit0 = ev.fit
    ev = rubric.apply_semantic(ev, {"boost": 0.9, "evidence": [Evidence("model", "estimate")]}, cfg,
                               employer="Example Labs")
    after = next(d.score for d in ev.dimensions if d.key == "skills")
    assert after == pytest.approx(min(1.0, before + 0.15))
    assert ev.fit >= fit0
    ev2 = rubric.apply_semantic(ev, {"boost": -1}, cfg)
    assert next(d.score for d in ev2.dimensions if d.key == "skills") == after


# ---------------------------------------------------------------- lang

def test_detect_languages():
    assert lang.detect("We are looking for a data analyst to join our team and work with the product group.") == "en"
    assert lang.detect("Nous recherchons un analyste de données pour rejoindre notre équipe dans nos bureaux.") == "fr"
    assert lang.detect("Buscamos una persona analista de datos para nuestro equipo en Madrid con experiencia.") == "es"
    assert lang.detect("Procuramos uma pessoa para a nossa equipe de dados em Lisboa, com experiência em SQL.") == "pt"
    assert lang.detect("Wir suchen eine Person für unser Datenteam in Berlin und bieten flexible Arbeitszeiten.") == "de"
    assert lang.detect("Cerchiamo una persona per il nostro gruppo di lavoro con esperienza nella analisi dei dati.") == "it"
    assert lang.detect("Wij zoeken een collega voor ons team met ervaring in data en een passie voor analyse.") == "nl"
    assert lang.detect("我们正在寻找一位数据分析师加入我们的团队，负责数据建模和报告工作。") == "zh"
    assert lang.detect("私たちはデータアナリストを募集しています。チームで一緒に働きましょう。") == "ja"
    assert lang.detect("") == ""


def test_required_language_phrases():
    r = lang.required_languages("Français requis. Spanish is a plus.")
    assert r["fr"]["kind"] == "required" and r["es"]["kind"] == "preferred"
    r = lang.required_languages("Must be bilingual.", country="CA")
    assert set(r) == {"en", "fr"}
    assert lang.required_languages("Our office overlooks the French Riviera.") == {}
    assert lang.required_languages("Working knowledge of Italian required")["it"]["level"] == "B1"


def test_level_rank():
    assert lang.level_rank("C1") > lang.level_rank("B2") > lang.level_rank("B1")
    assert lang.level_rank("native") == 7 and lang.level_rank("Fluent") == 5 and lang.level_rank("") == 0


def test_french_posting(tmp_path, no_legitimacy):
    cfg = config.from_dict({
        "candidate": {"name": "Alex Rivera", "languages": {"en": "C1", "fr": "B2"}, "work_authorization": ["CA"]},
        "focus": {"regions": [{"name": "Toronto", "match": ["toronto"]}],
                  "tracks": [{"key": "st", "label": "Statistique", "titles": ["statisticien"],
                              "skills": ["r", "sas", "statistics"]}],
                  "salary_floor": 60000, "salary_currency": "CAD"}}, tmp_path)
    text = ("Nous recherchons une personne pour notre équipe de statistique à Ottawa.\n\n"
            "Exigences\n- Maîtrise de R et SAS\n- 5 ans d'expérience en analyse statistique\n"
            "- Maîtrise du français et de l'anglais (bilinguisme requis)\n\nAtouts\n- Connaissance de Python\n\n"
            "Salaire : 70 000 $ à 85 000 $ par année\n")
    p = posting(employer="Globex", title="Statisticien", location="Ottawa, ON", text=text)
    reqs = rubric.extract_requirements(text)
    assert not any(r.degree for r in reqs)                    # "maîtrise de" is mastery, not a degree
    assert not any("Salaire" in r.text for r in reqs)
    assert next(r for r in reqs if "ans" in r.text).years == 5
    ev = rubric.evaluate(p, cfg, job_id="x")
    assert not ev.blockers and ev.track == "st"
    by = {d.key: d for d in ev.dimensions}
    assert any("fr required" in e.note for e in by["language"].evidence)
    assert by["compensation"].score == 1.0 and "CAD" in by["compensation"].evidence[0].note
    cfg.candidate.languages = {"en": "C1"}
    ev = rubric.evaluate(p, cfg, job_id="x")
    assert "language:fr" in ev.blockers
