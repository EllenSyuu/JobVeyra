import pytest

from jobveyra import outcomes as oc
from jobveyra import queue as qmod
from jobveyra.analytics import calibrate, calibration, demand, funnel, gaps, patterns, wilson
from jobveyra.analytics.calibration import auc


def job(i, state="submitted", **kw):
    d = {"id": f"example-labs:ref:{i:04d}", "employer": "Example Labs", "title": f"Data Scientist {i}",
         "state": state, "source": "greenhouse", "portal": "greenhouse", "family": "ds", "lane": "fast",
         "flagship": 0, "fit": 60, "updated_at": "2026-03-01T09:00:00"}
    d.update(kw)
    return d


def out(jid, outcome, at="2026-03-05T09:00:00"):
    return {"job_id": jid, "outcome": outcome, "at": at, "stage_note": ""}


# ---------------------------------------------------------------- funnel

def test_funnel_counts_rates_and_median():
    jobs = [job(1), job(2), job(3), job(4),
            job(5, state="eligible"), job(6, state="excluded"), job(7, state="discovered"),
            job(8, state="blocked_auth")]
    outs = [out(jobs[0]["id"], "reply", "2026-03-03T09:00:00"), out(jobs[0]["id"], "interview", "2026-03-10T09:00:00"),
            out(jobs[1]["id"], "rejected", "2026-03-05T09:00:00"),
            out(jobs[2]["id"], "screen", "2026-03-11T09:00:00"), out(jobs[2]["id"], "offer", "2026-03-20T09:00:00"),
            out(jobs[3]["id"], "no_reply", "2026-03-15T09:00:00"),
            out("globex:ref:9999", "reply")]
    f = funnel(jobs, outs)
    assert f["counts"] == {"discovered": 8, "eligible": 6, "submitted": 4, "reply": 3, "interview": 2, "offer": 1}
    assert f["conversion"]["reply_rate"] == 0.75
    assert f["conversion"]["offer_per_interview"] == 0.5
    assert [s["stage"] for s in f["stages"]] == list(("discovered", "eligible", "submitted", "reply", "interview", "offer"))
    assert f["stages"][3]["from_previous"] == 0.75
    assert f["median_days_to_reply"] == 4.0                 # 2, 4, 10 days
    assert f["unmatched_outcomes"] == 1


def test_funnel_empty():
    f = funnel([], [])
    assert f["counts"]["discovered"] == 0 and f["median_days_to_reply"] is None
    assert f["conversion"]["reply_rate"] is None


def test_funnel_with_real_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBQUEUE_NOW", "2026-03-01T09:00:00")
    q = qmod.Queue(tmp_path / "state")
    a, _ = q.upsert({"employer": "Example Labs", "title": "Data Analyst", "url": "https://boards.greenhouse.io/examplelabs/jobs/111",
                     "source": "greenhouse", "family": "analytics"})
    b, _ = q.upsert({"employer": "Globex", "title": "Data Scientist", "url": "https://jobs.lever.co/globex/" + "1" * 36})
    q.screen(a, 72)
    q.screen(b, 30)
    q.mark_submitted(a, "Thank you for applying")
    oc.record(q.dir, a, "reply", at="2026-03-04T09:00:00")
    f = funnel(q.all(), oc.load(q.dir))
    assert f["counts"]["submitted"] == 1 and f["counts"]["reply"] == 1 and f["counts"]["eligible"] == 1
    assert f["median_days_to_reply"] == 3.0


# ---------------------------------------------------------------- patterns

def test_wilson_known_values():
    lo, hi = wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)
    assert wilson(0, 10)[0] == 0.0


def test_patterns_signals_and_order():
    jobs, outs = [], []
    for i in range(15):
        j = job(i, source="greenhouse")
        jobs.append(j)
        if i < 12:
            outs.append(out(j["id"], "reply"))
    for i in range(15, 30):
        j = job(i, source="lever", portal="lever")
        jobs.append(j)
        if i == 15:
            outs.append(out(j["id"], "rejected"))
    for i in range(30, 33):                                   # small group
        jobs.append(job(i, source="un_careers", portal="inspira", flagship=1))
    jobs.append(job(99, state="eligible", source="remotive"))   # not submitted: ignored
    rows = patterns(jobs, outs)
    by = {(r["dimension"], r["value"]): r for r in rows}
    assert by[("source", "greenhouse")]["signal"] == "above"
    assert by[("source", "lever")]["signal"] == "below"
    assert by[("source", "un_careers")]["signal"] == "insufficient"
    assert ("source", "remotive") not in by
    assert by[("flagship", "yes")]["n"] == 3
    assert not any(r["dimension"] == "seniority" for r in rows)   # no job has it
    assert rows[0]["signal"] != "insufficient"
    sigs = [r["signal"] != "insufficient" for r in rows]
    assert sigs == sorted(sigs, reverse=True)
    g = by[("source", "greenhouse")]
    assert g["low"] > g["overall"] and g["n"] == 15 and g["replied"] == 12


