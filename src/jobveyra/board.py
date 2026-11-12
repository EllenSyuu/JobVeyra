"""A Markdown checklist the candidate edits instead of typing commands.

``render(cfg, q)`` writes the board: portals to sign in to, open questions, applications to check
on the portal, blocked jobs, and recent submissions to record a reply on. Every box carries a hidden
marker ``<!-- jv:<action>:<arg> -->`` so parsing never depends on the visible wording or language.

``apply(cfg, q, body)`` reads an edited board and applies each ticked box once:

    signedin:<scope>        records a sign-in signal (an agent verifies it in the browser)
    found:<id>              needs_check job found on the portal: submitted
    notfound:<id>           needs_check job not on the portal: back to ready_to_submit
    final:<scope>|<kinds>   approve the last step (declaration, terms...) for that portal's parked jobs:
                            an authorization, never a submission; the agent finishes them
    manual:<id>             the candidate applied themselves: needs_check until the portal shows it
    skip:<id>               drop the job: excluded
    outcome:<kind>:<id>     record reply, interview, rejected, offer for a submitted job

``comment(cfg, q, text)`` reads a reply such as ``Q3: Yes, from January`` and answers question Q3.

The board lives wherever Markdown checkboxes are editable: a GitHub issue in a private repository
(see docs/BOARD.md for the workflow), an Obsidian or Notion page, or a plain file.
"""
from __future__ import annotations

import datetime as dt
import re

from . import outcomes as oc
from . import signins
from .answers import Memory

MARK = re.compile(r"^\s*[-*]\s+\[[xX]\]\s.*?<!--\s*jv:([a-z]+):(\S+?)\s*-->", re.M)
OUTCOME_KINDS = ("reply", "interview", "rejected", "offer")


def _box(label: str, action: str, arg: str) -> str:
    return f"- [ ] {label} <!-- jv:{action}:{arg} -->"


