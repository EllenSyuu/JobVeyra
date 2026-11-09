import re
from pathlib import Path

import pytest

from jobveyra import config
from jobveyra.interview import followups, negotiation, prep, stories
from jobveyra.models import Posting

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "jobveyra.yml"

POSTING_TEXT = """Example Labs builds forecasting tools for retail planners. We are hiring a data scientist to join our applied team.

Requirements
- 3+ years of experience with Python and SQL
- Build and validate forecasting models for demand planning
- Communicate results to non-technical stakeholders
- Experience with experimentation and A/B testing
- Collaborate with product managers to prioritise work

Nice to have
- Spark or dbt
"""

CHURN = """id: churn-model
title: Rebuilt the demand forecasting model
situation: Weekly forecasts at a retail client were late and inaccurate.
task: Replace the spreadsheet forecast with a validated model.
action: Built a Python forecasting pipeline with backtesting and explained results to planners.
result: Forecast error fell and the weekly run became automatic.
reflection: Agree on the error metric with stakeholders first.
skills: [python, forecasting, stakeholder communication]
metrics:
  - {value: "error down 18%", source: "cv/master.md: Globex 2024"}
"""

PITCH = """- id: ab-test
  title: Designed a pricing A/B test
  situation: A pricing change was about to ship untested.
  task: Measure the effect before a full rollout.
  action: Designed the experimentation plan in SQL and Python and presented it to product managers.
  result: The team shipped the variant that won.
  skills: [experimentation, sql]
  metrics:
    - "conversion up 4%"
- id: broken
  title: Missing fields
"""


