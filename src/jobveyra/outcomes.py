"""Outcomes ledger: what employers did after an application went out.

The queue tracks *submission* (a job reaches ``submitted`` only with confirmation text); this
ledger tracks the *employer's response* afterwards. The two are kept apart on purpose: a
rejection does not change a queue state, and a job can collect several outcomes over time
(reply, then screen, then interview, then offer).

Storage: ``state/outcomes.jsonl``, append-only, one record per line::

    {"job_id": "...", "at": "2026-03-02T10:00:00", "outcome": "screen", "stage_note": "..."}

Times are ISO 8601. Records written here are naive UTC (the same convention as the queue);
records with an offset or a trailing ``Z`` are read and converted to naive UTC.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

OUTCOMES = ("no_reply", "reply", "screen", "interview", "assessment", "offer", "rejected", "withdrawn", "hired")
# Any response from the employer (a rejection is a reply; withdrawing is the candidate's act).
REPLY = frozenset({"reply", "screen", "interview", "assessment", "offer", "rejected", "hired"})
# A positive response: the employer moved the candidate forward.
POSITIVE = frozenset({"screen", "interview", "assessment", "offer", "hired"})
INTERVIEW = frozenset({"interview", "offer", "hired"})
OFFER = frozenset({"offer", "hired"})
FILE_NAME = "outcomes.jsonl"


def parse_time(value) -> dt.datetime | None:
    """ISO date or datetime (str, date or datetime) -> naive UTC datetime; None when unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        t = value
    elif isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day)
    else:
        s = str(value).strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        try:
            t = dt.datetime.fromisoformat(s)
        except ValueError:
            try:
                d = dt.date.fromisoformat(s[:10])
            except ValueError:
                return None
            return dt.datetime(d.year, d.month, d.day)
    if t.tzinfo is not None:
        t = t.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return t


def as_date(value) -> dt.date | None:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    t = parse_time(value)
    return t.date() if t else None


def _path(state_dir) -> Path:
    return Path(state_dir) / FILE_NAME


def record(state_dir, job_id: str, outcome: str, note: str = "", at=None) -> dict:
    """Append one outcome and return the stored record. ``at`` defaults to now (UTC)."""
    if not (job_id or "").strip():
        raise ValueError("record() needs a job id")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome {outcome!r} is not one of {', '.join(OUTCOMES)}")
    if at is None:
        from . import queue
        t = queue.now()
    else:
        t = parse_time(at)
        if t is None:
            raise ValueError(f"at={at!r} is not an ISO date or datetime")
    rec = {"job_id": job_id, "at": t.isoformat(timespec="seconds"), "outcome": outcome, "stage_note": note or ""}
    p = _path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return rec


def load(state_dir) -> list[dict]:
    """Every valid record, oldest first (file order breaks ties). Malformed lines are skipped."""
    p = _path(state_dir)
    if not p.is_file():
        return []
    out = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict) or d.get("outcome") not in OUTCOMES or not d.get("job_id"):
            continue
        t = parse_time(d.get("at"))
        if t is None:
            continue
        d.setdefault("stage_note", "")
        d["_order"] = i
        out.append(d)
    out.sort(key=lambda r: (parse_time(r["at"]), r["_order"]))
    for d in out:
        d.pop("_order", None)
    return out


def latest(outcomes: list[dict]) -> dict[str, dict]:
    """job_id -> its most recent record (by ``at``; the later record wins a tie)."""
    best: dict[str, tuple] = {}
    for i, r in enumerate(outcomes):
        t = parse_time(r.get("at")) or dt.datetime.min
        key = (t, i)
        if r["job_id"] not in best or key >= best[r["job_id"]][0]:
            best[r["job_id"]] = (key, r)
    return {k: v[1] for k, v in best.items()}


def by_job(outcomes: list[dict]) -> dict[str, list[dict]]:
    """job_id -> its records, oldest first."""
    out: dict[str, list[dict]] = {}
    for r in sorted(outcomes, key=lambda r: parse_time(r.get("at")) or dt.datetime.min):
        out.setdefault(r["job_id"], []).append(r)
    return out


def reached(records: list[dict], kinds) -> bool:
    """True when any record of one job is in ``kinds`` (e.g. REPLY, POSITIVE, INTERVIEW)."""
    return any(r.get("outcome") in kinds for r in records)


def submitted_at(job: dict) -> dt.datetime | None:
    """When a queue row was submitted: ``submitted_at`` when present (reports add it from the
    event log), else ``updated_at`` of a submitted row (the queue's last write to it)."""
    t = parse_time(job.get("submitted_at"))
    if t is None and job.get("state") == "submitted":
        t = parse_time(job.get("updated_at"))
    return t


def submission_times(state_dir) -> dict[str, str]:
    """job id -> timestamp of its transition to ``submitted`` in ``events.jsonl`` (first one wins)."""
    p = Path(state_dir) / "events.jsonl"
    out: dict[str, str] = {}
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict) and e.get("to") == "submitted" and e.get("id") and e.get("ts"):
            out.setdefault(e["id"], e["ts"])
    return out


def first_at(records: list[dict], kinds) -> dt.datetime | None:
    ts = [parse_time(r.get("at")) for r in records if r.get("outcome") in kinds]
    ts = [t for t in ts if t]
    return min(ts) if ts else None
