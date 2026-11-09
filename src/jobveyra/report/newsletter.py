"""Daily newsletter: email-safe HTML, plain text, an animated chart and an SMTP sender.

``build`` writes into ``out_dir``:
  newsletter.html   for sending: images referenced as cid:chart and cid:chartdark
  preview.html      the same page with relative image paths, for a browser
  newsletter.txt    the plain-text part
  chart.gif, chart-dark.gif, digest.json

The HTML uses table layout and simple CSS. The dark chart is hidden by default
(``display:none``) and swapped in by a ``prefers-color-scheme: dark`` media query, so clients
without media-query support show the light chart only.

SMTP settings come from the environment: SMTP_HOST, SMTP_PORT (587), SMTP_USER,
SMTP_PASSWORD, NEWSLETTER_TO (comma-separated), NEWSLETTER_FROM (defaults to SMTP_USER).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from . import digest as digest_mod

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
CSS = f"""
body{{margin:0;padding:0;background:#f6f8fa;}}
.wrap{{width:100%;background:#f6f8fa;}}
.card{{background:#ffffff;border:1px solid #d0d7de;border-radius:8px;}}
h1{{font:600 20px/1.3 {FONT};color:#1f2328;margin:0;}}
h2{{font:600 13px/1.4 {FONT};color:#1f2328;margin:28px 0 8px;text-transform:uppercase;letter-spacing:.06em;}}
p,li,td{{font:400 14px/1.55 {FONT};color:#1f2328;}}
.muted{{color:#656d76;}}
.kpi td{{text-align:left;padding:0 16px 0 0;vertical-align:top;}}
.kpi .n{{font:600 26px/1.1 {FONT};color:#1f2328;}}
.kpi .l{{font-size:12px;color:#656d76;}}
ul{{margin:0;padding-left:18px;}}
table.t{{border-collapse:collapse;width:100%;}}
table.t td,table.t th{{border-top:1px solid #d0d7de;padding:6px 8px 6px 0;text-align:left;font:400 13px/1.4 {FONT};color:#1f2328;}}
table.t th{{font-weight:600;color:#656d76;border-top:0;}}
a{{color:#0969da;text-decoration:none;}}
.foot{{border-top:1px solid #d0d7de;}}
.dark-img{{display:none;}}
@media (prefers-color-scheme: dark){{
 body,.wrap{{background:#010409 !important;}}
 .card{{background:#0d1117 !important;border-color:#30363d !important;}}
 h1,h2,p,li,td,.kpi .n,table.t td{{color:#e6edf3 !important;}}
 .muted,.kpi .l,table.t th{{color:#9198a1 !important;}}
 table.t td,table.t th,.foot{{border-color:#30363d !important;}}
 a{{color:#4493f8 !important;}}
 .light-img{{display:none !important;}}
 .dark-img{{display:block !important;max-height:none !important;}}
}}
"""


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _day(iso: str, weekday: bool = True) -> str:
    d = dt.date.fromisoformat(iso[:10])
    return f"{d.strftime('%a') + ' ' if weekday else ''}{d.strftime('%b')} {d.day}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def subject(dg: dict) -> str:
    t = dg["totals"]
    return f"Job search · {_day(dg['date'], weekday=False)} · {t['submitted']} submitted, {_plural(t['interviews'], 'interview')}"


def needs_lines(dg: dict) -> list[str]:
    """Plain-text 'needs attention' items, most urgent first (shared with status and notify)."""
    n = dg["needs"]
    out = []
    for g in n["auth"]:
        bits = [_plural(g["count"], "job") + " waiting"]
        if g.get("best_fit") is not None:
            bits.append(f"best fit {g['best_fit']}")
        if g.get("earliest_deadline"):
            bits.append(f"earliest deadline {_day(g['earliest_deadline'])}")
        out.append(f"Sign in to {g['scope']}: {', '.join(bits)}")
    if n.get("approvals_pending"):
        out.append(f"{_plural(n['approvals_pending'], 'application')} ready for your approval")
    if n.get("human"):
        out.append(f"{_plural(n['human'], 'job')} waiting for your answer")
    if n.get("needs_check"):
        out.append(f"{_plural(n['needs_check'], 'job')} to check on the portal before any resubmission")
    if n.get("technical"):
        out.append(f"{_plural(n['technical'], 'job')} blocked by a form or upload problem")
    out += list(dg.get("flags", {}).get("warnings", []))
    return out


def coming_lines(dg: dict) -> list[str]:
    c = dg["coming_up"]
    out = [f"{_day(d['date'])} · deadline · {d['employer']}, {d['title']}" for d in c["deadlines"]]
    out += [f"Follow up · {f['employer']}, {f['title']} ({f['days_waiting']} days since applying)" for f in c["followups"]]
    return out


def render_html(digest: dict, chart_light_src: str, chart_dark_src: str, cfg=None) -> str:
    dg, t = digest, digest["totals"]
    kpis = [("Submitted", t["submitted"]), ("Last 7 days", dg["last7"]), ("Replies", t["replies"]),
            ("Interviews", t["interviews"]), ("Offers", t["offers"])]
    who = f" for {cfg.candidate.name}" if cfg is not None and getattr(cfg.candidate, "name", "") else ""
    P = [f'<h1>Job search · {_e(_day(dg["date"]))}</h1>',
         f'<p class="muted" style="margin:6px 0 20px">Daily digest{_e(who)}. Reply rate {t["reply_rate"]}% '
         f'across {_plural(t["submitted"], "submitted application")}.</p>',
         '<table class="kpi" role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
         + "".join(f'<td><div class="n">{n}</div><div class="l">{_e(label)}</div></td>' for label, n in kpis)
         + "</tr></table>"]
    if chart_light_src:
        alt = f"Applications submitted per day over the last {len(dg['series'])} days"
        P.append(f'<div style="margin-top:24px"><img class="light-img" src="{_e(chart_light_src)}" width="536" alt="{_e(alt)}" '
                 f'style="display:block;width:100%;max-width:536px;height:auto;border:0">'
                 + (f'<img class="dark-img" src="{_e(chart_dark_src)}" width="536" alt="{_e(alt)}" '
                    f'style="display:none;max-height:0;overflow:hidden;mso-hide:all;width:100%;max-width:536px;height:auto;border:0">'
                    if chart_dark_src else "") + "</div>")

    P.append("<h2>Yesterday</h2>")
    if dg.get("yesterday"):
        P.append("<ul>" + "".join(f"<li>{_e(s['employer'])} · {_e(s['title'])}</li>" for s in dg["yesterday"]) + "</ul>")
    else:
        P.append('<p class="muted" style="margin:0">No applications were submitted.</p>')
    needs = needs_lines(dg)
    if needs:
        P.append("<h2>Needs attention</h2><ul>" + "".join(f"<li>{_e(x)}</li>" for x in needs) + "</ul>")
    soon = coming_lines(dg)
    if soon:
        P.append("<h2>Coming up</h2><ul>" + "".join(f"<li>{_e(x)}</li>" for x in soon) + "</ul>")
    if dg["by_track"]:
        P.append('<h2>By track</h2><table class="t" role="presentation" cellpadding="0" cellspacing="0" border="0">'
                 "<tr><th>Track</th><th>Submitted</th><th>Replies</th><th>Avg fit</th></tr>"
                 + "".join(f"<tr><td>{_e(r['label'])}</td><td>{r['sent']}</td><td>{r['replies']}</td>"
                           f"<td>{'' if r['avg_fit'] is None else str(r['avg_fit']) + ' / 100'}</td></tr>" for r in dg["by_track"])
                 + "</table>")
        P.append('<p class="muted" style="font-size:12px;margin:6px 0 0">Fit is a per-job match score from 0 to 100, not a count.</p>')
    body = "\n".join(P)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>{_e(subject(dg))}</title><style>{CSS}</style></head>
<body><table class="wrap" role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td align="center" style="padding:24px 12px">
<table class="card" role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px">
<tr><td style="padding:28px 32px">
{body}
</td></tr>
<tr><td class="foot" style="padding:16px 32px"><p class="muted" style="margin:0;font-size:12px">Generated by jobveyra from your local queue and outcomes ledger.</p></td></tr>
</table></td></tr></table></body></html>
"""


def render_text(digest: dict) -> str:
    dg, t = digest, digest["totals"]
    L = [f"Job search · {_day(dg['date'])}", "",
         f"Submitted {t['submitted']} · last 7 days {dg['last7']} · replies {t['replies']} · "
         f"interviews {t['interviews']} · offers {t['offers']}",
         f"Reply rate {t['reply_rate']}%", "", "Yesterday"]
    L += [f"- {s['employer']} · {s['title']}" for s in dg.get("yesterday", [])] or ["- No applications were submitted."]
    for head, items in (("Needs attention", needs_lines(dg)), ("Coming up", coming_lines(dg))):
        if items:
            L += ["", head] + [f"- {x}" for x in items]
    if dg["by_track"]:
        L += ["", "By track"]
        L += [f"- {r['label']}: {r['sent']} submitted, {r['replies']} replies"
              + ("" if r["avg_fit"] is None else f", avg fit {r['avg_fit']} / 100") for r in dg["by_track"]]
    return "\n".join(L) + "\n"


def build(cfg, q, today, out_dir) -> dict:
    """Write every newsletter file; returns ``{"digest", "subject", "files", "charts"}``.
    Without Pillow the chart files are skipped and the HTML has no image."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dg = digest_mod.build(cfg, q, today)
    charts = True
    try:
        from .chart import render_pair
        render_pair(dg["series"], out)
    except ImportError:
        charts = False
    files = {
        "newsletter.html": render_html(dg, "cid:chart" if charts else "", "cid:chartdark" if charts else "", cfg),
        "preview.html": render_html(dg, "chart.gif" if charts else "", "chart-dark.gif" if charts else "", cfg),
        "newsletter.txt": render_text(dg),
        "digest.json": json.dumps({**dg, "subject": subject(dg)}, indent=2, ensure_ascii=False, default=str) + "\n",
    }
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    names = sorted(files) + (["chart-dark.gif", "chart.gif"] if charts else [])
    return {"digest": dg, "subject": subject(dg), "files": [str(out / n) for n in names], "charts": charts}


def message(out_dir, sender: str, recipients: list[str]) -> EmailMessage:
    """multipart/alternative (text, multipart/related (html, inline GIFs))."""
    out = Path(out_dir)
    dg = json.loads((out / "digest.json").read_text(encoding="utf-8"))
    msg = EmailMessage()
    msg["Subject"] = dg.get("subject") or subject(dg)
    msg["From"] = sender
    msg["To"] = ", ".join(recipients) if recipients else "undisclosed-recipients:;"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(sender.rsplit("@", 1)[-1] if "@" in sender else "jobveyra.local").strip(">"))
    msg.set_content((out / "newsletter.txt").read_text(encoding="utf-8"))
    msg.add_alternative((out / "newsletter.html").read_text(encoding="utf-8"), subtype="html")
    html_part = msg.get_payload()[1]
    for cid, name in (("chart", "chart.gif"), ("chartdark", "chart-dark.gif")):
        p = out / name
        if p.is_file():
            html_part.add_related(p.read_bytes(), maintype="image", subtype="gif", cid=f"<{cid}>",
                                  filename=name, disposition="inline")
    return msg


def send(out_dir, env=os.environ, dry_run: bool = False) -> str:
    """Send the built newsletter. Returns a one-line result; never raises on SMTP errors.
    ``dry_run`` writes ``newsletter.eml`` and sends nothing."""
    out = Path(out_dir)
    if not (out / "digest.json").is_file():
        return f"Not sent: no newsletter in {out}; build it first"
    to = [a.strip() for a in (env.get("NEWSLETTER_TO") or "").split(",") if a.strip()]
    sender = env.get("NEWSLETTER_FROM") or env.get("SMTP_USER") or ""
    if dry_run:
        msg = message(out, sender or "jobveyra@localhost", to)
        (out / "newsletter.eml").write_bytes(bytes(msg))
        return f"Dry run: wrote {out / 'newsletter.eml'} ({len(to)} recipient(s)); nothing was sent"
    missing = [k for k, v in (("SMTP_HOST", env.get("SMTP_HOST")), ("NEWSLETTER_TO", to),
                              ("NEWSLETTER_FROM or SMTP_USER", sender)) if not v]
    if env.get("SMTP_USER") and not env.get("SMTP_PASSWORD"):
        missing.append("SMTP_PASSWORD")
    if missing:
        return f"Not sent: missing {', '.join(missing)}"
    try:
        port = int(env.get("SMTP_PORT") or 587)
    except ValueError:
        return f"Not sent: SMTP_PORT {env.get('SMTP_PORT')!r} is not a number"
    msg = message(out, sender, to)
    try:
        with smtplib.SMTP(env["SMTP_HOST"], port, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
            if env.get("SMTP_USER"):
                s.login(env["SMTP_USER"], env.get("SMTP_PASSWORD", ""))
            s.send_message(msg, from_addr=sender, to_addrs=to)
    except (smtplib.SMTPException, OSError) as e:
        return f"Not sent: {type(e).__name__}: {e}"
    return f"Sent \"{msg['Subject']}\" to {len(to)} recipient(s)"
