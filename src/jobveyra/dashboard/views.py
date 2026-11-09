"""HTML for the dashboard pages. Every value is escaped; charts are inline SVG.

Pages render completely on the server, so they read the same without JavaScript. The script
adds client-side filtering and sorting on the queue and sends the action forms as JSON.
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote

from .. import outcomes as oc
from .. import queue as qmod
from .markdown import render as render_md
from .markdown import safe_url

NAV = (("/", "overview", "Overview"), ("/queue", "queue", "Queue"), ("/review", "review", "Review"),
       ("/insights", "insights", "Insights"))
POLICY_TEXT = {
    "batch_approve": "You review a batch and approve it once. Each approval covers the exact posting content; "
                     "a changed posting comes back for review.",
    "auto": "Every job that passes your filters, score threshold and daily cap may be submitted without a review step.",
    "fill_only": "Forms are filled and stop before Submit. You press it.",
}
STATE_ORDER = {s: i for i, s in enumerate(("needs_check", "blocked_human", "blocked_auth", "blocked_technical",
                                           "in_progress", "ready_to_submit", "retry_wait", "eligible",
                                           "discovered", "submitted", "excluded"))}


def e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def job_href(jid: str) -> str:
    return "/job/" + quote(jid, safe="")


def cls_token(s: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "", (s or "").lower())


def fit_txt(v) -> str:
    return "" if v is None else str(v)


def pct(v, digits: int = 0) -> str:
    if v is None:
        return "–"
    return f"{100 * v:.{digits}f}%"


def badge(state: str) -> str:
    return f'<span class="state state-{cls_token(state)}">{e((state or "").replace("_", " "))}</span>'


def ext_link(url: str, label: str = "Posting") -> str:
    u = safe_url(url)
    if not u or not u.lower().startswith(("http://", "https://")):
        return ""
    return f'<a href="{e(u)}" rel="noopener noreferrer" target="_blank">{e(label)}<span class="sr-only"> (opens in a new tab)</span></a>'


def role_link(jid: str, employer: str, title: str) -> str:
    return (f'<a href="{e(job_href(jid))}"><span class="emp">{e(employer) or "Unknown employer"}</span>'
            f'<span class="role">{e(title)}</span></a>')


def empty(text: str) -> str:
    return f'<p class="empty">{e(text)}</p>'


# ---------------------------------------------------------------- layout and forms

def page(ctx: dict, title: str, active: str, body: str, *, lead: str = "") -> str:
    cur = ' aria-current="page"'
    nav = "".join(f'<li><a href="{href}"{cur if key == active else ""}>{label}</a></li>' for href, key, label in NAV)
    mode = ctx.get("mode", "")
    ro = '<span class="pill pill-strong">Read-only</span>' if ctx.get("read_only") else ""
    lead_html = f'<p class="lead">{lead}</p>' if lead else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="csrf-token" content="{e(ctx.get('csrf'))}">
<meta name="referrer" content="same-origin">
<title>{e(title)} · JobVeyra</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="/static/dashboard.css">
<script src="/static/dashboard.js" defer></script>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <div class="top-inner">
    <a class="brand" href="/">JobVeyra</a>
    <nav aria-label="Main"><ul>{nav}</ul></nav>
    <div class="top-meta">
      <a class="pill" href="/review" title="policy.submission">Submission: {e(mode.replace('_', ' '))}</a>{ro}
    </div>
  </div>
</header>
<main id="main" tabindex="-1">
<h1>{e(title)}</h1>
{lead_html}
{body}
</main>
<footer class="foot">
  <p>Workspace <code>{e(ctx.get('workspace'))}</code> · {e(ctx.get('today'))} · This dashboard records decisions only.
  It never submits an application or enters credentials.</p>
</footer>
</body>
</html>"""


def form(ctx: dict, action: str, next_: str, inner: str, *, confirm: str = "", cls: str = "action",
         label: str = "") -> str:
    if ctx.get("read_only"):
        return ""
    conf = f' data-confirm="{e(confirm)}"' if confirm else ""
    aria = f' aria-label="{e(label)}"' if label else ""
    return (f'<form method="post" action="/api/{e(action)}" class="{e(cls)}" data-api{conf}{aria}>'
            f'<input type="hidden" name="csrf" value="{e(ctx.get("csrf"))}">'
            f'<input type="hidden" name="next" value="{e(next_)}">{inner}'
            f'<p class="form-status" role="status" aria-live="polite"></p></form>')


def read_only_note(ctx: dict) -> str:
    return ('<p class="note">Read-only mode: actions are turned off. Restart without '
            '<code>--read-only</code> to record decisions.</p>' if ctx.get("read_only") else "")


