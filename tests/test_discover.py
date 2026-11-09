"""Focus filters and end-to-end discovery into a temporary workspace (no network)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from jobveyra import config, discover, filters, queue
from jobveyra.models import Posting
from jobveyra.sources import base
from jobveyra.sources.http import Http

FIX = Path(__file__).parent / "fixtures" / "sources"

FOCUS = {
    "regions": [
        {"name": "Lisbon", "match": ["lisbon", "lisboa", "portugal"], "weight": 1.0},
        {"name": "Madrid", "match": ["madrid"], "weight": 0.8},
        {"name": "Remote Europe", "match": ["remote - europe", "emea", "europe"], "weight": 0.7},
    ],
    "remote": "allow",
    "tracks": [
        {"key": "ds", "label": "Data science", "titles": ["data scientist", "machine learning", "applied scientist"]},
        {"key": "analytics", "label": "Analytics", "titles": ["data analyst", "analytics", "business intelligence"]},
    ],
    "seniority_min": "junior",
    "seniority_max": "senior",
    "exclude_titles": ["unpaid", "volunteer", "intern"],
    "employment": ["full_time"],
    "avoid_employers": ["Soylent"],
}


def focus(**over) -> config.Focus:
    raw = json.loads(json.dumps(FOCUS))
    raw.update(over)
    return config.from_dict({"focus": raw}, Path(".")).focus


def P(title="Data Scientist", location="Lisbon, Portugal", remote=None, employer="Example Labs", **kw) -> Posting:
    return Posting(source="test", employer=employer, title=title, url=kw.pop("url", "https://jobs.example.com/1"),
                   location=location, remote=remote, **kw)


# ---------------------------------------------------------------- region_of

def test_region_matches_case_insensitive_substring():
    f = focus()
    assert filters.region_of("LISBON, Portugal", None, f).name == "Lisbon"
    assert filters.region_of("Porto, Portugal", None, f).name == "Lisbon"
    assert filters.region_of("Madrid, Spain", False, f).name == "Madrid"
    assert filters.region_of("Berlin, Germany", None, f) is None
    assert filters.region_of("", None, f) is None


def test_region_ignores_accents():
    f = focus(regions=[{"name": "Sao Paulo", "match": ["sao paulo"]}])
    assert filters.region_of("São Paulo, Brasil", None, f).name == "Sao Paulo"


def test_region_short_match_is_whole_word():
    f = focus(regions=[{"name": "US", "match": ["us"]}])
    assert filters.region_of("Austin, US", None, f).name == "US"
    assert filters.region_of("Austin, TX", None, f) is None


def test_region_remote_policy():
    only, excl = focus(remote="only"), focus(remote="exclude")
    assert filters.region_of("Lisbon, Portugal", False, only) is None
    assert filters.region_of("Lisbon, Portugal", None, only) is None
    assert filters.region_of("Remote - Europe", None, only).name == "Remote Europe"      # inferred from text
    assert filters.region_of("Portugal", True, only).name == "Lisbon"
    assert filters.region_of("Remote - Europe", True, excl) is None
    assert filters.region_of("Lisbon, Portugal", False, excl).name == "Lisbon"


def test_region_remote_ok_false_skips_remote_jobs():
    f = focus(regions=[{"name": "Lisbon", "match": ["lisbon"], "remote_ok": False},
                       {"name": "Anywhere EU", "match": ["lisbon", "europe"], "remote_ok": True}])
    assert filters.region_of("Lisbon", False, f).name == "Lisbon"
    assert filters.region_of("Lisbon", True, f).name == "Anywhere EU"
    f2 = focus(regions=[{"name": "Lisbon", "match": ["lisbon"], "remote_ok": False}])
    assert filters.region_of("Lisbon", True, f2) is None


def test_region_open_remote_location_uses_first_remote_ok_region():
    f = focus(regions=[{"name": "Lisbon", "match": ["lisbon"], "remote_ok": False},
                       {"name": "Remote", "match": ["europe"], "remote_ok": True}])
    assert filters.region_of("Anywhere", True, f).name == "Remote"
    assert filters.region_of("", True, f).name == "Remote"
    assert filters.region_of("Remote", None, f).name == "Remote"
    assert filters.region_of("USA Only", True, f) is None


def test_region_without_regions_matches_anything():
    f = focus(regions=[])
    assert filters.region_of("Nairobi", None, f) is filters.ANY_REGION
    assert filters.region_of("Nairobi", False, focus(regions=[], remote="only")) is None


# ---------------------------------------------------------------- seniority_of

@pytest.mark.parametrize("title,level", [
    ("Data Scientist", "mid"), ("Senior Data Scientist", "senior"), ("Sr. Data Analyst", "senior"),
    ("Junior Data Analyst", "junior"), ("Jr Analyst", "junior"), ("Entry-Level Statistician", "junior"),
    ("Graduate Analyst", "junior"), ("Associate Statistician", "junior"), ("Data Analyst I", "junior"),
    ("Data Analyst II", "mid"), ("Statistician III", "senior"), ("Intermediate Analyst", "mid"),
    ("Lead Data Engineer", "lead"), ("Team Lead, Analytics", "lead"), ("Staff Machine Learning Engineer", "lead"),
    ("Principal Data Scientist", "principal"), ("Distinguished Engineer", "principal"),
    ("Director of Analytics", "director"), ("Head of Data", "director"), ("Associate Director, Risk", "director"),
    ("Chief Data Officer", "executive"), ("VP, Data", "executive"), ("Managing Director, Quant", "executive"),
    ("Data Science Intern", "intern"), ("Summer Internship - Statistics", "intern"), ("Co-op Student, Data", "intern"),
    # French, Spanish, Portuguese, German
    ("Stagiaire en science des données", "intern"), ("Analyste sénior", "senior"), ("Analyste principal", "principal"),
    ("Directeur, Analytique", "director"), ("Directrice des données", "director"), ("Chef d'équipe, données", "lead"),
    ("Científico de Datos Junior", "junior"), ("Analista Sénior", "senior"), ("Becario de Datos", "intern"),
    ("Jefe de Analítica", "lead"), ("Estagiário em Dados", "intern"), ("Analista de Dados Pleno", "mid"),
    ("Diretora de Dados", "director"), ("Werkstudent Data Science", "intern"), ("Praktikant Statistik", "intern"),
    ("Leiter Data Analytics", "director"), ("Abteilungsleiter Risikomanagement", "director"),
    ("Teamleiter BI", "lead"), ("Senior Datenanalyst", "senior"),
    # words that must not trigger a level
    ("Internal Audit Analyst", "mid"), ("International Statistician", "mid"), ("Product Manager", "mid"),
    ("Staff Accountant", "mid"), ("Executive Assistant to the CEO", "junior"), ("Leading Analyst", "mid"),
])
def test_seniority_of(title, level):
    assert filters.seniority_of(title) == level


# ---------------------------------------------------------------- track_of

def test_track_of():
    f = focus()
    assert filters.track_of("Senior Data Scientist", f).key == "ds"
    assert filters.track_of("Business Intelligence Analyst", f).key == "analytics"
    assert filters.track_of("Machine Learning Engineer", f).key == "ds"
    assert filters.track_of("Accountant", f) is None
    assert filters.track_of("Data Analytics Lead", f).key == "analytics"


# ---------------------------------------------------------------- passes

@pytest.mark.parametrize("posting,reason", [
    (P(), ""),
    (P(employer="Soylent Corp."), "avoid_employer"),
    (P(employer="SOYLENT"), "avoid_employer"),
    (P(title="Unpaid Data Scientist"), "title:unpaid"),
    (P(title="Data Science Intern"), "title:intern"),
    (P(title="Internal Data Scientist"), ""),                     # whole words only
    (P(employment="contract"), "employment:contract"),
    (P(employment="part_time"), "employment:part_time"),
    (P(employment=""), ""),                                       # unknown employment passes
    (P(title="Director of Data Science"), "seniority:director"),
    (P(title="Principal Data Scientist"), "seniority:principal"),
    (P(location="Berlin, Germany"), "region"),
    (P(location="Remote - Europe", remote=True), ""),
])
def test_passes(posting, reason):
    ok, why = filters.passes(posting, focus())
    assert (ok, why) == (reason == "", reason)


def test_passes_seniority_range_and_remote_reasons():
    f = focus(seniority_min="intern", seniority_max="junior", exclude_titles=[])
    assert filters.passes(P(title="Data Science Intern"), f) == (True, "")
    assert filters.passes(P(title="Senior Data Scientist"), f) == (False, "seniority:senior")
    assert filters.passes(P(), focus(remote="only")) == (False, "remote:only")
    assert filters.passes(P(location="Remote - Europe", remote=True), focus(remote="exclude")) == (False, "remote:excluded")


def test_passes_check_order():
    # avoid_employer wins over title, title over employment, employment over seniority, seniority over region
    p = P(employer="Soylent", title="Unpaid Director", employment="contract", location="Mars")
    assert filters.passes(p, focus())[1] == "avoid_employer"
    p.employer = "Globex"
    assert filters.passes(p, focus())[1] == "title:unpaid"
    p.title = "Director"
    assert filters.passes(p, focus())[1] == "employment:contract"
    p.employment = ""
    assert filters.passes(p, focus())[1] == "seniority:director"
    p.title = "Analyst"
    assert filters.passes(p, focus())[1] == "region"


# ---------------------------------------------------------------- discover.run

SOURCES = [
    {"type": "greenhouse", "board": "examplelabs"},
    {"type": "lever", "board": "globex", "employer": "Globex"},
    {"type": "ashby", "board": "initech", "employer": "Initech"},
    {"type": "workable", "board": "umbrella-analytics"},
    {"type": "smartrecruiters", "board": "Hooli"},
    {"type": "recruitee", "board": "vandelay"},
    {"type": "remotive", "category": "data", "currency": "USD"},
    {"type": "jsonld", "name": "careers-pages",
     "urls": ["https://careers.example.org/jobs", "https://careers.globex.example/jobs"]},
    {"type": "linkedin_alert", "name": "alerts", "path": "inbox/alert.html"},
    {"type": "usajobs", "keyword": "statistician"},
    {"type": "monster", "name": "nope"},
    {"type": "un_careers", "keywords": ["statistics"], "enabled": False},
]


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBVEYRA_HOME", str(tmp_path))
    monkeypatch.delenv("JOBQUEUE_DIR", raising=False)
    monkeypatch.delenv("USAJOBS_API_KEY", raising=False)
    monkeypatch.delenv("USAJOBS_EMAIL", raising=False)
    (tmp_path / "inbox").mkdir()
    shutil.copy(FIX / "linkedin" / "alert.html", tmp_path / "inbox" / "alert.html")
    return tmp_path


def rows_of(cfg) -> list[dict]:
    q = queue.Queue(cfg.state_dir)
    try:
        return q.all()
    finally:
        q.db.close()


def make_cfg(ws, sources=None, **focus_over):
    raw = json.loads(json.dumps(FOCUS))
    raw.update(focus_over)
    return config.from_dict({"focus": raw, "sources": sources if sources is not None else SOURCES,
                             "policy": {"exclude_below": 40, "full_package_at": 75}}, ws)


def test_run_end_to_end(ws):
    cfg = make_cfg(ws)
    stats = discover.run(cfg, Http(fixtures=FIX))
    assert set(stats) == {"fetched", "new", "filtered", "by_source", "errors"}
    assert stats["by_source"] == {"greenhouse": 3, "lever": 2, "ashby": 2, "workable": 2, "smartrecruiters": 2,
                                  "recruitee": 1, "remotive": 3, "careers-pages": 3, "alerts": 3, "usajobs": 0}
    assert stats["fetched"] == 21
    assert stats["filtered"] == {"seniority:director": 1, "title:intern": 1, "employment:contract": 3,
                                 "employment:part_time": 1, "region": 1, "avoid_employer": 1}
    assert stats["new"] == 13
    assert stats["fetched"] == stats["new"] + sum(stats["filtered"].values())
    assert set(stats["errors"]) == {"usajobs", "nope"}
    assert "USAJOBS_API_KEY" in stats["errors"]["usajobs"] and "unknown source type" in stats["errors"]["nope"]

    rows = {r["id"]: r for r in rows_of(cfg)}
    assert len(rows) == 13 and all(r["state"] == "discovered" for r in rows.values())
    gh = rows["example-labs:greenhouse:4012345"]
    assert gh["source"] == "greenhouse" and gh["family"] == "ds" and gh["req_id"] == "greenhouse:4012345"
    assert gh["portal"] == "greenhouse" and gh["content_hash"]
    li = rows["example-labs:linkedin:3901234567"]
    assert li["source"] == "alerts" and li["url"] == "https://www.linkedin.com/jobs/view/3901234567/"
    assert rows["initech:ashby:5f0c1e2d-1111-4222-8333-444455556666"]["family"] == "ds"
    assert rows["umbrella-analytics:workable:ab12cd34ef"]["family"] == "analytics"
    assert {r["source"] for r in rows.values()} == {"greenhouse", "lever", "ashby", "workable", "smartrecruiters",
                                                     "recruitee", "remotive", "careers-pages", "alerts"}

    cached = discover.load_posting(ws, "example-labs:greenhouse:4012345")
    assert cached.title == "Data Scientist" and "forecasting models" in cached.text
    assert cached.salary_min == 55000 and cached.extra["source_name"] == "greenhouse"
    f = discover.posting_path(ws, "example-labs:greenhouse:4012345")
    assert f.parent == ws / "postings" and f.name == "example-labs_greenhouse_4012345.json"
    assert json.loads(f.read_text(encoding="utf-8"))["id"] == "example-labs:greenhouse:4012345"
    assert len(list((ws / "postings").glob("*.json"))) == 13


def test_run_is_idempotent(ws):
    cfg = make_cfg(ws)
    discover.run(cfg, Http(fixtures=FIX))
    again = discover.run(cfg, Http(fixtures=FIX))
    assert again["new"] == 0 and again["fetched"] == 21
    assert len(rows_of(cfg)) == 13


def test_run_only_filters_by_name_or_type(ws):
    cfg = make_cfg(ws)
    stats = discover.run(cfg, Http(fixtures=FIX), only=["lever", "careers-pages"])
    assert set(stats["by_source"]) == {"lever", "careers-pages"} and stats["errors"] == {}
    stats = discover.run(cfg, Http(fixtures=FIX), only=["jsonld"])
    assert set(stats["by_source"]) == {"careers-pages"}


def test_run_dedupes_same_id_across_sources(ws):
    cfg = make_cfg(ws, sources=[{"type": "greenhouse", "board": "examplelabs"},
                                {"type": "greenhouse", "board": "examplelabs", "name": "gh-mirror"}])
    stats = discover.run(cfg, Http(fixtures=FIX))
    assert stats["new"] == 2 and stats["filtered"] == {"seniority:director": 2, "duplicate": 2}
    assert stats["by_source"] == {"greenhouse": 3, "gh-mirror": 3}


class FakeSource(base.Source):
    name = "fake"
    postings: list[Posting] = []

    def fetch(self, spec, http):
        return [Posting(**{**p.__dict__}) for p in self.postings]


def test_run_dedupes_by_content_hash(ws, monkeypatch):
    monkeypatch.setitem(base.REGISTRY, "fake", FakeSource)
    text = "Build forecasting models for grid operators."
    FakeSource.postings = [
        P(url="https://a.example.com/jobs/1", text=text),
        P(url="https://careers.example.com/data-scientist", text=text),   # same job via another site
        P(url="https://a.example.com/jobs/2", title="Data Analyst"),       # no text: never hash-deduped
        P(url="https://a.example.com/jobs/3", title="Data Analyst"),
    ]
    cfg = make_cfg(ws, sources=[{"type": "fake"}])
    stats = discover.run(cfg, None)
    assert stats["new"] == 3 and stats["filtered"] == {"duplicate": 1}
    # A later run that sees the same text under yet another URL is still a duplicate of the queued job.
    FakeSource.postings = [P(url="https://b.example.com/x", text=text)]
    assert discover.run(cfg, None)["filtered"] == {"duplicate": 1}


def test_run_records_source_errors_and_continues(ws, monkeypatch):
    class Boom(base.Source):
        name = "boom"

        def fetch(self, spec, http):
            raise RuntimeError("board offline")
    monkeypatch.setitem(base.REGISTRY, "boom", Boom)
    cfg = make_cfg(ws, sources=[{"type": "boom"}, {"type": "recruitee", "board": "vandelay"}])
    stats = discover.run(cfg, Http(fixtures=FIX))
    assert stats["errors"] == {"boom": "RuntimeError: board offline"}
    assert stats["new"] == 1 and stats["by_source"] == {"boom": 0, "recruitee": 1}


def test_run_drops_invalid_postings(ws, monkeypatch):
    monkeypatch.setitem(base.REGISTRY, "fake", FakeSource)
    FakeSource.postings = [P(title=""), P(url="")]
    stats = discover.run(make_cfg(ws, sources=[{"type": "fake"}]), None)
    assert stats["filtered"] == {"invalid": 2} and stats["new"] == 0


def test_run_applies_flagship_config(ws):
    cfg = make_cfg(ws, sources=[{"type": "recruitee", "board": "vandelay"}],
                   flagship_employers=["Vandelay Industries"])
    discover.run(cfg, Http(fixtures=FIX))
    row = rows_of(cfg)[0]
    assert row["flagship"] == 1 and queue.FULL_MIN == 75


def test_posting_id_matches_queue_rules():
    p = Posting(source="greenhouse", employer="Example Labs", title="Data Scientist",
                url="https://boards.greenhouse.io/examplelabs/jobs/4012345", req_id="4012345")
    assert discover.posting_id(p) == "example-labs:greenhouse:4012345"
    p2 = Posting(source="ashby", employer="Initech", title="X", url="https://jobs.ashbyhq.com/initech/abc", req_id="ABC")
    assert discover.posting_id(p2) == "initech:ashby:abc"
    p3 = Posting(source="jsonld", employer="Globex", title="Analyst", url="https://careers.globex.example/jobs/77")
    assert discover.posting_id(p3).startswith("globex:h")
