"""The digest: one dict of numbers that every report (email, status block, notifications) uses.

Submission times come from ``submitted_at`` when a row has one, else from the queue's event log
(the transition to ``submitted``), else from the row's ``updated_at``. Replies, interviews and
offers come from the outcomes ledger, never from queue states.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter

from .. import outcomes as oc
from .. import queue as qmod
from ..analytics.funnel import funnel
from ..interview.followups import due as followups_due

SERIES_DAYS = 14
HORIZON_DAYS = 14


def _jobs(q) -> list[dict]:
    times = oc.submission_times(q.dir)
    jobs = []
    for j in q.all():
        if j.get("state") == "submitted" and not j.get("submitted_at") and j["id"] in times:
            j = {**j, "submitted_at": times[j["id"]]}
        jobs.append(j)
    return jobs


def _fit(j: dict) -> float | None:
    try:
        return float(j["fit"]) if j.get("fit") not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _flag_list(j: dict) -> list[str]:
    f = j.get("flags")
    if isinstance(f, str):
        return [x.strip() for x in f.split(",") if x.strip()]
    return [str(x) for x in f] if f else []


def build(cfg, q, today) -> dict:
    today = oc.as_date(today) or dt.date.today()
    jobs = _jobs(q)
    outs = oc.load(q.dir)
    recs = oc.by_job(outs)
    sub = [j for j in jobs if j.get("state") == "submitted"]
    sent_on = {j["id"]: (oc.submitted_at(j) or dt.datetime.min).date() for j in sub}

    def hit(j, kinds):
        return oc.reached(recs.get(j["id"], []), kinds)

    replies = sum(1 for j in sub if hit(j, oc.REPLY))
    interviews = sum(1 for j in sub if hit(j, oc.INTERVIEW))
    offers = sum(1 for j in sub if hit(j, oc.OFFER))
    totals = {"submitted": len(sub), "replies": replies, "interviews": interviews, "offers": offers,
              "reply_rate": round(100 * replies / len(sub)) if sub else 0,
              "open": sum(1 for j in jobs if j.get("state") in qmod.OPEN),
              "discovered": len(jobs)}

    series = []
    for k in range(SERIES_DAYS - 1, -1, -1):
        d = today - dt.timedelta(days=k)
        series.append({"date": d.isoformat(), "sent": sum(1 for v in sent_on.values() if v == d)})
    last7 = sum(1 for v in sent_on.values() if 0 <= (today - v).days < 7)

    labels = {t.key: t.label for t in cfg.focus.tracks}
    tracks: dict[str, dict] = {}
    for j in sub:
        key = j.get("family") or ""
        t = tracks.setdefault(key, {"track": key or "other", "label": labels.get(key, key or "Other"),
                                    "sent": 0, "replies": 0, "_fits": []})
        t["sent"] += 1
        t["replies"] += 1 if hit(j, oc.REPLY) else 0
        if _fit(j) is not None:
            t["_fits"].append(_fit(j))
    by_track = []
    for t in sorted(tracks.values(), key=lambda t: (-t["sent"], t["label"])):
        fits = t.pop("_fits")
        t["avg_fit"] = round(sum(fits) / len(fits)) if fits else None
        by_track.append(t)

    auth: dict[str, dict] = {}
    for j in jobs:
        if j.get("state") != "blocked_auth":
            continue
        scope = q.scope(j)
        g = auth.setdefault(scope, {"scope": scope, "count": 0, "best_fit": None, "earliest_deadline": "",
                                    "action": j.get("action") or qmod.action_for("auth:", scope)})
        g["count"] += 1
        f = _fit(j)
        if f is not None and (g["best_fit"] is None or f > g["best_fit"]):
            g["best_fit"] = f
        dl = (j.get("deadline") or "")[:10]
        if dl and (not g["earliest_deadline"] or dl < g["earliest_deadline"]):
            g["earliest_deadline"] = dl
    for g in auth.values():
        if g["best_fit"] is not None:
            g["best_fit"] = int(round(g["best_fit"]))
    states = Counter(j.get("state") for j in jobs)
    needs = {
        "auth": sorted(auth.values(), key=lambda g: (g["earliest_deadline"] or "9999", -(g["best_fit"] or 0), g["scope"])),
        "human": states.get("blocked_human", 0),
        "technical": states.get("blocked_technical", 0),
        "needs_check": states.get("needs_check", 0),
        "approvals_pending": states.get("ready_to_submit", 0) if cfg.policy.submission == "batch_approve" else 0,
    }

    deadlines = []
    for j in jobs:
        if j.get("state") not in qmod.OPEN:
            continue
        d = oc.as_date((j.get("deadline") or "")[:10])
        if d and 0 <= (d - today).days <= HORIZON_DAYS:
            deadlines.append({"date": d.isoformat(), "days_left": (d - today).days, "job_id": j["id"],
                              "employer": j.get("employer", ""), "title": j.get("title", ""),
                              "state": j.get("state", ""), "fit": _fit(j)})
    deadlines.sort(key=lambda x: (x["date"], -(x["fit"] or 0), x["job_id"]))
    fups = followups_due(jobs, outs, today, cfg.policy.follow_up_days, name=cfg.candidate.name)

    flag_counts = Counter()
    for j in jobs:
        if j.get("state") in qmod.OPEN:
            flag_counts.update(f.split(":")[0] for f in _flag_list(j))
        if j.get("state") == "blocked_technical" and j.get("reason"):
            flag_counts[f"blocked:{j['reason'].split(':')[0]}"] += 1
        d = oc.as_date((j.get("deadline") or "")[:10])
        if j.get("state") in qmod.OPEN and d and d < today:
            flag_counts["deadline_passed"] += 1
    warnings = []
    by_source = Counter(j.get("source") or "(none)" for j in sub)
    if len(sub) >= 5 and by_source:
        src, n = by_source.most_common(1)[0]
        if n / len(sub) > cfg.policy.max_source_share:
            warnings.append(f"{src} supplied {n} of {len(sub)} submissions ({n / len(sub):.0%}), above "
                            f"policy.max_source_share {cfg.policy.max_source_share:.0%}")
    if flag_counts.get("deadline_passed"):
        warnings.append(f"{flag_counts['deadline_passed']} open job(s) are past their deadline")

    yesterday = today - dt.timedelta(days=1)
    return {
        "date": today.isoformat(),
        "totals": totals,
        "last7": last7,
        "yesterday": [{"job_id": j["id"], "employer": j.get("employer", ""), "title": j.get("title", "")}
                      for j in sub if sent_on[j["id"]] == yesterday],
        "series": series,
        "by_track": by_track,
        "needs": needs,
        "coming_up": {"deadlines": deadlines, "followups": fups},
        "flags": {"counts": dict(sorted(flag_counts.items())), "warnings": warnings},
        "funnel": funnel(jobs, outs),
        "states": dict(sorted(states.items())),
    }