@pytest.fixture
def cfg(tmp_path):
    import yaml
    return config.from_dict(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")), tmp_path)


@pytest.fixture
def bank(tmp_path):
    d = tmp_path / "stories"
    d.mkdir()
    (d / "churn.yml").write_text(CHURN, encoding="utf-8")
    (d / "pitch.yml").write_text(PITCH, encoding="utf-8")
    (d / "bad.yml").write_text("id: [unclosed", encoding="utf-8")
    return stories.load(tmp_path)


def posting():
    return Posting(source="greenhouse", employer="Example Labs", title="Data Scientist",
                   url="https://boards.greenhouse.io/examplelabs/jobs/111", location="Lisbon, Portugal",
                   deadline="2026-03-20", text=POSTING_TEXT, extra={"flags": ["no_salary", "repost:3"]})


# ---------------------------------------------------------------- stories

def test_load_validates_and_reports(bank):
    items, problems = bank
    ids = [s["id"] for s in items]
    assert ids == ["churn-model", "ab-test"]
    ab = items[1]
    assert ab["unsourced"] == ["conversion up 4%"]
    assert items[0]["unsourced"] == []
    joined = "\n".join(problems)
    assert "ab-test: metric 1 (conversion up 4%) has no source" in joined
    assert "broken: missing situation" in joined
    assert "bad.yml: invalid YAML" in joined


def test_load_missing_dir(tmp_path):
    assert stories.load(tmp_path / "nowhere") == ([], [])


def test_requirements_prefers_section_bullets():
    reqs = stories.requirements(POSTING_TEXT)
    assert reqs[0] == "3+ years of experience with Python and SQL"
    assert "Spark or dbt" in reqs
    assert stories.requirements("You will build dashboards. Experience with Tableau is required. We like cake.") == [
        "You will build dashboards", "Experience with Tableau is required"]


def test_match_ranks_by_overlap(bank):
    items, _ = bank
    ranked = stories.match(items, posting())
    assert [r["story"]["id"] for r in ranked] == ["churn-model", "ab-test"]
    assert "forecasting" in ranked[0]["matched"] and "python" in ranked[0]["matched"]
    assert ranked[0]["score"] > ranked[1]["score"] > 0
    assert stories.match(items, "Underwater basket weaving.") == []


# ---------------------------------------------------------------- prep

def test_prep_sheet_sections(bank, cfg):
    items, _ = bank
    job = {"id": "example-labs:greenhouse:111", "employer": "Example Labs", "title": "Data Scientist",
           "family": "ds", "fit": 74, "deadline": "2026-03-20", "state": "submitted",
           "flags": "stale:45"}
    md = prep.prep_sheet(job, posting(), items, cfg)
    for head in ("# Interview prep: Data Scientist at Example Labs", "## Role summary",
                 "## Top requirements and your evidence", "## Likely questions", "### Behavioral",
                 "### Technical", "### Motivation", "## Stories to use", "## Questions to ask them",
                 "## Logistics", "## Red flags"):
        assert head in md
    for cat in ("Behavioral", "Technical", "Motivation"):
        block = md.split(f"### {cat}")[1].split("###")[0].split("## ")[0]
        assert len(re.findall(r"(?m)^\d+\. ", block)) == 5
    assert "Application deadline: 2026-03-20" in md
    assert "Fit score: 74 / 100" in md
    assert 'story "Rebuilt the demand forecasting model"' in md
    assert "track skill: python" in md
    assert "no salary is published" in md and "reposted 3 times" in md and "45 days old" in md
    assert "Do not quote that number until it is sourced" in md
    assert "Why do you want to work at Example Labs?" in md
    assert "stakeholders" in md.split("### Behavioral")[1].split("### Technical")[0]
    assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", md)


def test_prep_sheet_without_evidence(cfg):
    md = prep.prep_sheet({"employer": "Globex", "title": "Analyst"}, "Requirements\n- Fluent in Klingon\n", [], cfg)
    assert "Evidence: none on file yet" in md
    assert "No story in the bank overlaps" in md
    assert "Application deadline: not stated" in md
    assert "None recorded." in md


# ---------------------------------------------------------------- negotiation

def test_negotiation_script(cfg):
    md = negotiation.script({"employer": "Example Labs", "title": "Data Scientist", "base": 50000, "currency": "EUR",
                             "bonus": "10%", "benefits": ["health", "pension"],
                             "competing": [{"employer": "Globex", "base": 54000, "deadline": "2026-04-01"}, "verbal interest elsewhere"]},
                            cfg)
    assert "Your floor is EUR 40,000. The offer is 25% above it." in md
    assert "EUR 54,000 to EUR 57,000" in md                   # +8% / +15%, rounded to 1,000
    assert "Globex: EUR 54,000, with a deadline of 2026-04-01" in md
    assert "verbal interest elsewhere" in md
    assert "Benefits: health, pension" in md
    assert "Signing bonus" in md and "Start date" in md
    assert "not legal or financial advice" in md


def test_negotiation_below_floor_and_custom_range(cfg):
    md = negotiation.script({"base": 36000, "currency": "EUR"}, cfg, counter_low=0.05, counter_high=0.10)
    assert "below it" in md
    assert "EUR 40,000 to EUR 40,000" in md                   # never counter below the floor
    assert "None. Do not imply one" in md
    with pytest.raises(ValueError):
        negotiation.script({"base": 1}, cfg, counter_low=0.2, counter_high=0.1)
    md2 = negotiation.script({"currency": "USD"}, cfg)
    assert "Ask for the base salary" in md2 and "convert it before comparing" in md2


# ---------------------------------------------------------------- follow-ups

def test_followups_due():
    jobs = [{"id": "a", "employer": "Example Labs", "title": "Data Scientist", "state": "submitted",
             "updated_at": "2026-03-01T09:00:00", "req_id": "R-1001"},
            {"id": "b", "employer": "Globex", "title": "Analyst", "state": "submitted", "updated_at": "2026-03-01T09:00:00"},
            {"id": "c", "employer": "Globex", "title": "Engineer", "state": "submitted", "updated_at": "2026-03-10T09:00:00"},
            {"id": "d", "employer": "Globex", "title": "Lead", "state": "submitted", "submitted_at": "2026-02-01T09:00:00",
             "updated_at": "2026-03-12T09:00:00"},
            {"id": "e", "employer": "Globex", "title": "Manager", "state": "submitted", "updated_at": "2026-02-01T09:00:00"},
            {"id": "f", "employer": "Globex", "title": "Draft", "state": "eligible", "updated_at": "2026-02-01T09:00:00"}]
    outs = [{"job_id": "b", "outcome": "rejected", "at": "2026-03-05T00:00:00"},
            {"job_id": "e", "outcome": "no_reply", "at": "2026-03-10T00:00:00"}]
    rows = followups.due(jobs, outs, "2026-03-15", 10, name="Alex Rivera")
    assert [r["job_id"] for r in rows] == ["d", "a"]          # e was nudged 5 days ago; c too recent
    assert rows[0]["days_waiting"] == 42
    a = rows[1]
    assert a["days_waiting"] == 14 and a["employer"] == "Example Labs"
    assert "Data Scientist" in a["suggested_message"] and "March 1" in a["suggested_message"]
    assert "R-1001" in a["suggested_message"] and a["suggested_message"].rstrip().endswith("Alex Rivera")
    assert len(a["suggested_message"]) < 600
    assert [r["job_id"] for r in followups.due(jobs, outs, "2026-03-25", 10)] == ["d", "e", "a", "c"]
