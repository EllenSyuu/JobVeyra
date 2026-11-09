import pytest

from jobveyra import config
from jobveyra.materials import ats, cover, fabrication, outbound
from jobveyra.models import Posting

FACTS = """Alex Rivera
M.Sc. Statistics, University of Example (Sep 2019 - Jun 2021)
B.Sc. Mathematics (2018)
Data Analyst at Example Labs, 09/2021 - present
- Cut report turnaround by 40 percent across 1200 weekly reports
- Built a churn model on 7.17 million customer records
- Managed a $2 million marketing budget with Globex
IELTS 8.0
"""


# ---------------------------------------------------------------- fabrication

def test_supported_claims_pass_in_other_formats():
    doc = ("At Example Labs I cut report turnaround by 40% across 1,200 weekly reports, built a churn model "
           "on 7.17M records and managed a $2M budget with Globex. M.Sc. in Statistics, September 2019. "
           "IELTS 8.0. I have worked there since 2021.")
    assert fabrication.check(doc, FACTS) == []


def test_unsupported_claims_are_reported():
    doc = ("I raised revenue by 35% for Initech in March 2022, led 12 analysts, hold a PhD and the CFA "
           "Level II, and worked with Umbrella Analytics from 2016. Data Analyst at Example Labs since Oct 2021.")
    bad = fabrication.check(doc, FACTS)
    for item in ("35%", "Initech", "March 2022", "12", "PhD", "CFA Level II", "Umbrella Analytics", "2016",
                 "Oct 2021"):
        assert item in bad, item
    assert "Example Labs" not in bad


def test_percent_needs_percent_and_value_equivalence():
    assert fabrication.check("grew 1200%", FACTS) == ["1200%"]
    assert fabrication.check("2 million dollars", FACTS) == []
    assert fabrication.check("€2,000,000", FACTS) == []


def test_degree_rules():
    assert fabrication.check("Master of Science in Statistics", FACTS) == []
    assert fabrication.check("a Master's degree", FACTS) == []
    assert fabrication.check("an MBA", FACTS) == ["MBA"]
    assert fabrication.check("Master of Finance", FACTS) == ["Master of Finance"]


def test_noise_is_ignored():
    doc = "1. Contact alex.rivera@example.com or +351 912 345 678, see https://example.com/p/2024"
    assert fabrication.check(doc, FACTS) == []


def test_story_provenance():
    story = "I joined Example Labs in 2021. The model cut churn by 18%. Everyone was happy."
    out = fabrication.story_provenance(story, FACTS)
    assert out == [{"sentence": "The model cut churn by 18%.", "unsupported": ["18%"]}]


# ---------------------------------------------------------------- outbound

@pytest.mark.parametrize("text", [
    "Unfortunately I lack experience with Spark.",
    "I don't have hands-on Kubernetes experience.",
    "I have no experience with Scala.",
    "I am not familiar with dbt.",
    "I have never actually used Airflow in production.",
    "My biggest gap is cloud tooling.",
    "I would need to learn your stack quickly.",
    "I would require sponsorship to work in the US.",
    "This letter was written with the help of ChatGPT.",
    "Je n'ai pas d'expérience en Spark.",
    "Je ne maîtrise pas Java.",
    "No tengo experiencia con Kubernetes.",
    "Tengo poca experiencia en finanzas.",
    "Não tenho experiência com Scala.",
    "Infelizmente, não trabalhei com Java.",
])
def test_outbound_blocks(text):
    assert outbound.check(text), text


@pytest.mark.parametrize("text", [
    "I built forecasting models in Python for three product teams.",
    "I am not only an analyst but also a teacher.",
    "Our gap analysis found 3 issues.",
    "J'ai développé des modèles de prévision en Python.",
    "Desarrollé modelos de previsión en Python.",
])
def test_outbound_passes(text):
    assert outbound.check(text) == []


def test_outbound_confirmed_marker_and_line_numbers():
    text = "Hello\nI would require sponsorship for this role. (confirmed)\nI lack SQL."
    hits = outbound.check(text)
    assert len(hits) == 1 and hits[0].startswith("line 3:")