def test_patterns_seniority_when_present_and_empty():
    jobs = [job(i, seniority="junior" if i % 2 else "mid") for i in range(4)]
    assert any(r["dimension"] == "seniority" for r in patterns(jobs, []))
    assert patterns([], []) == []


# ---------------------------------------------------------------- calibration

def test_auc_and_ties():
    assert auc([1, 2, 3, 4], [0, 0, 1, 1]) == 1.0
    assert auc([4, 3, 2, 1], [0, 0, 1, 1]) == 0.0
    assert auc([1, 1], [0, 1]) == 0.5
    assert auc([1, 2], [1, 1]) is None


def _calib_jobs():
    jobs, outs = [], []
    plan = [(50, 0), (60, 3), (70, 5), (80, 8)]                # 10 jobs per bucket, k positives
    i = 0
    for fit, k in plan:
        for m in range(10):
            j = job(i, fit=fit + (m % 5))
            jobs.append(j)
            if m < k:
                outs.append(out(j["id"], "interview" if m % 2 else "screen"))
            elif m == k:
                outs.append(out(j["id"], "rejected"))           # a reply, but not positive
            i += 1
    return jobs, outs


def test_calibration_with_enough_outcomes():
    jobs, outs = _calib_jobs()
    c = calibrate(jobs, outs)
    assert c["n"] == 40 and c["positive"] == 16
    rates = {b["bucket"]: b["rate"] for b in c["buckets"]}
    assert rates == {"<45": None, "45-54": 0.0, "55-64": 0.3, "65-74": 0.5, "75+": 0.8}
    assert c["monotonic"] is True
    assert c["auc"] > 0.75
    assert 0 < c["brier"] < 0.5
    assert "raise policy.exclude_below from 45 to 55" in c["recommendation"]
    assert calibration is calibrate


def test_calibration_not_enough_and_brier_extremes():
    jobs = [job(1, fit=100), job(2, fit=0), job(3, state="eligible", fit=90), job(4, fit=None)]
    c = calibrate(jobs, [out(jobs[0]["id"], "offer")])
    assert c["n"] == 2 and c["brier"] == 0.0 and c["auc"] == 1.0
    assert c["recommendation"].startswith("not enough outcomes yet")


def test_calibration_flags_non_monotonic():
    jobs, outs = _calib_jobs()
    flipped = [dict(j, fit=129 - float(j["fit"])) for j in jobs]   # high fit now responds least
    c = calibrate(flipped, outs)
    assert c["monotonic"] is False
    assert "does not rise steadily" in c["recommendation"] and "AUC" in c["recommendation"]


# ---------------------------------------------------------------- skills

def test_demand_boundaries_accents_synonyms():
    texts = ["We use Python and SQL daily. R is a plus.",
             "Experience with ML and statistical modelling; NoSQL stores.",
             "R&D team, React front end, Python scripting.",
             "Analyse de données, modélisation, Python.",
             "Machine   learning pipelines and C++."]
    vocab = ["Python", "SQL", "R", "machine learning", "statistics", "modelisation", "C", "Excel|spreadsheets"]
    d = dict(demand(texts, vocab))
    assert d["Python"] == 3
    assert d["SQL"] == 1                                     # not NoSQL
    assert d["R"] == 1                                       # not R&D, not React
    assert d["machine learning"] == 2                        # "ML" and spaced form
    assert d["statistics"] == 1                              # via "statistical"
    assert d["modelisation"] == 1                            # accent-insensitive
    assert d["C"] == 0                                       # not C++
    assert d["Excel"] == 0
    rows = demand(texts, vocab)
    assert rows[0] == ("Python", 3)
    assert [c for _, c in rows] == sorted((c for _, c in rows), reverse=True)


def test_gaps():
    rows = [("Python", 9), ("machine learning", 6), ("SQL", 5), ("Spark", 2), ("Fortran", 0)]
    assert gaps(rows, ["python", "ML", "sql"]) == [("Spark", 2)]
    assert gaps(rows, ["Python"], min_count=3) == [("machine learning", 6), ("SQL", 5)]
    assert gaps(rows, [], top=2) == [("Python", 9), ("machine learning", 6)]
