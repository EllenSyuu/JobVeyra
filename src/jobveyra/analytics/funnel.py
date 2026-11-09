"""Application funnel: discovered -> eligible -> submitted -> reply -> interview -> offer."""
from __future__ import annotations

import statistics

from .. import outcomes as oc

STAGES = ("discovered", "eligible", "submitted", "reply", "interview", "offer")
_NOT_ELIGIBLE = ("discovered", "excluded")


def _rate(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def funnel(jobs: list[dict], outcomes: list[dict]) -> dict:
    """Counts per stage, step and overall conversion, and the median days from submission to the
    first employer response. Reply/interview/offer count only jobs the queue shows as submitted;
    outcomes recorded for any other job id are reported as ``unmatched_outcomes``."""
    recs = oc.by_job(outcomes)
    submitted = [j for j in jobs if j.get("state") == "submitted"]
    sub_ids = {j["id"] for j in submitted}
    counts = {
        "discovered": len(jobs),
        "eligible": sum(1 for j in jobs if j.get("state") not in _NOT_ELIGIBLE),
        "submitted": len(submitted),
        "reply": sum(1 for j in submitted if oc.reached(recs.get(j["id"], []), oc.REPLY)),
        "interview": sum(1 for j in submitted if oc.reached(recs.get(j["id"], []), oc.INTERVIEW)),
        "offer": sum(1 for j in submitted if oc.reached(recs.get(j["id"], []), oc.OFFER)),
    }
    stages = []
    for i, s in enumerate(STAGES):
        prev = counts[STAGES[i - 1]] if i else None
        stages.append({"stage": s, "n": counts[s],
                       "from_previous": _rate(counts[s], prev) if i else None,
                       "from_discovered": _rate(counts[s], counts["discovered"])})
    days = []
    for j in submitted:
        first = oc.first_at(recs.get(j["id"], []), oc.REPLY)
        sent = oc.submitted_at(j)
        if first and sent:
            days.append(max(0.0, (first - sent).total_seconds() / 86400))
    return {
        "counts": counts,
        "stages": stages,
        "conversion": {
            "reply_rate": _rate(counts["reply"], counts["submitted"]),
            "interview_rate": _rate(counts["interview"], counts["submitted"]),
            "offer_rate": _rate(counts["offer"], counts["submitted"]),
            "interview_per_reply": _rate(counts["interview"], counts["reply"]),
            "offer_per_interview": _rate(counts["offer"], counts["interview"]),
        },
        "median_days_to_reply": round(statistics.median(days), 1) if days else None,
        "replies_timed": len(days),
        "unmatched_outcomes": len(set(recs) - sub_ids),
    }
