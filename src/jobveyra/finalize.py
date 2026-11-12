"""The last page of an application: what an agent may do without asking, decided in code.

The agent reports the final page as a short list of elements (no screenshot needed):

  [{"kind": "accuracy_declaration", "text": "I certify the information provided is accurate", "required": true},
   {"kind": "terms", "text": "I accept the data privacy statement", "required": true},
   {"kind": "optional_consent", "text": "Join our talent community"},
   {"kind": "answer", "text": "Salary expectation", "source": "answers"},
   {"kind": "submit", "text": "Apply"}]

kinds: navigation | submit | answer (source: answers|profile|package|standing|unverified) |
       accuracy_declaration | terms | optional_consent | self_identification | signature |
       captcha | mfa | password | account_creation | government_id | chrome_permission | unknown

``decide()`` returns one of
  submit      tick exactly ``tick``, leave ``leave`` unticked, press submit once
  hold        park the job (final approval / question) and continue with the next job
  auth        sign-in wall
  technical   CAPTCHA and the like
  ineligible  a REQUIRED declaration states something the candidate's known facts contradict
              (e.g. a citizenship they do not hold): the job is excluded, nobody is asked

Without a consent the defaults are the old hard rule (never tick an attestation). A standing
consent lives in ``<state>/consents.json`` with the candidate's own words and covers a CATEGORY
of checkbox; it never makes a false or unestablished statement certifiable:
  - a declaration is ticked only with the consent AND every answer on the form verified AND a
    generic accuracy statement or a claim known to be true;
  - known facts come from ``<state>/claims.json``: [{"pattern": regex, "true": bool, "why": text}];
    a false one is never ticked and never asked about (required -> ineligible, optional -> left);
  - an unknown factual claim (years of experience, licences, clearances...) goes to the candidate;
  - CAPTCHA, MFA, passwords, account creation and government ID numbers are never done for them;
  - a browser-extension permission prompt is platform-enforced: a hold with the exact action.
Only the candidate records a consent (``jobveyra authorize --consent KIND --evidence``).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import queue as jq

CONSENT_KINDS = ("accuracy_declaration", "application_terms", "electronic_signature", "self_identification")
VERIFIED_SOURCES = ("answers", "profile", "package", "standing")
# hold kind -> the consent that covers it; kinds missing here need the candidate every time
COVERED_BY = {"declaration": "accuracy_declaration", "terms": "application_terms", "signature": "electronic_signature"}
NEVER_GRANTABLE: tuple[str, ...] = ()

GENERIC_DECL = re.compile(
    r"(information|answers?|statements?|details|renseignements|informations)\b.{0,80}\b"
    r"(true|accurate|complete|correct|exacte?s?|véridiques?|complètes?)"
    r"|best of my knowledge|au meilleur de ma connaissance"
    r"|(i|j')\s*(certify|confirm|attest|declare|atteste|certifie|confirme|déclare)\b.{0,60}\b(accura|true|correct|complete|exact)"
    r"|misrepresentation|falsification|omission.{0,40}(grounds|motif)",
    re.I)
UNKNOWN_CLAIMS = re.compile(
    r"\d+\s*\+?\s*(years?|ans)\b|security\s+clearance|habilitation|background\s+check|credit\s+check|"
    r"references?\s+(may|will)\s+be\s+contacted|drug|bond(ed|able)|non[- ]compete|relocat", re.I)
NEGATION = re.compile(r"\b(not|no|never|n'|ne\s+suis\s+pas|pas)\b[^.;]{0,12}$", re.I)

MESSAGES = {
    "chrome_permission": "Approve the browser extension's prompt (optionally 'always allow' this site), then approve the job",
    "government_id": "Only the candidate enters ID numbers: {text}",
    "self_id_required": "Required self-identification question: {text}",
    "terms": "Terms required to apply: {text}",
    "signature": "Electronic signature (legally binding): {text}",
    "unknown_claim": "The declaration states a fact the fact base does not establish: {text} ({why})",
    "unverified_answers": "{n} answer(s) on the form are not verified, so the declaration cannot be certified",
    "declaration": "Accuracy declaration: {text}",
    "question": "Unrecognised required field: {text}",
    "ineligible": "required declaration contradicts the candidate's known facts: {text} ({why})",
}
ORDER = ("chrome_permission", "unknown_claim", "unverified_answers", "declaration", "signature", "terms", "question")


def _state(state_dir) -> Path:
    return Path(state_dir or jq.STATE_DIR or ".")


def consents(state_dir=None) -> dict:
    try:
        return json.loads((_state(state_dir) / "consents.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def grant(kind: str, evidence: str, state_dir=None, **extra) -> dict:
    if kind not in CONSENT_KINDS:
        raise ValueError(f"unknown consent kind {kind}; one of {CONSENT_KINDS}")
    if not (evidence or "").strip():
        raise ValueError("a standing consent needs the candidate's words and where they said them")
    d = consents(state_dir)
    d[kind] = {"granted": jq.iso(jq.now()), "evidence": evidence[:300], **extra}
    p = _state(state_dir) / "consents.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return d[kind]


def known_claims(state_dir=None) -> list[tuple[str, bool, str]]:
    try:
        rows = json.loads((_state(state_dir) / "claims.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [(r["pattern"], bool(r["true"]), r.get("why", "")) for r in rows if r.get("pattern")]


def claim_truth(text: str, claims: list[tuple[str, bool, str]] | None = None) -> tuple[str, str]:
    """('generic'|'true'|'false'|'unknown', why) for what a declaration asks the candidate to state."""
    t = text or ""
    found_true = ""
    for rx, truth, why in (claims if claims is not None else known_claims()):
        for m in re.finditer(rx, t, re.I):
            neg = bool(NEGATION.search(t[:m.start()]))
            if truth == neg:
                return "false", why
            found_true = found_true or why
    if UNKNOWN_CLAIMS.search(t):
        return "unknown", "factual claim not in the fact base"
    if found_true:
        return "true", found_true
    if GENERIC_DECL.search(t):
        return "generic", "generic accuracy statement"
    return "unknown", "declaration text not recognised"


def decide(elements: list[dict], cons: dict | None = None, *, claims=None, unverified: int | None = None,
           messages: dict | None = None) -> dict:
    cons = consents() if cons is None else cons
    claims = known_claims() if claims is None else claims
    msg = {**MESSAGES, **(messages or {})}
    tick, leave, holds = [], [], []
    n_unver = sum(1 for e in elements if e.get("kind") == "answer" and (e.get("source") or "unverified") not in VERIFIED_SOURCES)
    if unverified is not None:
        n_unver = max(n_unver, int(unverified))
    for e in elements:
        k, txt, req = e.get("kind") or "unknown", (e.get("text") or "")[:200], bool(e.get("required", True))
        if k in ("navigation", "submit", "answer"):
            continue
        if k == "captcha":
            return {"decision": "technical", "class": "captcha", "why": "a CAPTCHA is never solved for the candidate"}
        if k in ("mfa", "password", "account_creation"):
            return {"decision": "auth", "why": f"{k}: the candidate signs in themselves"}
        if k == "chrome_permission":
            holds.append(("chrome_permission", msg["chrome_permission"]))
        elif k == "government_id":
            holds.append(("question", msg["government_id"].format(text=txt)))
        elif k == "optional_consent":
            leave.append(txt)
        elif k == "self_identification":
            si = cons.get("self_identification")
            if si:
                tick.append(f"{txt} -> {si.get('answer', 'prefer not to answer')}")
            elif req:
                holds.append(("question", msg["self_id_required"].format(text=txt)))
            else:
                leave.append(txt)
        elif k == "terms":
            if not req:
                leave.append(txt)
            elif "application_terms" in cons:
                tick.append(txt)
            else:
                holds.append(("terms", msg["terms"].format(text=txt)))
        elif k == "signature":
            if "electronic_signature" in cons and n_unver == 0:
                tick.append(f"{txt} -> type the legal name")
            else:
                holds.append(("signature", msg["signature"].format(text=txt)))
        elif k == "accuracy_declaration":
            truth, why = claim_truth(txt, claims)
            if truth == "false":
                if req:
                    return {"decision": "ineligible", "why": msg["ineligible"].format(text=txt[:120], why=why)}
                leave.append(txt)
            elif truth == "unknown":
                holds.append(("unknown_claim", msg["unknown_claim"].format(text=txt, why=why)))
            elif n_unver:
                holds.append(("unverified_answers", msg["unverified_answers"].format(n=n_unver)))
            elif "accuracy_declaration" in cons:
                tick.append(txt)
            else:
                holds.append(("declaration", msg["declaration"].format(text=txt)))
        elif req:
            holds.append(("question", msg["question"].format(text=txt)))
        else:
            leave.append(txt)
    if holds:
        holds.sort(key=lambda h: ORDER.index(h[0]) if h[0] in ORDER else 99)
        grantable = [e.get("text", "")[:200] for e in elements if e.get("kind") in ("accuracy_declaration", "terms", "signature")
                     and claim_truth(e.get("text", ""), claims)[0] != "false"]
        return {"decision": "hold", "kind": holds[0][0], "need": "; ".join(h[1] for h in holds)[:300],
                "holds": sorted({h[0] for h in holds}), "tick": tick, "tick_after_grant": tick + grantable, "leave": leave}
    return {"decision": "submit", "tick": tick, "leave": leave, "unverified_answers": n_unver}


# ---------------------------------------------------------------- the gate an agent calls

def finalize(q: jq.Queue, jid: str, elements: list[dict], *, page: str = "", saved: str = "unknown",
             recon: str = "unknown", unverified: int | None = None, messages: dict | None = None) -> dict:
    """Decide, record, and tell the agent what to do. ``click`` is True only when the durable attempt
    record has been written; anything else means: do not press submit, take the next job."""
    j = q.get(jid)
    if j is None:
        raise KeyError(jid)
    if j["state"] == "submitted":
        return {"decision": "do_not_click", "why": "already submitted", "click": False}
    if j["state"] != "in_progress":
        return {"decision": "do_not_click", "why": f"state is {j['state']}: lease it with next first", "click": False}
    q.progress(jid, jq.FORM_COMPLETED, page=page, saved=saved, reconstructable=recon)
    d = decide(elements, consents(q.dir), claims=known_claims(q.dir), unverified=unverified, messages=messages)
    if d["decision"] == "hold" and j.get("final_grant") and "chrome_permission" not in d["holds"]:
        d = {"decision": "submit", "tick": d["tick_after_grant"], "leave": d["leave"], "authorized_by": j["final_grant"][:120]}
    if d["decision"] == "ineligible":
        q.set_state(jid, "excluded", d["why"][:200], reason=f"ineligible:{d['why'][:150]}", lease_until="",
                    last_attempt_at=jq.iso(jq.now()), final_stage="")
        return {"decision": "excluded", "why": d["why"], "click": False}
    if d["decision"] == "auth":
        st = q.block(jid, f"auth:{q.scope(j)}")
        return {"decision": "parked", "state": st, "why": d["why"], "click": False}
    if d["decision"] == "technical":
        st = q.block(jid, d.get("class", "unsupported_form"))
        return {"decision": "parked", "state": st, "why": d["why"], "click": False}
    if d["decision"] == "hold":
        st = q.await_final(jid, ",".join(d["holds"]), d["need"], page=page, saved=saved, reconstructable=recon)
        return {"decision": "parked", "state": st, "kind": d["kind"], "need": d["need"],
                "recovery": q.get(jid).get("recovery") or "", "click": False}
    q.progress(jid, jq.FINALIZATION_READY)
    rec = q.begin_submit(jid)
    if not rec["click"]:
        return {"decision": "do_not_click", "why": rec["status"], "click": False}
    return {"decision": "submit", "tick": d["tick"], "leave": d["leave"], "attempt_id": rec["attempt_id"], "click": True}


def _kinds(j: dict) -> set[str]:
    return {k for k in (j.get("final_kind") or "").split(",") if k}


def authorize_consent(q: jq.Queue, kind: str, evidence: str, **extra) -> list[str]:
    """Record a standing consent and release every parked job it now fully covers."""
    grant(kind, evidence, q.dir, **extra)
    have = {k for k, c in COVERED_BY.items() if c in consents(q.dir)}
    rel = []
    for j in q.all("blocked_human"):
        ks = _kinds(j)
        if j.get("final_stage") == jq.AWAITING_FINAL and ks and ks <= have:
            q.grant_final(j["id"], f"standing consent {kind}: {evidence[:100]}")
            rel.append(j["id"])
    return rel


def holding(q: jq.Queue) -> dict:
    """Every open blocker grouped by category and portal (one pass per portal for the candidate)."""
    out: dict[str, dict] = {}
    for j in q.all():
        cat = jq.holding_category(j)
        if not cat:
            continue
        sub = q.scope(j) if cat in ("AUTH REQUIRED", "FINAL APPROVAL REQUIRED") else (j.get("reason") or "").split(":")[0]
        if cat == "FINAL APPROVAL REQUIRED":
            sub += f" · {j.get('final_kind') or ''}"
        out.setdefault(cat, {}).setdefault(sub, []).append({
            "id": j["id"], "employer": j.get("employer"), "title": (j.get("title") or "")[:70],
            "need": j.get("final_need") or j.get("action") or "",
            "page": j.get("final_page") or j.get("apply_url") or j.get("url") or "", "recovery": j.get("recovery") or ""})
    return {"counts": {k: sum(len(v) for v in g.values()) for k, g in out.items()}, "groups": out}