def render(cfg, q, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    out = [f"# Job search board · {today.isoformat()}", "",
           "Tick a box (or reply in a comment for questions); the next sync applies it.", ""]
    groups = signins.waiting(q)
    if groups:
        out += ["## Sign in", ""]
        for g in groups:
            due = f", earliest deadline {g['earliest_deadline']}" if g["earliest_deadline"] else ""
            out.append(_box(f"I signed in to **{g['portal']}** `{g['scope']}`: {len(g['jobs'])} waiting{due} "
                            f"([open]({g['open']}))", "signedin", g["scope"]))
        out.append("")
    qs = Memory(cfg.workspace).open_questions()
    if qs:
        out += ["## Questions", "", "Reply in a comment, e.g. `Q1: Yes`.", ""]
        out += [f"- **{x['id']}** {x['company']}: {x['question']} ({len(x['jobs'].split(','))} job(s) waiting)"
                for x in qs]
        out.append("")
    from . import queue as jq
    finals = [j for j in q.all("blocked_human") if j.get("final_stage") == jq.AWAITING_FINAL]
    if finals:
        out += ["## Final approval", "", "The form is complete; only the last step needs you. Approving lets the "
                "agent finish it; the portal's confirmation page still decides what counts as submitted.", ""]
        fg: dict = {}
        for j in finals:
            fg.setdefault((q.scope(j), j.get("final_kind") or ""), []).append(j)
        for (scope, kind), js in sorted(fg.items()):
            label = ", ".join(jq.KIND_LABELS.get(k, k) for k in kind.split(",") if k)
            out.append(_box(f"approve the last step on **{scope}** ({label}): {len(js)} job(s)", "final", f"{scope}|{kind}"))
            for j in js:
                out.append(f"  - {j.get('employer')} · {j.get('title')}: {j.get('final_need') or ''}"
                           + (f" ([open]({j['final_page']}))" if j.get("final_page") else ""))
        out.append("")
    checks = q.all("needs_check")
    if checks:
        out += ["## Check on the portal", "", "Submit was clicked but no confirmation was seen. Look in the portal's "
                "list of your applications.", ""]
        for j in checks:
            out.append(f"- {j.get('employer')} · {j.get('title')}")
            out.append("  " + _box("found it there", "found", j["id"]))
            out.append("  " + _box("not there", "notfound", j["id"]))
        out.append("")
    blocked = [j for j in q.all() if j["state"] in ("blocked_human", "blocked_technical")
               and not (j.get("reason") or "").startswith("hold:Q") and j.get("final_stage") != jq.AWAITING_FINAL]
    if blocked:
        out += ["## Stuck", ""]
        for j in blocked:
            out.append(f"- {j.get('employer')} · {j.get('title')}: {j.get('action') or j.get('reason')}"
                       + (f" ([open]({j.get('apply_url') or j.get('url')}))" if j.get("apply_url") or j.get("url") else ""))
            out.append("  " + _box("I applied myself", "manual", j["id"]))
            out.append("  " + _box("skip it", "skip", j["id"]))
        out.append("")
    recs = oc.by_job(oc.load(q.dir))
    sub = sorted(q.all("submitted"), key=lambda j: j.get("updated_at") or "", reverse=True)
    recent = [j for j in sub if not oc.reached(recs.get(j["id"], []), oc.REPLY)][:15]
    if recent:
        out += ["## Heard back?", ""]
        for j in recent:
            boxes = " ".join(f"[ ] {k} <!-- jv:outcome:{k}:{j['id']} -->" for k in OUTCOME_KINDS)
            out.append(f"- {j.get('employer')} · {j.get('title')}")
            out.append("  - " + boxes)
        out.append("")
    if len(out) <= 4:
        out.append("Nothing needs you right now.")
    return "\n".join(out).rstrip() + "\n"


_INLINE = re.compile(r"\[[xX]\]\s+\w+\s+<!--\s*jv:(outcome):(\S+?)\s*-->")


def ticked(body: str) -> list[tuple[str, str]]:
    found = [(m.group(1), m.group(2)) for m in MARK.finditer(body or "")]
    found += [(m.group(1), m.group(2)) for m in _INLINE.finditer(body or "")]
    return list(dict.fromkeys(found))


def apply(cfg, q, body: str) -> list[str]:
    """Apply every ticked box; returns one human-readable line per change. Safe to run twice."""
    done = []
    for action, arg in ticked(body):
        if action == "signedin":
            if any(s["scope"] == arg for s in signins.pending(cfg.state_dir)):
                continue
            if any(g["scope"] == arg for g in signins.waiting(q)):
                signins.signal(cfg.state_dir, arg, source="board")
                done.append(f"sign-in recorded for {arg}")
            continue
        if action == "final":
            from . import queue as jq
            scope, _, kind = arg.partition("|")
            for j in q.all("blocked_human"):
                if j.get("final_stage") == jq.AWAITING_FINAL and q.scope(j) == scope and (j.get("final_kind") or "") == kind:
                    q.grant_final(j["id"], f"candidate approved on the board ({scope} · {kind})")
                    done.append(f"final step approved: {j.get('employer')} · {j.get('title')}")
            continue
        if action == "outcome":
            kind, _, jid = arg.partition(":")
            j = q.get(jid)
            if kind in OUTCOME_KINDS and j and j["state"] == "submitted":
                if not any(r.get("outcome") == kind for r in oc.by_job(oc.load(q.dir)).get(jid, [])):
                    oc.record(q.dir, jid, kind, "board")
                    done.append(f"{kind}: {j.get('employer')} · {j.get('title')}")
            continue
        j = q.get(arg)
        if not j:
            continue
        try:
            done += _job_action(q, action, arg, j)
        except ValueError:                 # an illegal transition: the job moved on since the board was drawn
            continue
    return done


def _job_action(q, action: str, arg: str, j: dict) -> list[str]:
    done = []
    if action == "found" and j["state"] == "needs_check":
        q.resolve_check(arg, found_on_portal=True, evidence="candidate found it on the portal (board)")
        done.append(f"submitted (found on portal): {j.get('employer')}")
    elif action == "notfound" and j["state"] == "needs_check":
        q.resolve_check(arg, found_on_portal=False, evidence="not on the portal (board)")
        done.append(f"back in the queue: {j.get('employer')}")
    elif action == "manual" and j["state"] not in ("submitted", "excluded", "needs_check"):
        q.candidate_reported(arg, "applied by the candidate (board)")
        done.append(f"noted that you applied: {j.get('employer')}; tick 'found it there' once the portal lists it")
    elif action == "skip" and j["state"] not in ("submitted", "excluded"):
        q.set_state(arg, "excluded", "skipped by the candidate (board)", reason="skipped:board")
        done.append(f"skipped: {j.get('employer')}")
    return done


REPLY = re.compile(r"^\s*(Q\d+)\s*[:：.\-]?\s*(.+?)\s*$", re.I | re.M)


def comment(cfg, q, text: str, today: dt.date | None = None) -> list[str]:
    """Answer questions from a comment (``Q3: Yes``); each answered question releases its jobs."""
    mem = Memory(cfg.workspace)
    done = []
    for m in REPLY.finditer(text or ""):
        try:
            item = mem.reply(m.group(1).upper(), m.group(2), today or dt.date.today())
        except KeyError:
            continue
        released = [jid for j in q.all() if (j.get("reason") or "") == f"hold:{item['id']}"
                    for jid in q.unblock(jid=j["id"])]
        done.append(f"{item['id']} answered; {len(released)} job(s) back in the queue")
    return done
