import json

import pytest

from jobveyra import outcomes as oc


def test_record_and_load_roundtrip(tmp_path):
    st = tmp_path / "state"
    r = oc.record(st, "example-labs:ref:1001", "reply", "recruiter email", at="2026-03-04T10:00:00")
    assert r == {"job_id": "example-labs:ref:1001", "at": "2026-03-04T10:00:00", "outcome": "reply",
                 "stage_note": "recruiter email"}
    oc.record(st, "example-labs:ref:1001", "screen", at="2026-03-06")
    rows = oc.load(st)
    assert [x["outcome"] for x in rows] == ["reply", "screen"]
    assert rows[1]["at"] == "2026-03-06T00:00:00"
    assert (st / "outcomes.jsonl").read_text().count("\n") == 2


def test_record_defaults_to_queue_clock(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBQUEUE_NOW", "2026-05-01T08:30:00")
    r = oc.record(tmp_path, "globex:ref:7", "no_reply")
    assert r["at"] == "2026-05-01T08:30:00"


def test_record_rejects_unknown_outcome_and_bad_time(tmp_path):
    with pytest.raises(ValueError, match="not one of"):
        oc.record(tmp_path, "x", "ghosted")
    with pytest.raises(ValueError):
        oc.record(tmp_path, "x", "reply", at="yesterday-ish")
    with pytest.raises(ValueError):
        oc.record(tmp_path, "", "reply")


def test_load_skips_malformed_and_sorts_by_time(tmp_path):
    p = tmp_path / "outcomes.jsonl"
    p.write_text("\n".join([
        json.dumps({"job_id": "a", "at": "2026-03-05T00:00:00", "outcome": "interview"}),
        "not json",
        json.dumps({"job_id": "a", "at": "2026-03-01T00:00:00Z", "outcome": "reply"}),
        json.dumps({"job_id": "b", "at": "2026-03-02", "outcome": "made_up"}),
        json.dumps({"job_id": "c", "at": "2026-03-03T12:00:00+02:00", "outcome": "rejected"}),
    ]) + "\n")
    rows = oc.load(tmp_path)
    assert [(r["job_id"], r["outcome"]) for r in rows] == [("a", "reply"), ("c", "rejected"), ("a", "interview")]
    assert rows[0]["stage_note"] == ""
    assert oc.parse_time(rows[1]["at"]).hour == 10          # converted to UTC


def test_load_missing_file(tmp_path):
    assert oc.load(tmp_path / "nope") == []


def test_latest_picks_most_recent_and_later_on_tie():
    rows = [{"job_id": "a", "at": "2026-03-01T00:00:00", "outcome": "reply"},
            {"job_id": "a", "at": "2026-03-09T00:00:00", "outcome": "offer"},
            {"job_id": "a", "at": "2026-03-04T00:00:00", "outcome": "interview"},
            {"job_id": "b", "at": "2026-03-02T00:00:00", "outcome": "screen"},
            {"job_id": "b", "at": "2026-03-02T00:00:00", "outcome": "rejected"}]
    lt = oc.latest(rows)
    assert lt["a"]["outcome"] == "offer"
    assert lt["b"]["outcome"] == "rejected"


def test_stage_sets():
    assert "rejected" in oc.REPLY and "rejected" not in oc.POSITIVE
    assert "withdrawn" not in oc.REPLY and "no_reply" not in oc.REPLY
    assert oc.OFFER <= oc.INTERVIEW <= oc.POSITIVE <= oc.REPLY


def test_submitted_at_and_event_log(tmp_path):
    assert oc.submitted_at({"state": "submitted", "updated_at": "2026-03-01T09:00:00"}).day == 1
    assert oc.submitted_at({"state": "submitted", "submitted_at": "2026-02-20T09:00:00",
                            "updated_at": "2026-03-01T09:00:00"}).day == 20
    assert oc.submitted_at({"state": "eligible", "updated_at": "2026-03-01T09:00:00"}) is None
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"ts": "2026-03-01T09:00:00", "id": "a", "from": "eligible", "to": "submitted"}) + "\n"
        + json.dumps({"ts": "2026-03-02T09:00:00", "id": "b", "from": "", "to": "discovered"}) + "\n")
    assert oc.submission_times(tmp_path) == {"a": "2026-03-01T09:00:00"}
