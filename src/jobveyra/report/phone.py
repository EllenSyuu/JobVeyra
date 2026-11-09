"""A phone-sized page of the search: today's numbers, what needs you, and every application.

``render(cfg, q, today)`` returns one self-contained HTML file (no server, no network, no external
fonts) with the data embedded. It holds no contact details. Open it on a phone, or publish it
somewhere private; regenerate it after each run (``jobveyra phone``).
"""
from __future__ import annotations

import datetime as dt
import html
import json

from . import digest as dg

_STATE_LABEL = {"submitted": "Sent", "ready_to_submit": "Ready", "in_progress": "Sending", "eligible": "To prepare",
                "needs_check": "Check portal", "blocked_auth": "Sign-in", "blocked_human": "Question",
                "blocked_technical": "Stuck", "retry_wait": "Retrying", "discovered": "New", "excluded": "Excluded"}

_CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--mute:#78716c;--line:#e7e5e4;--card:#fff;--accent:#1c1917}
@media (prefers-color-scheme:dark){:root{--bg:#0c0a09;--fg:#f5f5f4;--mute:#a8a29e;--line:#292524;--card:#1c1917;--accent:#f5f5f4}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:640px;margin:0 auto;padding:16px}h1{font-size:20px;margin:4px 0 2px}h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);margin:22px 0 8px}
.sub{color:var(--mute);font-size:13px}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}.kpi b{display:block;font-size:22px}.kpi span{font-size:12px;color:var(--mute)}
ul{list-style:none;margin:0;padding:0}li{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:6px 0}
li small{color:var(--mute);display:block}a{color:inherit}.pill{float:right;font-size:12px;border:1px solid var(--line);border-radius:99px;padding:1px 8px;color:var(--mute)}
.tabs{display:flex;gap:6px;margin-top:16px}.tabs button{flex:1;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);font:inherit}
.tabs button[aria-pressed=true]{border-color:var(--accent);font-weight:600}input,select{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);font:inherit;margin:8px 0}
.hidden{display:none}
"""

_JS = """
const D=JSON.parse(document.getElementById('data').textContent);
const $=s=>document.querySelector(s);
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function list(){const q=$('#q').value.toLowerCase(),f=$('#f').value;
 $('#apps').innerHTML=D.jobs.filter(j=>(!f||j.group===f)&&(!q||(j.employer+' '+j.title).toLowerCase().includes(q)))
 .map(j=>`<li><span class=pill>${esc(j.label)}</span>${j.url?`<a href="${esc(j.url)}">${esc(j.employer)}</a>`:esc(j.employer)}<small>${esc(j.title)}${j.fit!=null?' · fit '+j.fit:''}${j.deadline?' · due '+esc(j.deadline):''}</small></li>`).join('')||'<li>Nothing here.</li>'}
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tabs button').forEach(x=>x.setAttribute('aria-pressed',x===b));
 document.querySelectorAll('section').forEach(s=>s.classList.toggle('hidden',s.id!==b.dataset.tab))});
$('#q').oninput=list;$('#f').onchange=list;list();
"""


def _group(state: str) -> str:
    if state == "submitted":
        return "sent"
    if state in ("blocked_auth", "blocked_human", "blocked_technical", "needs_check"):
        return "needs"
    if state == "excluded":
        return "excluded"
    return "open"


def render(cfg, q, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    d = dg.build(cfg, q, today)
    t = d["totals"]
    jobs = []
    for j in q.all():
        if j["state"] == "discovered":
            continue
        fit = j.get("fit")
        try:
            fit = int(round(float(fit))) if fit not in (None, "") else None
        except (TypeError, ValueError):
            fit = None
        jobs.append({"employer": j.get("employer") or "", "title": j.get("title") or "", "state": j["state"],
                     "label": _STATE_LABEL.get(j["state"], j["state"]), "group": _group(j["state"]), "fit": fit,
                     "deadline": (j.get("deadline") or "")[:10], "url": j.get("url") or "",
                     "updated": j.get("updated_at") or ""})
    jobs.sort(key=lambda j: (j["group"] != "needs", j["group"] == "excluded", j["deadline"] or "9999", -(j["fit"] or 0)))
    needs = []
    for g in d["needs"]["auth"]:
        needs.append(f"Sign in to <b>{html.escape(g['scope'])}</b>: {g['count']} waiting"
                     + (f", due {g['earliest_deadline']}" if g["earliest_deadline"] else ""))
    for k, label in (("human", "question(s) to answer"), ("needs_check", "to check on a portal"),
                     ("technical", "stuck"), ("approvals_pending", "ready for your approval")):
        if d["needs"].get(k):
            needs.append(f"{d['needs'][k]} {label}")
    coming = [f"{html.escape(x['date'])} · {html.escape(x['employer'])}: {html.escape(x['title'])}"
              for x in d["coming_up"]["deadlines"][:8]]
    kpi = "".join(f'<div class=kpi><b>{v}</b><span>{k}</span></div>' for k, v in
                  (("sent", t["submitted"]), ("replies", t["replies"]), ("interviews", t["interviews"]), ("offers", t["offers"])))
    data = json.dumps({"jobs": jobs}, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Job search</title><style>{_CSS}</style></head><body><main>
<h1>Job search</h1><div class=sub>{today.strftime('%a %b')} {today.day} · reply rate {t['reply_rate']}% · {t['open']} open</div>
<div class=kpis>{kpi}</div>
<div class=tabs><button data-tab=today aria-pressed=true>Today</button><button data-tab=all aria-pressed=false>Applications</button></div>
<section id=today><h2>Needs you</h2><ul>{''.join(f'<li>{x}</li>' for x in needs) or '<li>Nothing right now.</li>'}</ul>
<h2>Coming up</h2><ul>{''.join(f'<li>{x}</li>' for x in coming) or '<li>No deadlines in the next two weeks.</li>'}</ul></section>
<section id=all class=hidden><input id=q placeholder="Search employer or title" aria-label="Search">
<select id=f aria-label="Filter"><option value="">All</option><option value=needs>Needs you</option><option value=open>In progress</option>
<option value=sent>Sent</option><option value=excluded>Excluded</option></select><ul id=apps></ul></section>
</main><script type="application/json" id="data">{data}</script><script>{_JS}</script></body></html>
"""