def table(caption: str, heads: list[tuple[str, str]], rows: list[str], *, cls: str = "",
          hide_caption: bool = False) -> str:
    th = "".join('<th scope="col"' + (f' class="{c}"' if c else "") + f">{e(h)}</th>" for h, c in heads)
    cap_cls = ' class="sr-only"' if hide_caption else ""
    return (f'<div class="table-wrap" tabindex="0" role="region" aria-label="{e(caption)}">'
            f'<table class="{e(cls)}"><caption{cap_cls}>{e(caption)}</caption>'
            f'<thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


# ---------------------------------------------------------------- charts

def bar_chart(series: list[dict]) -> str:
    w, h, pad_l, pad_b, pad_t = 900, 200, 28, 28, 14
    n = max(len(series), 1)
    top = max([s["sent"] for s in series] + [1])
    inner_w, inner_h = w - pad_l - 8, h - pad_b - pad_t
    step = inner_w / n
    bw = max(4.0, step * 0.62)
    bars, labels = [], []
    for i, s in enumerate(series):
        x = pad_l + i * step + (step - bw) / 2
        bh = inner_h * s["sent"] / top
        y = pad_t + inner_h - bh
        tip = f'{s["date"]}: {s["sent"]} sent'
        if s["sent"]:
            bars.append(f'<rect class="bar" x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2">'
                        f'<title>{e(tip)}</title></rect>')
        else:
            bars.append(f'<rect class="bar-zero" x="{x:.1f}" y="{pad_t + inner_h - 2:.1f}" width="{bw:.1f}" height="2">'
                        f'<title>{e(tip)}</title></rect>')
        if i % 2 == (n - 1) % 2:
            labels.append(f'<text class="tick" x="{x + bw / 2:.1f}" y="{h - 9}" text-anchor="middle">'
                          f'{e(s["date"][8:10].lstrip("0"))}</text>')
    total = sum(s["sent"] for s in series)
    first, last = (series[0]["date"], series[-1]["date"]) if series else ("", "")
    grid = (f'<line class="grid" x1="{pad_l}" x2="{w - 8}" y1="{pad_t}" y2="{pad_t}"/>'
            f'<text class="tick" x="{pad_l - 6}" y="{pad_t + 4}" text-anchor="end">{top}</text>'
            f'<line class="axis" x1="{pad_l}" x2="{w - 8}" y1="{pad_t + inner_h}" y2="{pad_t + inner_h}"/>'
            f'<text class="tick" x="{pad_l - 6}" y="{pad_t + inner_h + 4}" text-anchor="end">0</text>')
    rows = "".join(f'<tr><td>{e(s["date"])}</td><td class="num">{s["sent"]}</td></tr>' for s in series)
    return f"""<figure class="chart">
<figcaption id="sent-cap">Applications sent per day, {e(first)} to {e(last)}</figcaption>
<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="sent-title sent-desc" preserveAspectRatio="xMidYMid meet">
<title id="sent-title">Applications sent per day</title>
<desc id="sent-desc">{total} applications over {len(series)} days; the highest day had {top if total else 0}.</desc>
{grid}{''.join(bars)}{''.join(labels)}
</svg>
<details class="data"><summary>Show the numbers</summary>
<table><caption class="sr-only">Applications sent per day</caption><thead><tr><th scope="col">Date</th><th scope="col" class="num">Sent</th></tr></thead><tbody>{rows}</tbody></table>
</details>
</figure>"""


def hbar(value: float | None, *, width: int = 120, mark: float | None = None) -> str:
    """A small horizontal bar for a 0..1 value, with an optional reference tick."""
    v = 0.0 if value is None else max(0.0, min(1.0, value))
    tick = ""
    if mark is not None:
        mx = 1 + (width - 2) * max(0.0, min(1.0, mark))
        tick = f'<line class="ref" x1="{mx:.1f}" x2="{mx:.1f}" y1="0" y2="12"/>'
    return (f'<svg class="hbar" width="{width}" height="12" viewBox="0 0 {width} 12" aria-hidden="true" focusable="false">'
            f'<rect class="track" x="0" y="3" width="{width}" height="6" rx="3"/>'
            f'<rect class="bar" x="0" y="3" width="{(width * v):.1f}" height="6" rx="3"/>{tick}</svg>')


def interval(lo: float, hi: float, rate: float, overall: float, *, width: int = 140) -> str:
    def x(v):
        return 4 + (width - 8) * max(0.0, min(1.0, v))
    return (f'<svg class="interval" width="{width}" height="14" viewBox="0 0 {width} 14" aria-hidden="true" focusable="false">'
            f'<line class="track-line" x1="4" x2="{width - 4}" y1="7" y2="7"/>'
            f'<line class="ref" x1="{x(overall):.1f}" x2="{x(overall):.1f}" y1="1" y2="13"/>'
            f'<line class="ci" x1="{x(lo):.1f}" x2="{x(hi):.1f}" y1="7" y2="7"/>'
            f'<circle class="dot" cx="{x(rate):.1f}" cy="7" r="3"/></svg>')


def calibration_chart(cal: dict) -> str:
    buckets = cal.get("buckets", [])
    w, row_h, pad_l, pad_r = 560, 30, 64, 120
    h = row_h * len(buckets) + 24
    inner = w - pad_l - pad_r
    parts = []
    for i, b in enumerate(buckets):
        y = 8 + i * row_h
        parts.append(f'<text class="label" x="{pad_l - 10}" y="{y + 14}" text-anchor="end">{e(b["bucket"])}</text>')
        parts.append(f'<rect class="track" x="{pad_l}" y="{y + 4}" width="{inner}" height="14" rx="2"/>')
        if b["n"]:
            bw = inner * (b["rate"] or 0)
            parts.append(f'<rect class="bar" x="{pad_l}" y="{y + 4}" width="{bw:.1f}" height="14" rx="2">'
                         f'<title>{e(b["bucket"])}: {b["positive"]} of {b["n"]} positive</title></rect>')
            txt = f'{pct(b["rate"])}  ({b["positive"]}/{b["n"]})'
        else:
            txt = "no submissions"
        parts.append(f'<text class="value" x="{pad_l + inner + 10}" y="{y + 15}">{e(txt)}</text>')
    if cal.get("overall_rate") is not None:
        ox = pad_l + inner * cal["overall_rate"]
        parts.append(f'<line class="ref" x1="{ox:.1f}" x2="{ox:.1f}" y1="4" y2="{h - 16}"/>'
                     f'<text class="tick" x="{ox:.1f}" y="{h - 4}" text-anchor="middle">overall {pct(cal["overall_rate"])}</text>')
    desc = "; ".join(f'{b["bucket"]}: {pct(b["rate"]) if b["n"] else "none"} of {b["n"]}' for b in buckets)
    return f"""<figure class="chart">
<figcaption>Positive-response rate by fit score</figcaption>
<svg class="narrow" viewBox="0 0 {w} {h}" role="img" aria-labelledby="cal-title cal-desc">
<title id="cal-title">Positive-response rate by fit bucket</title><desc id="cal-desc">{e(desc)}</desc>
{''.join(parts)}
</svg>
</figure>"""


# ---------------------------------------------------------------- overview

def overview(ctx: dict, dg: dict) -> str:
    t = dg["totals"]
    stats = [("Submitted", t["submitted"], "confirmed by the employer"),
             ("Last 7 days", dg["last7"], "sent this week"),
             ("Replies", t["replies"], "any employer response"),
             ("Interviews", t["interviews"], "interview or later"),
             ("Offers", t["offers"], "offer or hired"),
             ("Reply rate", f'{t["reply_rate"]}%', "replies per submission")]
    stat_html = "".join(f'<div class="stat"><dt>{e(k)}</dt><dd><span class="num-big">{e(v)}</span>'
                        f'<span class="hint">{e(h)}</span></dd></div>' for k, v, h in stats)
    needs = dg["needs"]
    att = dg.get("attention", {})
    mode = dg.get("policy", {}).get("submission", ctx.get("mode"))

    auth_rows = [f'<tr><th scope="row"><code>{e(g["scope"])}</code></th><td class="num">{g["count"]}</td>'
                 f'<td class="num">{fit_txt(g["best_fit"])}</td><td>{e(g["earliest_deadline"]) or "–"}</td>'
                 f'<td class="wrap">{e(g["action"])}</td></tr>' for g in needs["auth"]]
    auth = (table("Sign-ins needed, by portal", [("Portal", ""), ("Jobs", "num"), ("Best fit", "num"),
                                                 ("Earliest deadline", ""), ("What to do", "")], auth_rows)
            if auth_rows else empty("No portal is waiting for a sign-in."))

    def job_list(rows, text_empty):
        if not rows:
            return empty(text_empty)
        items = "".join(f'<li>{role_link(j["id"], j.get("employer", ""), j.get("title", ""))}'
                        f'<span class="why"><code>{e(j.get("reason"))}</code> {e(j.get("action"))}</span></li>'
                        for j in rows)
        return f'<ul class="joblist">{items}</ul>'

    if mode == "batch_approve":
        appr = (f'<p><span class="count">{needs["approvals_pending"]}</span> ready to submit and waiting for approval. '
                f'<a href="/review">Open review</a></p>')
    else:
        appr = f'<p>Approvals are not used under <code>policy.submission: {e(mode)}</code>.</p>'
    warnings = "".join(f"<li>{e(w)}</li>" for w in dg.get("flags", {}).get("warnings", []))
    warn_html = f'<div class="callout"><h3>Warnings</h3><ul>{warnings}</ul></div>' if warnings else ""

    dl_rows = [f'<tr><td>{e(d["date"])}</td><td class="num">{d["days_left"]}</td>'
               f'<td>{role_link(d["job_id"], d["employer"], d["title"])}</td><td>{badge(d["state"])}</td></tr>'
               for d in dg["coming_up"]["deadlines"]]
    deadlines = (table("Deadlines in the next 14 days", [("Date", ""), ("Days left", "num"), ("Role", ""),
                                                         ("State", "")], dl_rows)
                 if dl_rows else empty("No deadline in the next 14 days."))
    fu_rows = [f'<tr><td>{role_link(f["job_id"], f["employer"], f["title"])}'
               f'<details class="draft"><summary>Draft message</summary><pre>{e(f["suggested_message"])}</pre></details></td>'
               f'<td>{e(f["submitted"])}</td><td class="num">{f["days_since_contact"]}</td></tr>'
               for f in dg["coming_up"]["followups"]]
    followups = (table("Follow-ups due", [("Role", ""), ("Submitted", ""), ("Days since contact", "num")], fu_rows)
                 if fu_rows else empty("No follow-up is due."))

    tr_rows = [f'<tr><th scope="row">{e(t["label"])}</th><td class="num">{t["sent"]}</td>'
               f'<td class="num">{t["replies"]}</td><td class="num">{fit_txt(t["avg_fit"])}</td></tr>'
               for t in dg.get("by_track", [])]
    tracks = (table("Submissions by track", [("Track", ""), ("Sent", "num"), ("Replies", "num"), ("Average fit", "num")],
                    tr_rows) if tr_rows else "")
    states = " · ".join(f'<a href="/queue?state={e(quote(k))}">{e(k.replace("_", " "))} {v}</a>'
                        for k, v in dg.get("states", {}).items())

    body = f"""
<section aria-labelledby="h-numbers">
<h2 id="h-numbers" class="sr-only">Headline numbers</h2>
<dl class="stats">{stat_html}</dl>
<p class="states">{states or "The queue is empty."}</p>
</section>
<section aria-labelledby="h-chart"><h2 id="h-chart">Last 14 days</h2>{bar_chart(dg["series"])}</section>
<div class="cols">
<section aria-labelledby="h-needs">
<h2 id="h-needs">Needs attention</h2>
{warn_html}
<h3>Sign-ins by portal</h3>{auth}
<h3>Approvals pending</h3>{appr}
<h3>Needs a check <span class="count">{needs["needs_check"]}</span></h3>
{job_list(att.get("needs_check", []), "Nothing is waiting for a manual check.")}
<h3>Waiting for your answer <span class="count">{needs["human"]}</span></h3>
{job_list(att.get("blocked_human", []), "No question is waiting for you.")}
<h3>Technical blocks <span class="count">{needs["technical"]}</span></h3>
{job_list(att.get("blocked_technical", []), "No technical block.")}
</section>
<section aria-labelledby="h-coming">
<h2 id="h-coming">Coming up</h2>
<h3>Deadlines</h3>{deadlines}
<h3>Follow-ups</h3>{followups}
{f'<h3>By track</h3>{tracks}' if tracks else ''}
</section>
</div>"""
    return page(ctx, "Overview", "overview", body,
                lead=f"Numbers for {e(dg['date'])}. Replies, interviews and offers come from the outcomes ledger; "
                     f"an application counts as submitted only with the employer's confirmation.")


# ---------------------------------------------------------------- queue

def _options(values, selected: str, all_label: str) -> str:
    opts = [f'<option value="">{e(all_label)}</option>']
    for v, label in values:
        sel = " selected" if v == selected else ""
        opts.append(f'<option value="{e(v)}"{sel}>{e(label)}</option>')
    return "".join(opts)


def queue_page(ctx: dict, jobs: list[dict], params: dict) -> str:
    states = sorted({j["state"] for j in jobs}, key=lambda s: (STATE_ORDER.get(s, 99), s))
    tracks = sorted({(j.get("track") or "", j.get("track_label") or j.get("track") or "") for j in jobs if j.get("track")},
                    key=lambda x: x[1])
    sources = sorted({j.get("source") or "" for j in jobs if j.get("source")})
    p = {k: (params.get(k) or [""])[0] for k in ("state", "track", "source", "q", "sort", "dir")}
    sort = p["sort"] if p["sort"] in ("fit", "posted", "employer", "state") else "fit"
    direction = p["dir"] if p["dir"] in ("asc", "desc") else ("asc" if sort in ("employer", "state") else "desc")

    def key(j):
        if sort == "fit":
            return (j.get("fit") is None, j.get("fit") or 0)
        if sort == "posted":
            return (not j.get("posted"), j.get("posted") or "")
        if sort == "state":
            return (STATE_ORDER.get(j["state"], 99), j["state"])
        return ((j.get("employer") or "").lower(), (j.get("title") or "").lower())

    ordered = sorted(jobs, key=key, reverse=(direction == "desc"))
    if direction == "desc":       # keep rows without a value at the end either way
        ordered = sorted(ordered, key=lambda j: (sort == "fit" and j.get("fit") is None) or
                         (sort == "posted" and not j.get("posted")))

    def visible(j):
        text = " ".join(str(j.get(k) or "") for k in ("employer", "title", "location", "id", "reason")).lower()
        return ((not p["state"] or j["state"] == p["state"]) and (not p["track"] or j.get("track") == p["track"])
                and (not p["source"] or j.get("source") == p["source"]) and (not p["q"] or p["q"].lower() in text))

    rows = []
    for j in ordered:
        st = j["state"]
        why = ""
        if st in qmod.BLOCKED or st in ("needs_check", "retry_wait", "excluded"):
            why = f'<code>{e(j.get("reason"))}</code>'
            if j.get("action"):
                why += f'<span class="action-text">{e(j.get("action"))}</span>'
            if st == "retry_wait" and j.get("next_attempt_at"):
                why += f'<span class="action-text">retry after {e(j["next_attempt_at"])}</span>'
        text = " ".join(str(j.get(k) or "") for k in ("employer", "title", "location", "id", "reason")).lower()
        hidden = "" if visible(j) else " hidden"
        rows.append(
            f'<tr data-state="{e(st)}" data-track="{e(j.get("track"))}" data-source="{e(j.get("source"))}" '
            f'data-fit="{e(fit_txt(j.get("fit")))}" data-posted="{e((j.get("posted") or "")[:10])}" '
            f'data-employer="{e((j.get("employer") or "").lower())}" data-rank="{STATE_ORDER.get(st, 99)}" '
            f'data-text="{e(text)}"{hidden}>'
            f'<td>{role_link(j["id"], j.get("employer", ""), j.get("title", ""))}'
            f'<span class="sub">{e(j.get("location"))}</span></td>'
            f'<td>{badge(st)}</td><td class="wrap">{why}</td>'
            f'<td class="num">{fit_txt(j.get("fit"))}</td><td>{e(j.get("lane"))}</td>'
            f'<td>{e(j.get("track_label"))}</td><td>{e(j.get("source"))}</td>'
            f'<td class="nowrap">{e((j.get("posted") or "")[:10])}</td>'
            f'<td>{ext_link(j.get("apply_url") or j.get("url") or "", "Open")}</td></tr>')
    shown = sum(1 for j in jobs if visible(j))
    sort_opts = "".join(f'<option value="{k}"{" selected" if k == sort else ""}>{label}</option>'
                        for k, label in (("fit", "Fit"), ("posted", "Posted"), ("employer", "Employer"),
                                         ("state", "State")))
    dir_opts = "".join(f'<option value="{k}"{" selected" if k == direction else ""}>{label}</option>'
                       for k, label in (("desc", "Descending"), ("asc", "Ascending")))
    controls = f"""<form class="filters" method="get" action="/queue" role="search" aria-label="Filter the queue" id="queue-filters">
<div class="field"><label for="f-state">State</label><select id="f-state" name="state">{_options([(s, s.replace('_', ' ')) for s in states], p['state'], 'All states')}</select></div>
<div class="field"><label for="f-track">Track</label><select id="f-track" name="track">{_options(tracks, p['track'], 'All tracks')}</select></div>
<div class="field"><label for="f-source">Source</label><select id="f-source" name="source">{_options([(s, s) for s in sources], p['source'], 'All sources')}</select></div>
<div class="field grow"><label for="f-q">Search</label><input id="f-q" name="q" type="search" value="{e(p['q'])}" placeholder="Employer, role, location, id" autocomplete="off"></div>
<div class="field"><label for="f-sort">Sort by</label><select id="f-sort" name="sort">{sort_opts}</select></div>
<div class="field"><label for="f-dir">Order</label><select id="f-dir" name="dir">{dir_opts}</select></div>
<div class="field submit"><button type="submit" class="btn">Apply</button></div>
</form>
<p class="count-line" id="queue-count" role="status" aria-live="polite">Showing {shown} of {len(jobs)} jobs</p>"""
    tbl = table("Every job in the queue", [("Role", ""), ("State", ""), ("Reason and next step", ""), ("Fit", "num"),
                                            ("Lane", ""), ("Track", ""), ("Source", ""), ("Posted", ""), ("Link", "")],
                rows, cls="queue", hide_caption=True)
    body = controls + (tbl if jobs else empty("The queue is empty. Run jobveyra discover and jobveyra evaluate."))
    return page(ctx, "Queue", "queue", body,
                lead="Every job with exactly one state and the reason for it. Blocked rows say what unblocks them.")


# ---------------------------------------------------------------- job detail

def job_page(ctx: dict, d: dict) -> str:
    j = d["job"]
    jid = j["id"]
    nxt = job_href(jid)
    fields = [("State", badge(j["state"])), ("Fit", e(fit_txt(j.get("fit"))) or "–"), ("Lane", e(j.get("lane")) or "–"),
              ("Track", e(j.get("track_label")) or "–"), ("Source", e(j.get("source")) or "–"),
              ("Portal", e(j.get("portal")) or "–"), ("Location", e(j.get("location")) or "–"),
              ("Posted", e((j.get("posted") or "")[:10]) or "–"), ("Deadline", e((j.get("deadline") or "")[:10]) or "–"),
              ("Requisition", e(j.get("req_id")) or "–"), ("Package", f'<code>{e(j.get("package"))}</code>' if j.get("package") else "–"),
              ("Job id", f'<code>{e(jid)}</code>')]
    if j.get("reason"):
        fields.insert(1, ("Reason", f'<code>{e(j["reason"])}</code>'))
    if j.get("action"):
        fields.insert(2, ("Next step", e(j["action"])))
    if j.get("confirmation"):
        fields.append(("Confirmation", e(j["confirmation"])))
    if j.get("submitted_at"):
        fields.append(("Submitted at", e(j["submitted_at"])))
    if j.get("last_error"):
        fields.append(("Last error", e(j["last_error"])))
    dl = "".join(f'<div><dt>{k}</dt><dd>{v}</dd></div>' for k, v in fields)
    links = " · ".join(x for x in (ext_link(j.get("url") or "", "Posting page"),
                                   ext_link(j.get("apply_url") or "", "Application page")
                                   if j.get("apply_url") and j.get("apply_url") != j.get("url") else "") if x)
    sub = d["submission"]
    gate = (f'<p class="gate"><strong>Submission gate</strong> under <code>{e(sub["policy"])}</code>: '
            f'{"may be submitted" if sub["allowed"] else "may not be submitted now"} ({e(sub["why"])}).</p>')

    acts = d.get("actions", [])
    forms = []
    if "outcome" in acts:
        opts = "".join(f'<option value="{o}">{o.replace("_", " ")}</option>' for o in oc.OUTCOMES)
        forms.append(form(ctx, "outcome", nxt, f"""<h3>Record an employer response</h3>
<input type="hidden" name="id" value="{e(jid)}">
<div class="field"><label for="o-kind">Outcome</label><select id="o-kind" name="outcome" required>{opts}</select></div>
<div class="field grow"><label for="o-note">Note <span class="opt">(optional)</span></label><input id="o-note" name="note" maxlength="1000" autocomplete="off"></div>
<div class="field submit"><button class="btn btn-primary" type="submit">Record outcome</button></div>"""))
    if "check" in acts:
        forms.append(form(ctx, "check", nxt, f"""<h3>Resolve the manual check</h3>
<p class="hint">Open the portal's My Applications page. Record what you saw there; nothing is resubmitted from here.</p>
<input type="hidden" name="id" value="{e(jid)}">
<div class="field grow"><label for="c-ev">What you saw <span class="opt">(used as the confirmation when found)</span></label><input id="c-ev" name="evidence" maxlength="500" autocomplete="off"></div>
<div class="field submit"><button class="btn btn-primary" type="submit" name="found" value="1">Found on the portal</button>
<button class="btn" type="submit" name="found" value="0">Not found</button></div>"""))
    if "unblock" in acts:
        forms.append(form(ctx, "unblock", nxt, f"""<h3>Release this job</h3>
<p class="hint">Use this once the blocker is fixed (signed in, question answered).</p>
<input type="hidden" name="id" value="{e(jid)}">
<div class="field submit"><button class="btn" type="submit">Unblock</button></div>"""))
    if "block" in acts:
        forms.append(form(ctx, "block", nxt, f"""<h3>Hold this job</h3>
<input type="hidden" name="id" value="{e(jid)}">
<div class="field grow"><label for="b-reason">Reason code</label><input id="b-reason" name="reason" required maxlength="200" placeholder="hold:salary question" autocomplete="off" aria-describedby="b-help"></div>
<p class="hint" id="b-help"><code>hold:&lt;question&gt;</code> waits for you, <code>auth:&lt;portal&gt;</code> holds every job on that sign-in, anything else is a technical block.</p>
<div class="field submit"><button class="btn" type="submit">Block</button></div>"""))
    forms_html = "".join(f for f in forms if f)
    actions = (f'<section aria-labelledby="h-act"><h2 id="h-act">Actions</h2>{read_only_note(ctx)}{forms_html}</section>'
               if acts else "")

    ev_md = d.get("evaluation_markdown") or ""
    evaluation = (f'<div class="md">{render_md(ev_md, base_level=3)}</div>' if ev_md
                  else empty("No evaluation report yet. Run jobveyra evaluate for this job."))
    p = d.get("posting")
    if p and p.get("text"):
        posting = (f'<details class="posting"><summary>Cached posting text ({len(p["text"].split())} words)</summary>'
                   f'<div class="posting-text">{e(p["text"])}</div></details>')
    else:
        posting = empty("No cached posting text.")
    ev_rows = [f'<tr><td class="nowrap">{e(x["ts"])}</td><td>{e(x["from"]) or "–"}</td><td>{badge(x["to"])}</td>'
               f'<td class="wrap">{e(x["note"])}</td></tr>' for x in d.get("events", [])]
    history = (table("State changes", [("Time", ""), ("From", ""), ("To", ""), ("Note", "")], ev_rows, hide_caption=True)
               if ev_rows else empty("No recorded state changes."))
    oc_rows = [f'<tr><td class="nowrap">{e(r["at"])}</td><td>{e(r["outcome"].replace("_", " "))}</td>'
               f'<td class="wrap">{e(r.get("stage_note"))}</td></tr>' for r in d.get("outcomes", [])]
    outs = (table("Employer responses", [("Time", ""), ("Outcome", ""), ("Note", "")], oc_rows, hide_caption=True)
            if oc_rows else empty("No employer response recorded."))

    body = f"""<p class="crumbs"><a href="/queue">Queue</a> / <code>{e(jid)}</code></p>
<p class="subtitle"><span class="emp">{e(j.get("employer"))}</span> {f'<span class="links">{links}</span>' if links else ''}</p>
<section aria-labelledby="h-status"><h2 id="h-status">Status</h2><dl class="fields">{dl}</dl>{gate}</section>
{actions}
<section aria-labelledby="h-eval"><h2 id="h-eval">Evaluation</h2>{evaluation}</section>
<section aria-labelledby="h-post"><h2 id="h-post">Posting</h2>{posting}</section>
<section aria-labelledby="h-hist"><h2 id="h-hist">History</h2>{history}</section>
<section aria-labelledby="h-out"><h2 id="h-out">Outcomes</h2>{outs}</section>"""
    return page(ctx, j.get("title") or jid, "queue", body)


# ---------------------------------------------------------------- review

def _items_table(caption: str, items: list[dict], *, choose: str = "") -> str:
    rows = []
    for k, it in enumerate(items):
        note = ("job no longer in the queue" if it["missing"] else
                "posting changed since staging" if it["changed"] else "")
        pick = ""
        if choose:
            pick = (f'<td><input type="checkbox" id="{e(choose)}-{k}" name="exclude" value="{e(it["id"])}">'
                    f'<label for="{e(choose)}-{k}" class="sr-only">Leave out {e(it["employer"])} {e(it["title"])}</label></td>')
        who = (f"<code>{e(it['id'])}</code>" if it["missing"] else role_link(it["id"], it["employer"], it["title"]))
        rows.append(f'<tr>{pick}<td>{who}</td>'
                    f'<td class="num">{fit_txt(it["fit"])}</td><td>{badge(it["state"]) if it["state"] else "–"}</td>'
                    f'<td>{ext_link(it["url"], "Open")}</td><td class="wrap">{e(note)}</td></tr>')
    heads = ([("Leave out", "")] if choose else []) + [("Role", ""), ("Fit", "num"), ("State", ""), ("Link", ""),
                                                       ("Note", "")]
    return table(caption, heads, rows, hide_caption=True)


def review_page(ctx: dict, r: dict) -> str:
    pol = r["policy"]
    mode = pol["submission"]
    banner = f"""<div class="policy policy-{cls_token(mode)}" role="note" aria-labelledby="h-policy">
<p class="policy-label" id="h-policy">Submission mode</p>
<p class="policy-mode"><code>{e(mode)}</code></p>
<p>{e(POLICY_TEXT.get(mode, ""))}</p>
<p class="hint">Batches hold up to {pol["batch_size"]} jobs; an approval lasts {pol["approval_ttl_hours"]} hours;
at most {pol["max_per_day"]} submissions a day. In every mode an application counts as sent only when the
employer's confirmation is recorded.</p>
</div>"""
    batch_mode = mode == "batch_approve"
    if batch_mode:
        stage = form(ctx, "stage", "/review", f"""<p><span class="count">{r["ready_uncovered"]}</span> of {r["ready"]} ready job(s) are not covered by a live approval.</p>
<div class="field submit"><button class="btn btn-primary" type="submit"{" disabled" if not r["ready_uncovered"] else ""}>Stage a batch</button></div>""",
                     label="Stage a new batch")
        plain = "" if stage else f"<p>{r['ready_uncovered']} ready job(s) not covered by a live approval.</p>"
        stage_html = (f'<section aria-labelledby="h-stage"><h2 id="h-stage">Stage a batch</h2>{read_only_note(ctx)}'
                      f'{stage}{plain}</section>')
    else:
        stage_html = (f'<section aria-labelledby="h-stage"><h2 id="h-stage">Stage a batch</h2>'
                      f'<p>Batch approval is not used under <code>{e(mode)}</code>. Change <code>policy.submission</code> '
                      f'in <code>jobveyra.yml</code> to <code>batch_approve</code> to review before anything is sent.</p></section>')

    staged = []
    for b in r["staged"]:
        tbl = _items_table(f"Jobs in batch {b['batch']}", b["items"], choose=f"x-{b['batch']}" if batch_mode and not ctx.get("read_only") else "")
        page_note = f'<p class="hint">Static review page: <code>{e(b["review_page"])}</code></p>' if b["review_page"] else ""
        if batch_mode and not ctx.get("read_only"):
            inner = (f'<input type="hidden" name="batch" value="{e(b["batch"])}">{tbl}'
                     f'<div class="field submit"><button class="btn btn-primary" type="submit">Approve batch</button></div>')
            approve = form(ctx, "approve", "/review", inner, label=f"Approve batch {b['batch']}",
                           confirm=f"Approve batch {b['batch']} for {pol['approval_ttl_hours']} hours, minus any job you ticked?")
            discard = form(ctx, "revoke", "/review", f'<input type="hidden" name="batch" value="{e(b["batch"])}">'
                           f'<div class="field submit"><button class="btn" type="submit">Discard batch</button></div>',
                           label=f"Discard batch {b['batch']}", cls="action inline")
            content = approve + discard
        else:
            content = tbl
        staged.append(f'<article class="batch" aria-labelledby="sb-{e(b["batch"])}">'
                      f'<h3 id="sb-{e(b["batch"])}">Batch <code>{e(b["batch"])}</code></h3>'
                      f'<p class="meta">Staged {e(b["at"])} · {len(b["items"])} job(s). Tick a job to leave it out.</p>'
                      f'{page_note}{content}</article>')
    staged_html = "".join(staged) or empty("No staged batch is waiting.")

    live = []
    for b in r["live"]:
        revoke = form(ctx, "revoke", "/review", f'<input type="hidden" name="batch" value="{e(b["batch"])}">'
                      f'<div class="field submit"><button class="btn" type="submit">Revoke</button></div>',
                      confirm=f"Revoke the approval for batch {b['batch']}?", label=f"Revoke batch {b['batch']}",
                      cls="action inline")
        live.append(f'<article class="batch" aria-labelledby="lb-{e(b["batch"])}">'
                    f'<h3 id="lb-{e(b["batch"])}">Batch <code>{e(b["batch"])}</code></h3>'
                    f'<p class="meta">Approved by {e(b["by"])} at {e(b["at"])} · expires {e(b["expires"])} · '
                    f'{len(b["items"])} job(s)</p>{_items_table("Jobs approved in " + b["batch"], b["items"])}{revoke}</article>')
    live_html = "".join(live) or empty("No live approval.")
    hist_rows = [f'<tr><td>{e(h["type"])}</td><td><code>{e(h["batch"])}</code></td><td class="nowrap">{e(h["at"])}</td>'
                 f'<td>{e(h["by"])}</td><td class="nowrap">{e(h["expires"])}</td></tr>' for h in r["history"]]
    hist = (table("Approval history", [("Event", ""), ("Batch", ""), ("At", ""), ("By", ""), ("Expires", "")],
                  hist_rows, hide_caption=True) if hist_rows else empty("No approvals recorded yet."))
    body = f"""{banner}
{stage_html}
<section aria-labelledby="h-staged"><h2 id="h-staged">Waiting for approval</h2>{staged_html}</section>
<section aria-labelledby="h-live"><h2 id="h-live">Live approvals</h2>{live_html}</section>
<section aria-labelledby="h-hist"><h2 id="h-hist">History</h2>{hist}</section>"""
    return page(ctx, "Review", "review", body,
                lead="Approving records your decision. The agent still leases one job at a time and submits only what "
                     "a live approval covers.")


# ---------------------------------------------------------------- insights

def insights_page(ctx: dict, ins: dict) -> str:
    f = ins["funnel"]
    top = max(f["counts"].get("discovered", 0), 1)
    f_rows = [f'<tr><th scope="row">{e(s["stage"])}</th><td class="num">{s["n"]}</td>'
              f'<td>{hbar(s["n"] / top)}</td><td class="num">{pct(s["from_previous"])}</td>'
              f'<td class="num">{pct(s["from_discovered"], 1)}</td></tr>' for s in f["stages"]]
    conv = f["conversion"]
    funnel_html = table("Funnel", [("Stage", ""), ("Jobs", "num"), ("", ""), ("From previous", "num"),
                                   ("From discovered", "num")], f_rows, hide_caption=True)
    med = f["median_days_to_reply"]
    funnel_note = (f'<p class="meta">Reply rate {pct(conv["reply_rate"])} · interview rate {pct(conv["interview_rate"])} · '
                   f'median {e(med) if med is not None else "–"} days to first reply ({f["replies_timed"]} timed)'
                   + (f' · {f["unmatched_outcomes"]} outcome(s) recorded for jobs not marked submitted' if f["unmatched_outcomes"] else "")
                   + "</p>")

    pats = ins["patterns"]
    p_rows = [f'<tr><td>{e(r["dimension"])}</td><td>{e(r["value"])}</td><td class="num">{r["n"]}</td>'
              f'<td class="num">{r["replied"]}</td><td class="num">{pct(r["rate"])}</td>'
              f'<td class="nowrap">{pct(r["low"])} – {pct(r["high"])}</td>'
              f'<td>{interval(r["low"], r["high"], r["rate"], r["overall"])}</td>'
              f'<td><span class="signal signal-{cls_token(r["signal"])}">{e(r["signal"])}</span></td></tr>' for r in pats]
    patterns_html = (table("Response patterns", [("Dimension", ""), ("Value", ""), ("Sent", "num"), ("Replied", "num"),
                                                 ("Rate", "num"), ("95% interval", ""), ("", ""), ("Signal", "")],
                           p_rows, hide_caption=True)
                     if p_rows else empty("No submissions yet."))
    overall = pats[0]["overall"] if pats else None
    pat_note = (f'<p class="meta">Wilson 95% intervals. The tick marks the overall reply rate ({pct(overall)}). A group shows '
                f'<em>above</em> or <em>below</em> only with at least {ins.get("patterns_min_n", 8)} submissions and an '
                f'interval that excludes the overall rate.</p>')

    cal = ins["calibration"]
    mono = {True: "yes", False: "no", None: "–"}[cal.get("monotonic")]
    cal_stats = (f'<dl class="stats small"><div class="stat"><dt>Scored submissions</dt><dd><span class="num-big">{cal["n"]}</span></dd></div>'
                 f'<div class="stat"><dt>Brier score</dt><dd><span class="num-big">{e(cal["brier"]) if cal["brier"] is not None else "–"}</span><span class="hint">lower is better</span></dd></div>'
                 f'<div class="stat"><dt>AUC</dt><dd><span class="num-big">{e(cal["auc"]) if cal["auc"] is not None else "–"}</span><span class="hint">0.5 is chance</span></dd></div>'
                 f'<div class="stat"><dt>Rises with fit</dt><dd><span class="num-big">{mono}</span></dd></div></dl>')
    cal_html = cal_stats + calibration_chart(cal) + f'<p class="callout-plain">{e(cal["recommendation"])}</p>'

    sk = ins["skills"]
    d_rows = [f'<tr><th scope="row">{e(r["term"])}</th><td class="num">{r["postings"]}</td>'
              f'<td>{hbar(r["postings"] / max(sk["postings"], 1))}</td><td>{"yes" if r["held"] else "no"}</td></tr>'
              for r in sk["demand"]]
    g_rows = [f'<tr><th scope="row">{e(r["term"])}</th><td class="num">{r["postings"]}</td></tr>' for r in sk["gaps"]]
    demand = (table("Most requested terms", [("Term", ""), ("Postings", "num"), ("", ""), ("In your tracks", "")], d_rows,
                    hide_caption=True) if d_rows else empty("No cached posting text to count."))
    gaps = (table("Gaps", [("Term", ""), ("Postings", "num")], g_rows, hide_caption=True)
            if g_rows else empty("No gap among the terms counted."))
    body = f"""<section aria-labelledby="h-funnel"><h2 id="h-funnel">Funnel</h2>{funnel_html}{funnel_note}</section>
<section aria-labelledby="h-pat"><h2 id="h-pat">Patterns</h2>{pat_note}{patterns_html}</section>
<section aria-labelledby="h-cal"><h2 id="h-cal">Score calibration</h2>{cal_html}</section>
<section aria-labelledby="h-skills"><h2 id="h-skills">Skill demand</h2>
<p class="meta">Across {sk["postings"]} cached posting(s). Held terms are the skills listed on your tracks.</p>
<div class="cols"><div><h3>Most requested</h3>{demand}</div><div><h3>Gaps</h3>{gaps}</div></div></section>"""
    return page(ctx, "Insights", "insights", body,
                lead="What the outcomes say so far. Small samples are shown as they are, never read as patterns.")


# ---------------------------------------------------------------- errors

def error_page(ctx: dict, status: int, message: str, back: str = "/") -> str:
    body = f'<p class="error-msg">{e(message)}</p><p><a href="{e(back)}">Go back</a></p>'
    return page(ctx, f"Error {status}", "", body)
