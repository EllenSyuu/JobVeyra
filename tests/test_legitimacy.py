"""Legitimacy flags: closed, repost, stale, evergreen, no_salary, vague_title."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from jobveyra import discover, queue
from jobveyra.evaluate import legitimacy
from jobveyra.models import Posting
from jobveyra.sources.http import Http

FIX = Path(__file__).parent / "fixtures" / "sources"
TODAY = dt.date(2026, 11, 9)


def P(**kw) -> Posting:
    base = dict(source="greenhouse", employer="Example Labs", title="Data Scientist",
                url="https://boards.greenhouse.io/examplelabs/jobs/4012345", posted="2026-10-20",
                salary_min=55000.0, salary_max=70000.0, salary_currency="EUR", text="Build forecasting models.")
    base.update(kw)
    return Posting(**base)


def row(p: Posting, **over) -> dict:
    r = p.to_queue()
    r.update(id=discover.posting_id(p), employer_key=queue.employer_key(p.employer))
    r.update(over)
    return r


def check(p, history=(), http=None):
    return legitimacy.check(p, list(history), http, today=TODAY)


def test_clean_posting_has_no_flags():
    assert check(P()) == []


# ---------------------------------------------------------------- repost

def test_repost_same_title_different_id():
    old = P(url="https://boards.greenhouse.io/examplelabs/jobs/3900001", text="Older text.")
    older = P(url="https://boards.greenhouse.io/examplelabs/jobs/3800001", title="Data Scientist (REQ-12345)",
              text="Even older.")
    assert check(P(), [row(old), row(older)]) == ["repost:2"]


def test_repost_matches_employer_key_not_display_name():
    old = P(employer="Example Labs, Inc.", url="https://boards.greenhouse.io/examplelabs/jobs/3900001")
    assert check(P(), [row(old)]) == ["repost:1"]


def test_same_job_already_in_history_is_not_a_repost():
    p = P()
    assert check(p, [row(p)]) == []


def test_same_hash_new_posted_date_is_repost():
    p = P()
    assert check(p, [row(p, posted="2026-08-01")]) == ["repost:1"]


def test_same_hash_under_other_employer_title_row():
    p = P()
    other = row(P(url="https://jobs.example.com/x"), title="Data Scientist - Forecasting")
    assert check(p, [other]) == ["repost:1"]


def test_different_title_or_employer_is_not_repost():
    hist = [row(P(title="Data Analyst", url="https://boards.greenhouse.io/examplelabs/jobs/1", text="x")),
            row(P(employer="Globex", url="https://boards.greenhouse.io/globex/jobs/2", text="y"))]
    assert check(P(), hist) == []


# ---------------------------------------------------------------- stale

def test_stale_after_45_days():
    assert check(P(posted="2026-09-25")) == []                     # 45 days: not yet
    assert check(P(posted="2026-09-24")) == ["stale:46"]
    assert check(P(posted="")) == []
    assert check(P(posted="not a date")) == []


def test_stale_uses_queue_clock_by_default(monkeypatch):
    monkeypatch.setenv("JOBQUEUE_NOW", "2027-01-01T00:00:00")
    assert legitimacy.check(P(), [], None) == ["stale:73"]


# ---------------------------------------------------------------- evergreen

@pytest.mark.parametrize("kw", [
    {"text": "Join our talent pool for future openings."},
    {"text": "We are always accepting applications from statisticians."},
    {"title": "General Application - Data"},
    {"title": "Data Scientist - Pipeline"},
    {"text": "This is a pipeline requisition; hiring happens on a rolling basis."},
    {"text": "Candidature spontanée : envoyez-nous votre CV."},
])
def test_evergreen(kw):
    assert "evergreen" in check(P(**kw))


def test_data_pipelines_in_text_are_not_evergreen():
    assert check(P(text="You will build data pipelines in Airflow.")) == []


# ---------------------------------------------------------------- no_salary

def test_no_salary_when_fields_and_text_are_silent():
    assert check(P(salary_min=None, salary_max=None, text="Great team, great culture.")) == ["no_salary"]


@pytest.mark.parametrize("text", [
    "The range is $80,000 - $100,000.", "Salary: €55k", "CAD 90,000 per year", "Salaire : 65 000 $ par année",
    "Salary range 70000 to 85000", "Compensation range: 120k-140k",
])
def test_salary_in_text_counts(text):
    assert "no_salary" not in check(P(salary_min=None, salary_max=None, text=text))


def test_pay_attention_is_not_salary():
    assert check(P(salary_min=None, salary_max=None, text="Pay attention to detail; 5 years of SQL.")) == ["no_salary"]


# ---------------------------------------------------------------- vague_title

@pytest.mark.parametrize("title", ["Various Positions", "Multiple roles", "Open positions", "Join our team!",
                                   "Opportunities", "Plusieurs postes", "Staff", "General application", "IT"])
def test_vague_title(title):
    assert "vague_title" in check(P(title=title))


@pytest.mark.parametrize("title", ["Data Scientist", "Senior Statistician, Positions Team", "Staff Data Scientist"])
def test_specific_titles_are_not_vague(title):
    assert "vague_title" not in check(P(title=title))


# ---------------------------------------------------------------- closed

def test_closed_when_url_is_gone():
    assert check(P(url="https://jobs.example.com/gone"), http=Http(fixtures=FIX)) == ["closed"]


def test_closed_when_url_missing_404():
    assert check(P(url="https://jobs.example.com/never-existed"), http=Http(fixtures=FIX)) == ["closed"]


@pytest.mark.parametrize("url", ["https://jobs.example.com/filled", "https://jobs.example.com/fr-ferme"])
def test_closed_when_page_says_so(url):
    assert check(P(url=url), http=Http(fixtures=FIX)) == ["closed"]


def test_live_page_is_not_closed():
    h = Http(fixtures=FIX)
    assert check(P(), http=h) == []
    assert ("HEAD", P().url) in h.requests and ("GET", P().url) in h.requests


def test_no_http_means_no_liveness_check():
    assert check(P(url="https://jobs.example.com/gone")) == []


def test_liveness_errors_are_ignored():
    class Broken:
        def head(self, url):
            raise OSError("boom")
    assert check(P(), http=Broken()) == []


def test_flags_are_sorted_and_unique():
    p = P(title="Various positions", posted="2026-01-02", salary_min=None, salary_max=None,
          text="Join our talent pool. Join our talent pool.", url="https://jobs.example.com/gone")
    flags = check(p, [row(P(title="Various positions", url="https://x.example/9", text="z"))], http=Http(fixtures=FIX))
    assert flags == sorted(set(flags))
    assert flags == ["closed", "evergreen", "no_salary", "repost:1", "stale:311", "vague_title"]
