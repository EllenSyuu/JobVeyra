"""Batch approval: the gate between a prepared application and the Submit button.

``policy.submission`` decides how far automation goes:

  auto           every job that passed the gates may be submitted
  batch_approve  a person reviews one page listing a batch, approves it once, and every job
                 on that page may then be submitted until the approval expires
  fill_only      forms are filled but never submitted; the person presses Submit

An approval is a token: an HMAC over the batch's job ids *and* each job's content hash,
signed with a per-workspace secret. If a posting changes after review (new text, new hash)
its approval no longer applies, so nobody approves one thing and submits another.

Ledger: ``state/approvals.jsonl`` (one line per staged batch and per approval).
"""
from __future__ import annotations

import dataclasses as dc
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import secrets
from pathlib import Path

from . import queue as jq

READY = ("ready_to_submit", "eligible")


@dc.dataclass
class Batch:
    id: str
    created_at: str
    jobs: list[dict]                 # queue rows at staging time

    @property
    def items(self) -> list[tuple[str, str]]:
        return [(j["id"], j.get("content_hash") or "") for j in self.jobs]


def _ledger(state: Path) -> Path:
    return state / "approvals.jsonl"


def _key(state: Path) -> bytes:
    p = state / ".approval_key"
    if not p.exists():
        state.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32), encoding="utf-8")
        os.chmod(p, 0o600)
    return bytes.fromhex(p.read_text(encoding="utf-8").strip())


def _sign(state: Path, items: list[tuple[str, str]], expires: str) -> str:
    msg = json.dumps({"items": sorted(items), "expires": expires}, sort_keys=True).encode()
    return hmac.new(_key(state), msg, hashlib.sha256).hexdigest()


def _append(state: Path, rec: dict) -> None:
    state.mkdir(parents=True, exist_ok=True)
    with _ledger(state).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


def records(state: Path) -> list[dict]:
    p = _ledger(state)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def stage(q: jq.Queue, cfg, *, now: dt.datetime | None = None) -> Batch | None:
    """Pick up to batch_size jobs that are ready and not already covered by a live approval."""
    t = now or jq.now()
    covered = {jid for rec in live(cfg.state_dir, t) for jid, _h in rec["items"]}
    pool = [j for j in q.all("ready_to_submit") if j["id"] not in covered]
    pool.sort(key=lambda j: jq.priority(j, t))
    jobs = pool[: cfg.policy.batch_size]
    if not jobs:
        return None
    bid = "b" + t.strftime("%Y%m%d%H%M%S") + secrets.token_hex(2)
    batch = Batch(id=bid, created_at=jq.iso(t), jobs=jobs)
    _append(cfg.state_dir, {"type": "staged", "batch": bid, "at": batch.created_at,
                            "items": [list(i) for i in batch.items]})
    return batch


def get_batch(state: Path, batch_id: str) -> list[tuple[str, str]]:
    for rec in records(state):
        if rec["type"] == "staged" and rec["batch"] == batch_id:
            return [tuple(i) for i in rec["items"]]
    raise KeyError(f"no staged batch {batch_id}")


def approve(state: Path, batch_id: str, *, by: str, ttl_hours: int = 24, exclude: tuple[str, ...] = (),
            now: dt.datetime | None = None) -> str:
    """Approve a staged batch (minus any job ids in `exclude`). Returns the token."""
    t = now or jq.now()
    items = [i for i in get_batch(state, batch_id) if i[0] not in set(exclude)]
    if not items:
        raise ValueError("nothing left to approve in this batch")
    expires = jq.iso(t + dt.timedelta(hours=ttl_hours))
    token = _sign(state, items, expires)
    _append(state, {"type": "approved", "batch": batch_id, "at": jq.iso(t), "by": by, "expires": expires,
                    "items": [list(i) for i in items], "token": token})
    return token