def test_outbound_kinds():
    assert outbound.check("My French is intermediate.")
    assert outbound.check("My French is intermediate.", kind="cv") == []
    answers = "Kubernetes: 0 years\nScala: No\nDo you require sponsorship?: No\nPython: 5 years"
    hits = outbound.check(answers, kind="answers")
    assert len(hits) == 2 and "line 1" in hits[0] and "line 2" in hits[1]
    with pytest.raises(ValueError):
        outbound.check("x", kind="email")


def test_outbound_strips_latex():
    assert outbound.check(r"I \textbf{don't have} a degree % comment I lack nothing")
    assert outbound.check(r"Fine text % I lack SQL") == []


# ---------------------------------------------------------------- ats

def test_ats_clean_text():
    text = "Alex Rivera\nalex.rivera@example.com | +351 912 345 678\nPython, SQL, machine learning, Tableau dashboards"
    r = ats.check_text(text, ["Python", "SQL", "ML", "Tableau", "Kubernetes"])
    assert r["coverage"] == 80.0 and r["missing"] == ["Kubernetes"]
    assert "ML" in r["matched"] and r["synonym_only"] == ["ML"]
    assert r["has_email"] and r["has_phone"]
    assert r["score"] == 90 and len(r["reasons"]) == 1


def test_ats_noise_and_missing_contacts():
    text = "Alex Rivera\n(cid:12)(cid:7) Python e�cient work ﬁnance and the o ce speci c\n" + "x" * 200
    r = ats.check_text(text, ["Python"])
    assert not r["has_email"] and not r["has_phone"]
    assert r["noise"]["cid"] == 2 and r["noise"]["replacement"] == 1 and r["noise"]["ligatures"] == 1
    assert r["noise"]["ligature_gaps"] >= 2
    assert r["score"] == 100 - 15 - 10 - 20 - 15 - 10
    assert len(r["reasons"]) == 5


def test_ats_empty():
    r = ats.check_text("", ["Python"])
    assert r["score"] == 0 and r["missing"] == ["Python"]


# ---------------------------------------------------------------- cover

def test_cover_angles(tmp_path):
    (tmp_path / "cv").mkdir()
    (tmp_path / "cv" / "master.md").write_text("Alex Rivera\nPython, SQL, Docker, forecasting\n", encoding="utf-8")
    cfg = config.from_dict({
        "candidate": {"name": "Alex Rivera", "master_cv": "cv/master.md"},
        "focus": {"tracks": [{"key": "ds", "label": "Data science", "titles": ["data scientist"],
                              "skills": ["python", "statistics"]}]}}, tmp_path)
    text = """About Globex
Our mission is to make freight cheaper for small shippers. We build routing software used by 4,000 carriers.

Responsibilities
- Own the demand forecasting pipeline
- Partner with operations on pricing experiments

Requirements
- Python and SQL
- Experience with Kubernetes
- Statistics background

Nice to have
- Docker
"""
    p = Posting(source="lever", employer="Globex", title="Data Scientist", url="https://jobs.example/2", text=text)
    a = cover.angles(p, cfg)
    assert a["why_company"][0].startswith("Our mission is to make freight cheaper")
    assert a["problems"][:2] == ["Own the demand forecasting pipeline", "Partner with operations on pricing experiments"]
    reqs = {x["requirement"]: x for x in a["approach"]}
    assert "Python and SQL" in reqs and "track skills" in reqs["Python and SQL"]["source"]
    assert reqs["Docker"]["source"] == "CV"
    assert "Experience with Kubernetes" not in reqs and a["gaps"] == ["Experience with Kubernetes"]
    assert a["language"] == "en" and a["tone"] in ("neutral", "formal", "casual")
    assert a["keywords"][:2] == ["python", "sql"] or set(a["keywords"][:4]) >= {"python", "sql"}


def test_tone():
    assert cover.tone_of("The successful candidate shall report to the Director. Applicants must hold a degree.") == "formal"
    assert cover.tone_of("Hey folks! We're an awesome crew and you'll love it! Fun vibes!") == "casual"
    assert cover.tone_of("You will build models and present results.") == "neutral"
