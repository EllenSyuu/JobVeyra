"""Plain data behind the dashboard pages and its JSON API, plus the actions it may record.

Every function takes a ``Config`` and a ``Queue`` and returns plain data (dicts, lists, str).
The actions here only record decisions the candidate made: an employer response, a hold, a
release, the result of a manual check, a staged batch, an approval or a withdrawal of one.
Nothing in this module submits an application, opens a browser or touches credentials.
"""
from __future__ import annotations

import dataclasses as dc
import json
import re
from pathlib import Path

from .. import approvals, discover
from .. import outcomes as oc
from .. import queue as qmod
from ..analytics import skills
from ..analytics.calibration import calibrate
from ..analytics.funnel import funnel
from ..analytics.patterns import MIN_N as PATTERNS_MIN_N
from ..analytics.patterns import patterns
from ..report import digest

JOB_FIELDS = ("id", "employer", "title", "state", "reason", "action", "fit", "lane", "family", "source",
              "portal", "auth_scope", "location", "posted", "deadline", "url", "apply_url", "package", "req_id",
              "lang", "flagship", "attempts", "last_error", "next_attempt_at", "confirmation", "content_hash",
              "created_at", "updated_at", "submitted_at")
MAX_ID = 300
MAX_TEXT = 1000
# vocabulary terms that are ordinary English words once lower-cased; they would count every posting
AMBIGUOUS_TERMS = {"go", "rest"}
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class ActionError(Exception):
    """A refused action: ``status`` is the HTTP status the server answers with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def today(cfg=None):
    return qmod.now().date()


def fit_of(j: dict) -> int | None:
    try:
        return int(round(float(j["fit"]))) if j.get("fit") not in (None, "") else None
    except (TypeError, ValueError):
        return None


def track_labels(cfg) -> dict[str, str]:
    return {t.key: t.label for t in cfg.focus.tracks}


def job_row(j: dict, labels: dict[str, str] | None = None) -> dict:
    row = {k: j.get(k) for k in JOB_FIELDS if j.get(k) not in (None, "")}
    row["id"] = j["id"]
    row["state"] = j.get("state") or ""
    row["fit"] = fit_of(j)
    fam = j.get("family") or ""
    row["track"] = fam
    row["track_label"] = (labels or {}).get(fam, fam)
    row["flagship"] = bool(int(float(j.get("flagship") or 0)))
    return row


def jobs(cfg, q) -> list[dict]:
    labels = track_labels(cfg)
    return [job_row(j, labels) for j in digest._jobs(q)]


def evaluation(cfg, jid: str) -> tuple[dict | None, str]:
    base = cfg.workspace / "reports" / "evaluations" / discover.safe_id(jid)
    ev, md = None, ""
    try:
        ev = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ev = None
    try:
        md = base.with_suffix(".md").read_text(encoding="utf-8")
    except OSError:
        md = ""
    return ev, md


def evaluations(cfg) -> dict[str, dict]:
    out: dict[str, dict] = {}
    d = cfg.workspace / "reports" / "evaluations"
    if d.is_dir():
        for f in d.glob("*.json"):
            try:
                ev = json.loads(f.read_text(encoding="utf-8"))
                out[ev["job_id"]] = ev
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return out


def events_for(state_dir: Path, jid: str) -> list[dict]:
    p = Path(state_dir) / "events.jsonl"
    out = []
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("id") == jid:
            out.append({"ts": e.get("ts", ""), "from": e.get("from", ""), "to": e.get("to", ""),
                        "note": e.get("note", "")})
    return out


def posting(cfg, jid: str) -> dict | None:
    try:
        p = discover.load_posting(cfg.workspace, jid)
    except (OSError, ValueError, TypeError):
        return None
    return dc.asdict(p) if p else None


def job_detail(cfg, q, jid: str) -> dict | None:
    j = q.get(jid)
    if not j:
        return None
    times = oc.submission_times(q.dir)
    if j.get("state") == "submitted" and not j.get("submitted_at") and jid in times:
        j = {**j, "submitted_at": times[jid]}
    ev, md = evaluation(cfg, jid)
    ok, why = approvals.allowed(j, cfg)
    return {
        "job": job_row(j, track_labels(cfg)),
        "evaluation": ev,
        "evaluation_markdown": md,
        "posting": posting(cfg, jid),
        "events": events_for(q.dir, jid),
        "outcomes": [r for r in oc.load(q.dir) if r["job_id"] == jid],
        "submission": {"policy": cfg.policy.submission, "allowed": ok, "why": why},
        "actions": available_actions(j),
    }


def available_actions(j: dict) -> list[str]:
    st = j.get("state") or ""
    acts = []
    if st == "submitted":
        acts.append("outcome")
    if any(b in qmod.TRANSITIONS.get(st, ()) for b in qmod.BLOCKED) or st in qmod.BLOCKED:
        acts.append("block")
    if st in qmod.BLOCKED or st == "blocked":
        acts.append("unblock")
    if st == "needs_check":
        acts.append("check")
    return acts


def skill_view(cfg, job_rows: list[dict], *, top: int = 20) -> dict:
    from ..evaluate.rubric import VOCAB
    held = sorted({s for t in cfg.focus.tracks for s in t.skills})
    vocab = list(dict.fromkeys([*held, *(v for v in VOCAB if v not in AMBIGUOUS_TERMS)]))
    texts = []
    for j in job_rows:
        try:
            p = discover.load_posting(cfg.workspace, j["id"])
        except (OSError, ValueError, TypeError):
            p = None
        if p and p.text:
            texts.append(p.text)
    rows = [r for r in skills.demand(texts, vocab) if r[1] > 0]
    held_terms = set()
    for s in held:
        held_terms.update(skills._variants(s)[1])
    demand = [{"term": t, "postings": n, "held": bool(held_terms.intersection(skills._variants(t)[1]))}
              for t, n in rows[:top]]
    gaps = [{"term": t, "postings": n} for t, n in skills.gaps(rows, held, top=top)]
    return {"postings": len(texts), "demand": demand, "gaps": gaps, "held": held}


def insights(cfg, q) -> dict:
    js = digest._jobs(q)
    outs = oc.load(q.dir)
    return {
        "funnel": funnel(js, outs),
        "patterns": patterns(js, outs),
        "patterns_min_n": PATTERNS_MIN_N,
        "calibration": calibrate(js, outs, exclude_below=cfg.policy.exclude_below),
        "skills": skill_view(cfg, js),
    }


def digest_view(cfg, q) -> dict:
    dg = digest.build(cfg, q, today(cfg))
    open_jobs = [j for j in q.all() if j.get("state") in ("needs_check", "blocked_human", "blocked_technical")]
    labels = track_labels(cfg)
    dg["attention"] = {
        st: [job_row(j, labels) for j in open_jobs if j.get("state") == st]
        for st in ("needs_check", "blocked_human", "blocked_technical")
    }
    dg["policy"] = {"submission": cfg.policy.submission, "batch_size": cfg.policy.batch_size,
                    "approval_ttl_hours": cfg.policy.approval_ttl_hours}
    return dg


# ---------------------------------------------------------------- review and approvals

def _item_rows(q, items) -> list[dict]:
    out = []
    for jid, h in items:
        j = q.get(jid) or {}
        out.append({"id": jid, "hash": h, "current_hash": j.get("content_hash") or "",
                    "changed": bool(j) and (j.get("content_hash") or "") != h, "missing": not j,
                    "employer": j.get("employer", ""), "title": j.get("title", ""), "state": j.get("state", ""),
                    "fit": fit_of(j) if j else None, "url": j.get("apply_url") or j.get("url") or ""})
    return out


def review(cfg, q) -> dict:
    state = cfg.state_dir
    t = qmod.now()
    recs = approvals.records(state)
    approved = {r["batch"] for r in recs if r.get("type") == "approved"}
    revoked = {r["batch"] for r in recs if r.get("type") == "revoked"}
    live = approvals.live(state, t)
    covered = {jid for rec in live for jid, _h in rec["items"]}
    staged = []
    for r in recs:
        if r.get("type") != "staged" or r["batch"] in approved or r["batch"] in revoked:
            continue
        page = cfg.workspace / "reports" / f"review-{r['batch']}.html"
        staged.append({"batch": r["batch"], "at": r.get("at", ""), "items": _item_rows(q, r.get("items", [])),
                       "review_page": str(page) if page.is_file() else ""})
    staged.reverse()
    live_rows = [{"batch": r["batch"], "at": r.get("at", ""), "by": r.get("by", ""), "expires": r.get("expires", ""),
                  "items": _item_rows(q, r["items"])} for r in reversed(live)]
    live_ids = {r["batch"] for r in live}
    history = [{"type": r.get("type"), "batch": r.get("batch"), "at": r.get("at", ""), "by": r.get("by", ""),
                "expires": r.get("expires", ""), "n": len(r.get("items", []))}
               for r in recs if r.get("type") in ("approved", "revoked")]
    history = [h for h in reversed(history)][:20]
    ready = q.all("ready_to_submit")
    return {
        "policy": {"submission": cfg.policy.submission, "batch_size": cfg.policy.batch_size,
                   "approval_ttl_hours": cfg.policy.approval_ttl_hours, "max_per_day": cfg.policy.max_per_day},
        "ready": len(ready),
        "ready_uncovered": sum(1 for j in ready if j["id"] not in covered),
        "staged": staged,
        "live": live_rows,
        "live_batches": sorted(live_ids),
        "history": history,
    }


# ---------------------------------------------------------------- actions (record decisions only)

def _text(body: dict, key: str, *, required: bool = False, limit: int = MAX_TEXT) -> str:
    v = body.get(key, "")
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ActionError(400, f"{key} must be text")
    v = v.strip()
    if required and not v:
        raise ActionError(400, f"{key} is required")
    if len(v) > limit:
        raise ActionError(400, f"{key} is longer than {limit} characters")
    if CONTROL.search(v):
        raise ActionError(400, f"{key} contains control characters")
    return v


def _job(q, body: dict) -> dict:
    jid = _text(body, "id", required=True, limit=MAX_ID)
    j = q.get(jid)
    if not j:
        raise ActionError(404, f"unknown job {jid}")
    return j


def _flag(body: dict, key: str) -> bool:
    v = body.get(key)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v or "").strip().lower()
    if s in ("1", "true", "yes", "found", "on"):
        return True
    if s in ("0", "false", "no", "not_found", "off", ""):
        return False
    raise ActionError(400, f"{key} must be true or false")


def act_outcome(cfg, q, body: dict) -> dict:
    j = _job(q, body)
    kind = _text(body, "outcome", required=True, limit=40)
    if kind not in oc.OUTCOMES:
        raise ActionError(400, f"outcome must be one of {', '.join(oc.OUTCOMES)}")
    rec = oc.record(cfg.state_dir, j["id"], kind, _text(body, "note"))
    return {"recorded": rec}


def act_block(cfg, q, body: dict) -> dict:
    j = _job(q, body)
    reason = _text(body, "reason", required=True, limit=200)
    if re.search(r"\s", reason.split(":", 1)[0]):
        raise ActionError(400, "reason starts with a code such as hold:, auth:<portal> or captcha")
    try:
        return {"id": j["id"], "state": q.block(j["id"], reason)}
    except ValueError as e:
        raise ActionError(409, str(e)) from None


def act_unblock(cfg, q, body: dict) -> dict:
    portal = _text(body, "portal", limit=200)
    if body.get("id"):
        j = _job(q, body)
        if j["state"] not in qmod.BLOCKED + ("blocked",):
            raise ActionError(409, f"{j['id']} is {j['state']}, not blocked")
        return {"unblocked": q.unblock(jid=j["id"])}
    if not portal:
        raise ActionError(400, "id or portal is required")
    scopes = {q.scope(j) for j in q.all() if j["state"] in qmod.BLOCKED} | \
             {j.get("portal") for j in q.all() if j["state"] in qmod.BLOCKED}
    if portal not in scopes:
        raise ActionError(404, f"no blocked job on {portal}")
    return {"unblocked": q.unblock(portal=portal)}


def act_check(cfg, q, body: dict) -> dict:
    j = _job(q, body)
    if j["state"] != "needs_check":
        raise ActionError(409, f"{j['id']} is {j['state']}, not needs_check")
    found = _flag(body, "found")
    evidence = _text(body, "evidence", limit=500)
    state = q.resolve_check(j["id"], found_on_portal=found, evidence=evidence)
    return {"id": j["id"], "state": state}


def _require_batch_policy(cfg) -> None:
    if cfg.policy.submission != "batch_approve":
        raise ActionError(409, f"policy.submission is {cfg.policy.submission}: batch approvals are not used")


def act_stage(cfg, q, body: dict) -> dict:
    _require_batch_policy(cfg)
    batch = approvals.stage(q, cfg)
    if not batch:
        return {"batch": None, "message": "nothing waiting for review"}
    page = approvals.review_page(batch, cfg, evaluations(cfg))
    return {"batch": batch.id, "jobs": [j["id"] for j in batch.jobs], "review_page": str(page)}


def _batch_id(body: dict) -> str:
    bid = _text(body, "batch", required=True, limit=64)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", bid):
        raise ActionError(400, "batch id has unexpected characters")
    return bid


def act_approve(cfg, q, body: dict) -> dict:
    _require_batch_policy(cfg)
    bid = _batch_id(body)
    try:
        items = approvals.get_batch(cfg.state_dir, bid)
    except KeyError:
        raise ActionError(404, f"no staged batch {bid}") from None
    recs = approvals.records(cfg.state_dir)
    if any(r.get("batch") == bid and r.get("type") == "revoked" for r in recs):
        raise ActionError(409, f"batch {bid} was revoked; stage a new one")
    exclude = body.get("exclude") or []
    if isinstance(exclude, str):
        exclude = [x for x in re.split(r"[\s,]+", exclude) if x]
    if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
        raise ActionError(400, "exclude must be a list of job ids")
    ids = {jid for jid, _h in items}
    unknown = [x for x in exclude if x not in ids]
    if unknown:
        raise ActionError(400, f"not in batch {bid}: {', '.join(unknown)}")
    by = cfg.candidate.name or "candidate"
    try:
        approvals.approve(cfg.state_dir, bid, by=by, ttl_hours=cfg.policy.approval_ttl_hours,
                          exclude=tuple(exclude))
    except ValueError as e:
        raise ActionError(409, str(e)) from None
    return {"batch": bid, "approved": len(ids) - len(set(exclude)), "excluded": sorted(set(exclude)),
            "hours": cfg.policy.approval_ttl_hours}


def act_revoke(cfg, q, body: dict) -> dict:
    bid = _batch_id(body)
    if not any(r.get("batch") == bid for r in approvals.records(cfg.state_dir)):
        raise ActionError(404, f"no batch {bid}")
    approvals.revoke(cfg.state_dir, bid)
    return {"revoked": bid}


ACTIONS = {"outcome": act_outcome, "block": act_block, "unblock": act_unblock, "check": act_check,
           "stage": act_stage, "approve": act_approve, "revoke": act_revoke}