def revoke(state: Path, batch_id: str, *, now: dt.datetime | None = None) -> None:
    _append(state, {"type": "revoked", "batch": batch_id, "at": jq.iso(now or jq.now())})


def live(state: Path, t: dt.datetime | None = None) -> list[dict]:
    """Approvals that are signed correctly, unexpired and not revoked."""
    t = t or jq.now()
    recs = records(state)
    revoked = {r["batch"] for r in recs if r["type"] == "revoked"}
    out = []
    for r in recs:
        if r["type"] != "approved" or r["batch"] in revoked or r["expires"] <= jq.iso(t):
            continue
        items = [tuple(i) for i in r["items"]]
        if hmac.compare_digest(r.get("token", ""), _sign(state, items, r["expires"])):
            out.append({**r, "items": items})
    return out


def allowed(job: dict, cfg, *, now: dt.datetime | None = None) -> tuple[bool, str]:
    """May this job be submitted right now under the configured policy?"""
    mode = cfg.policy.submission
    if mode == "auto":
        return True, "policy: auto"
    if mode == "fill_only":
        return False, "policy: fill_only (the candidate presses Submit)"
    h = job.get("content_hash") or ""
    for rec in live(cfg.state_dir, now):
        for jid, ch in rec["items"]:
            if jid == job["id"]:
                if ch == h:
                    return True, f"approved in batch {rec['batch']} by {rec['by']}"
                return False, "posting changed after approval; review it again"
    return False, "not approved yet: run `jobveyra review` then `jobveyra approve`"


def review_page(batch: Batch, cfg, evaluations: dict[str, dict] | None = None) -> Path:
    """A static HTML page for one batch: what will be sent, where, and why it qualified."""
    ev = evaluations or {}
    out = cfg.workspace / "reports" / f"review-{batch.id}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    e = lambda s: html.escape(str(s or ""), quote=True)  # noqa: E731
    rows = []
    for j in batch.jobs:
        x = ev.get(j["id"], {})
        flags = ", ".join(x.get("flags", []) + x.get("blockers", [])) or "none"
        rows.append(
            f"<tr><td><b>{e(j.get('employer'))}</b><br>{e(j.get('title'))}<br>"
            f"<a href=\"{e(j.get('apply_url') or j.get('url'))}\">{e(j.get('apply_url') or j.get('url'))}</a></td>"
            f"<td>{e(j.get('location'))}</td><td>{int(float(j.get('fit') or 0))}</td>"
            f"<td>{e(j.get('lane'))}</td><td>{e(j.get('package')) or '-'}</td><td>{e(flags)}</td>"
            f"<td><code>{e(j['id'])}</code></td></tr>")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark">
<title>Review batch {e(batch.id)}</title>
<style>body{{font:14px/1.5 -apple-system,'Segoe UI',Helvetica,Arial,sans-serif;max-width:1100px;margin:32px auto;padding:0 16px;color:#1f2328;background:#fff}}
table{{border-collapse:collapse;width:100%}}td,th{{border-top:1px solid #d0d7de;padding:8px;text-align:left;vertical-align:top}}
th{{color:#656d76;font-weight:600}}code{{font-size:12px}}a{{color:#0969da;word-break:break-all}}
@media (prefers-color-scheme:dark){{body{{background:#0d1117;color:#e6edf3}}td,th{{border-color:#30363d}}a{{color:#4493f8}}}}</style></head>
<body><h1>Review batch {e(batch.id)}</h1>
<p>{len(batch.jobs)} applications are ready. Approving covers exactly these postings as they are now; if a posting
changes, it comes back for review. Approve all with <code>jobveyra approve {e(batch.id)}</code>, or leave some out
with <code>--exclude ID</code>.</p>
<table><tr><th>Role</th><th>Location</th><th>Fit</th><th>Package</th><th>Materials</th><th>Flags</th><th>Job id</th></tr>
{''.join(rows)}</table></body></html>"""
    out.write_text(page, encoding="utf-8")
    return out
