"""The submission lifecycle a browser-driving agent follows, one job at a time.

    next      lease the highest-priority job the policy allows (approval, daily cap)
    card      everything the agent needs for that job in about 1 KB
    finalize  on the last page: decide what may be ticked (finalize.py), write the durable attempt
              record, or park the job for the candidate and move on
    clicked   record the moment before the final Submit (so a crash is never resubmitted)
    done      record the employer's confirmation text; only this makes a job `submitted`
    uncertain no confirmation seen: `needs_check`, never retried automatically
    fail      transient (retried with backoff) or permanent (blocked_technical)

The agent drives the browser; this module only decides and records. It never clicks, never
signs in and never reads cookies.
"""
from __future__ import annotations

import datetime as dt

from . import approvals
from . import queue as jq


def submitted_today(q: jq.Queue, today: dt.date | None = None) -> int:
    d = (today or jq.now().date()).isoformat()
    return sum(1 for j in q.all("submitted") if (j.get("updated_at") or "")[:10] == d)


def next_job(cfg, q: jq.Queue, *, owner: str = "agent", signed_in: tuple[str, ...] = ()) -> tuple[dict | None, str]:
    """Lease the next job the policy allows. Returns (job, why-not) where job is None when nothing may run."""
    jq.configure(cfg)
    if cfg.policy.submission == "fill_only":
        job = q.claim(owner=owner, signed_in=signed_in)
        return job, "" if job else "nothing ready"
    if submitted_today(q) >= cfg.policy.max_per_day:
        return None, f"daily cap reached ({cfg.policy.max_per_day}); raise policy.max_per_day to continue"
    gate = (lambda j: approvals.allowed(j, cfg)[0]) if cfg.policy.submission == "batch_approve" else None
    job = q.claim(owner=owner, signed_in=signed_in, accept=gate)
    if job:
        return job, ""
    waiting = [j for j in q.all("ready_to_submit") if gate and not gate(j)]
    if waiting:
        return None, f"{len(waiting)} ready job(s) wait for approval: run `jobveyra review`"
    return None, "nothing ready"


def card(cfg, job: dict) -> dict:
    """The task card for one leased job."""
    ok, why = approvals.allowed(job, cfg)
    return {
        "id": job["id"], "employer": job.get("employer"), "title": job.get("title"),
        "apply": job.get("apply_url") or job.get("url"), "portal": job.get("portal"),
        "lane": job.get("lane"), "package": job.get("package") or "", "attempt": int(job.get("attempts") or 0) + 1,
        "may_submit": ok, "policy": why,
        "playbook": f"jobveyra playbook {job['id']}",
        **({"resume": {k: job.get(k) for k in ("final_grant", "final_page", "form_saved", "recovery") if job.get(k)}}
           if job.get("final_grant") or job.get("final_page") else {}),
        "rules": [
            "answer form questions only from the profile and verified facts; stop and ask when unsure",
            "run `jobveyra check-materials` on the package before typing anything",
            "never enter passwords or solve CAPTCHAs: block the job instead",
            "ordinary steps (Next, Save, verified answers, the narrowest consent) never need approval",
            "on the last page run `jobveyra finalize ID --elements JSON`: click=true -> tick `tick`, press "
            "Submit once; otherwise the job is parked: take the next one" if ok else
            "fill the form and stop before Submit: the candidate presses it",
            "run `jobveyra done ID --confirmation TEXT` only with the portal's confirmation text",
        ],
    }
