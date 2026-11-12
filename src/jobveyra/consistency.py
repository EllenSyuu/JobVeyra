"""Do the queue, the outcomes ledger, the packages and the approvals agree?

``check(cfg, q)`` returns problems, each ``{"kind", "job", "detail"}``. None of them is fixed
automatically: each needs a person or an agent to look.

  submitted_without_confirmation  a submitted job with no confirmation text recorded
  outcome_for_unsent              an outcome recorded for a job that was never submitted
  outcome_unknown_job             an outcome for a job id the queue does not have
  ready_without_package           ready_to_submit but the package folder is missing
  package_failed_checks           ready_to_submit but the package's last build did not pass
  orphan_package                  a package folder whose job is not in the queue
  duplicate_open                  two open jobs with the same posting content
  deadline_passed                 an open job whose deadline is in the past
  final_stage_mismatch            the finalization stage disagrees with the queue state
  final_without_recovery          a job parked for final approval without its action / recovery note
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from . import outcomes as oc
from . import queue as Q


def check(cfg, q, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    jobs = q.all()
    by_id = {j["id"]: j for j in jobs}
    out = []

    def add(kind, jid, detail):
        out.append({"kind": kind, "job": jid, "detail": detail})

    for j in jobs:
        if j["state"] == "submitted" and not (j.get("confirmation") or j.get("reason") == "manual"):
            add("submitted_without_confirmation", j["id"], f"{j.get('employer')} · {j.get('title')}")
        if j["state"] == "ready_to_submit":
            pkg = j.get("package") or ""
            p = (cfg.workspace / pkg) if pkg and not Path(pkg).is_absolute() else Path(pkg)
            if not pkg or not p.exists():
                add("ready_without_package", j["id"], pkg or "no package recorded")
            elif (p / "report.json").is_file():
                try:
                    if not json.loads((p / "report.json").read_text(encoding="utf-8")).get("pass", True):
                        add("package_failed_checks", j["id"], str(p / "report.json"))
                except ValueError:
                    add("package_failed_checks", j["id"], "report.json unreadable")
        fs = j.get("final_stage") or ""
        if (fs and fs not in Q.FINAL_STAGES) or (fs in Q.STAGE_STATE and j["state"] not in Q.STAGE_STATE[fs]):
            add("final_stage_mismatch", j["id"], f"final_stage {fs} but state {j['state']}")
        if fs == Q.AWAITING_FINAL and not (j.get("final_need") and j.get("recovery")):
            add("final_without_recovery", j["id"], j.get("final_page") or "")
        d = oc.as_date((j.get("deadline") or "")[:10])
        if j["state"] in Q.OPEN and d and d < today:
            add("deadline_passed", j["id"], f"deadline {d.isoformat()}")
    for r in oc.load(q.dir):
        j = by_id.get(r.get("job_id"))
        if j is None:
            add("outcome_unknown_job", r.get("job_id"), r.get("outcome", ""))
        elif j["state"] != "submitted" and r.get("outcome") != "withdrawn":
            add("outcome_for_unsent", j["id"], f"{r.get('outcome')} recorded while {j['state']}")
    pk = cfg.workspace / "packages"
    if pk.is_dir():
        from .discover import safe_id
        known = {safe_id(j["id"]) for j in jobs}
        for d in sorted(pk.iterdir()):
            if d.is_dir() and d.name not in known:
                add("orphan_package", d.name, str(d))
    groups = defaultdict(list)
    for j in jobs:
        if j["state"] in Q.OPEN and j.get("content_hash"):
            groups[j["content_hash"]].append(j["id"])
    for h, ids in groups.items():
        if len(ids) > 1:
            add("duplicate_open", ids[0], "same posting as " + ", ".join(ids[1:]))
    return out
