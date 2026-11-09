"""The daily retrospective and the learnings that steer the next run.

``review(cfg, q, today)`` writes ``reports/reviews/<date>.md``: what yesterday produced, what is
stuck, the funnel so far, reply rates by segment with 95 % intervals (only segments with enough
submissions are read as signals), whether the fit score predicts replies, and the learnings so far.

``learnings.md`` in the workspace is the running memory: one dated line per lesson, written by the
candidate or an agent with ``jobveyra learn "<lesson>"``. Agents read it at the start of every run
(AGENTS.md); the review suggests lessons from its signals but never writes them on its own.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

from . import outcomes as oc
from .analytics.calibration import calibrate
from .analytics.funnel import funnel as funnel_of
from .analytics.patterns import patterns as patterns_of


def learnings_path(cfg) -> Path:
    return cfg.workspace / "learnings.md"


def learn(cfg, text: str, today: dt.date) -> str:
    p = learnings_path(cfg)
    line = f"- {today.isoformat()}: {' '.join(text.split())}"
    head = "" if p.is_file() else "# Learnings\n\nOne line per lesson; agents read this before every run.\n\n"
    with p.open("a", encoding="utf-8") as fh:
        fh.write(head + line + "\n")
    return line


def learnings(cfg, last: int = 0) -> list[str]:
    p = learnings_path(cfg)
    if not p.is_file():
        return []
    rows = [x for x in p.read_text(encoding="utf-8").splitlines() if x.startswith("- ")]
    return rows[-last:] if last else rows


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.0f}%"


def review(cfg, q, today: dt.date) -> tuple[Path, str]:
    jobs, outs = q.all(), oc.load(q.dir)
    y = today - dt.timedelta(days=1)
    sent_y = [j for j in jobs if j["state"] == "submitted" and (oc.submitted_at(j) or dt.datetime.min).date() == y]
    recs_y = [r for r in outs if (oc.parse_time(r.get("at")) or dt.datetime.min).date() == y]
    states = Counter(j["state"] for j in jobs)
    f = funnel_of(jobs, outs)
    pats = patterns_of(jobs, outs)
    cal = calibrate(jobs, outs, exclude_below=cfg.policy.exclude_below)
    L = [f"# Review · {today.isoformat()}", "", f"## Yesterday ({y.isoformat()})", ""]
    L += [f"- Sent {len(sent_y)}" + (": " + "; ".join(f"{j.get('employer')} · {j.get('title')}" for j in sent_y[:10])
                                      if sent_y else "")]
    L += [f"- Heard back {len(recs_y)}" + (": " + ", ".join(sorted({r['outcome'] for r in recs_y})) if recs_y else "")]
    L += ["", "## Queue now", "", "  ".join(f"{k} {v}" for k, v in sorted(states.items())) or "empty", ""]
    stuck = states.get("blocked_auth", 0) + states.get("blocked_human", 0) + states.get("blocked_technical", 0)
    if stuck or states.get("needs_check"):
        L += [f"{stuck} blocked, {states.get('needs_check', 0)} to check on a portal: see `jobveyra board`.", ""]
    L += ["## Funnel", ""]
    for k, v in f.items():
        if not isinstance(v, (dict, list)):
            L.append(f"- {k.replace('_', ' ')}: {v}")
    L += ["", "## Reply rate by segment", "",
          "| Segment | Value | Sent | Replied | Rate | 95% interval | Signal |", "|---|---|--:|--:|--:|---|---|"]
    for r in pats[:20]:
        L.append(f"| {r['dimension']} | {r['value']} | {r['n']} | {r['replied']} | {_pct(r['rate'])} | "
                 f"{_pct(r['low'])}-{_pct(r['high'])} | {r['signal']} |")
    if not pats:
        L.append("| - | no submissions yet | | | | | |")
    L += ["", "## Does the fit score predict replies?", "", str(cal.get("recommendation") or "not enough data yet"), ""]
    sig = [r for r in pats if r["signal"] != "insufficient"]
    if sig:
        L += ["## Suggested lessons (record the ones you agree with: `jobveyra learn \"...\"`)", ""]
        for r in sig[:5]:
            word = "more" if r["signal"] == "above" else "fewer"
            L.append(f"- {r['dimension']} = {r['value']} replies at {_pct(r['rate'])} vs {_pct(r['overall'])} overall "
                     f"(n={r['n']}): consider {word} applications like these.")
        L.append("")
    lessons = learnings(cfg, last=10)
    L += ["## Learnings so far", ""] + (lessons or ["- none yet"])
    text = "\n".join(L).rstrip() + "\n"
    out = cfg.workspace / "reports" / "reviews" / f"{today.isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out, text
