"""Follow-ups due: submitted applications with no employer response after N days.

Days are calendar days. A ``no_reply`` record is not a response; it marks that the candidate
checked or followed up, so the waiting clock restarts from the latest such record.
"""
from __future__ import annotations

import datetime as dt

from .. import outcomes as oc


def message(job: dict, sent: dt.date | None, name: str = "") -> str:
    title = job.get("title") or "the open position"
    when = f" on {sent.strftime('%B')} {sent.day}" if sent else ""
    ref = f" (reference {job['req_id']})" if job.get("req_id") else ""
    sign = f"\n{name}" if name else ""
    return (f"Subject: Following up on my application for {title}\n\n"
            f"Hello,\n\n"
            f"I applied for the {title} role{ref}{when} and wanted to ask whether there is an update on the "
            f"hiring timeline. I am still very interested in the position and happy to share anything else "
            f"that would help.\n\n"
            f"Thank you for your time.\n\nBest regards,{sign}\n")


def due(jobs: list[dict], outcomes: list[dict], today, days: int, *, name: str = "") -> list[dict]:
    """``[{job_id, employer, title, submitted, days_waiting, suggested_message}]``, longest wait first."""
    today = oc.as_date(today) or dt.date.today()
    recs = oc.by_job(outcomes)
    out = []
    for j in jobs:
        if j.get("state") != "submitted":
            continue
        rs = recs.get(j["id"], [])
        if any(r["outcome"] != "no_reply" for r in rs):
            continue                       # the employer answered, or the candidate withdrew
        sent = oc.submitted_at(j)
        if sent is None:
            continue
        nudged = oc.first_at(rs[-1:], {"no_reply"}) if rs else None
        since = max(sent, nudged) if nudged else sent
        waiting = (today - since.date()).days
        if waiting < days:
            continue
        out.append({"job_id": j["id"], "employer": j.get("employer", ""), "title": j.get("title", ""),
                    "submitted": sent.date().isoformat(), "days_waiting": (today - sent.date()).days,
                    "days_since_contact": waiting,
                    "suggested_message": message(j, sent.date(), name)})
    out.sort(key=lambda r: (-r["days_waiting"], r["job_id"]))
    return out
