"""Jobs waiting on a sign-in: what to open, a durable "I signed in" signal, and resuming.

The engine never signs in. A job behind a login waits in ``blocked_auth`` with its *scope*: the
session it needs (``workday:acme`` is one Workday tenant; ``taleo:globex`` one Taleo site).

``waiting(q)``        one row per scope: how many jobs, the earliest deadline, the page to open,
                      and what signing in means on that portal family
``signal(...)``       the candidate says "signed in to <scope>"; stored in state/signals.jsonl,
                      so a signal given while no agent is running is never lost
``pending(ws)``       signals no agent has checked yet
``verify(...)``       an agent checked the portal in the browser: on success the scope's jobs go
                      back to the queue; either way the signal is acknowledged
``wait(...)``         block until a pending signal exists (for a live browser session)
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from . import queue as Q

KINDS = [
    (r"^workday:", "Workday", "Each employer has its own Workday account: Create Account the first time "
                              "(your email and a password you choose), Sign In after that."),
    (r"^taleo:", "Taleo", "Sign in or create a Taleo candidate account for this employer."),
    (r"^successfactors:", "SuccessFactors", "Sign in or create a candidate account on this employer's site."),
    (r"^icims:", "iCIMS", "Sign in with email; iCIMS often sends a one-time code."),
    (r"oraclecloud|^oracle", "Oracle Recruiting", "Sign in with your email; Oracle sends a one-time code."),
    (r"inspira|careers\.un\.org", "UN Careers (Inspira)", "Sign in to your UN Careers account; the personal history "
                                                          "profile is reused across applications."),
    (r"linkedin", "LinkedIn", "Sign in to LinkedIn in the same browser profile the agent uses."),
    (r"indeed", "Indeed", "Sign in to Indeed in the same browser profile the agent uses."),
]


def kind_of(scope: str) -> tuple[str, str]:
    for rx, name, hint in KINDS:
        if re.search(rx, scope or "", re.I):
            return name, hint
    return (scope.split(":")[0] if scope else "portal"), "Open the page and sign in, or create an account."


def _open_url(url: str) -> str:
    u = urlparse(url or "")
    if not u.netloc:
        return url or ""
    if "myworkdayjobs.com" in u.netloc:
        parts = [p for p in u.path.split("/") if p]
        site = parts[1] if len(parts) > 1 and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0] or "") else (parts[0] if parts else "")
        return f"{u.scheme}://{u.netloc}/{site}" if site else f"{u.scheme}://{u.netloc}"
    return url


def waiting(q) -> list[dict]:
    groups: dict[str, dict] = {}
    for j in q.all("blocked_auth"):
        scope = q.scope(j)
        name, hint = kind_of(scope)
        g = groups.setdefault(scope, {"scope": scope, "portal": name, "hint": hint, "jobs": [], "earliest_deadline": "",
                                      "open": _open_url(j.get("apply_url") or j.get("url") or "")})
        g["jobs"].append({"id": j["id"], "employer": j.get("employer"), "title": j.get("title"),
                          "deadline": (j.get("deadline") or "")[:10]})
        d = (j.get("deadline") or "")[:10]
        if d and (not g["earliest_deadline"] or d < g["earliest_deadline"]):
            g["earliest_deadline"] = d
    return sorted(groups.values(), key=lambda g: (g["earliest_deadline"] or "9999", -len(g["jobs"]), g["scope"]))


def _rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def signal(state_dir: Path, scope: str, source: str = "cli") -> dict:
    row = {"ts": Q.iso(Q.now()), "scope": scope, "source": source}
    _append(Path(state_dir) / "signals.jsonl", row)
    return row


def pending(state_dir: Path) -> list[dict]:
    """Signals newer than the last acknowledgement for their scope."""
    sigs = _rows(Path(state_dir) / "signals.jsonl")
    last_ack: dict[str, str] = {}
    for a in _rows(Path(state_dir) / "signal_acks.jsonl"):
        last_ack[a["scope"]] = max(last_ack.get(a["scope"], ""), a.get("ts", ""))
    latest: dict[str, dict] = {}
    for s in sigs:
        if s.get("ts", "") > last_ack.get(s["scope"], ""):
            latest[s["scope"]] = s
    return sorted(latest.values(), key=lambda s: s["ts"])


def verify(q, state_dir: Path, scope: str, *, ok: bool, evidence: str) -> dict:
    """Record what the browser showed. On success the scope's blocked_auth jobs go back to the queue."""
    released = q.unblock(portal=scope, reason_prefix="auth") if ok else []
    _append(Path(state_dir) / "signal_acks.jsonl",
            {"ts": Q.iso(Q.now()), "scope": scope, "ok": ok, "evidence": evidence[:300], "released": len(released)})
    return {"scope": scope, "ok": ok, "released": released}


def wait(state_dir: Path, *, interval: float = 30, timeout: float = 3600, sleep=time.sleep, clock=time.monotonic) -> list[dict]:
    end = clock() + timeout
    while True:
        p = pending(state_dir)
        if p or clock() >= end:
            return p
        sleep(interval)


PLAYBOOK_DIR = Path(__file__).resolve().parent / "playbooks"
PLAYBOOK_FOR = [(r"^workday:|myworkdayjobs", "workday"), (r"^taleo:|taleo\.net", "taleo"),
                (r"^successfactors:|successfactors|sapsf", "successfactors"), (r"^icims:|icims\.com", "icims"),
                (r"greenhouse", "greenhouse"), (r"lever\.co", "lever"), (r"ashbyhq", "ashby"),
                (r"smartrecruiters", "smartrecruiters"), (r"linkedin", "linkedin"),
                (r"inspira|careers\.un\.org|unjobs|jobs\.undp|unicef\.org", "un-careers"),
                (r"^oracle:|oraclecloud", "oracle-recruiting")]


def playbook_name(scope_or_url: str) -> str:
    for rx, name in PLAYBOOK_FOR:
        if re.search(rx, scope_or_url or "", re.I):
            return name
    return ""


def playbook(workspace: Path, scope_or_url: str) -> str:
    """The general rules plus the portal's own page; a workspace ``playbooks/<name>.md`` is added after
    the built-in one, so a user's learned notes travel with every run."""
    parts = []
    name = playbook_name(scope_or_url)
    for n in ("all", name):
        if not n:
            continue
        for d in (PLAYBOOK_DIR, Path(workspace) / "playbooks"):
            f = d / f"{n}.md"
            if f.is_file():
                parts.append(f.read_text(encoding="utf-8").strip())
    return "\n\n".join(parts) + "\n"
