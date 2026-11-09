"""Read recruiting emails and turn them into outcomes, without logging in anywhere.

``classify(subject, body)`` names what an email is: ``confirmation`` (application received),
``rejected``, ``interview`` (an invitation or scheduling), ``assessment`` (a test or case), ``offer``,
or ``other``. English, French, Spanish and Portuguese phrasing.

``match(q, sender, subject, body)`` finds the job it is about: requisition number first, then
employer name with the title, then employer alone when only one submitted job has it.

``scan(cfg, q, messages, apply=False)`` does both for a list of messages (``.eml`` files, an mbox,
or text an agent pasted from a mail connector) and, with ``apply=True``, records the outcome; an
application confirmation for a job in ``needs_check`` resolves it as submitted. Nothing is recorded
for an email that matches no job or more than one.
"""
from __future__ import annotations

import email
import mailbox
import re
from email import policy
from pathlib import Path

from . import outcomes as oc

RULES = [
    ("offer", r"\b(?:offer of employment|job offer|pleased to offer|offre d'emploi|lettre d'offre|oferta de (?:trabajo|emprego))\b"),
    ("rejected", r"\b(?:unfortunately|regret to inform|not (?:to )?(?:move|moving) forward|decided to (?:proceed|move forward) with other|"
                 r"no longer under consideration|position has been filled|not been selected|other candidates whose|"
                 r"malheureusement|nous ne (?:pourrons|donnerons) pas suite|pas été retenue?|lamentablemente|"
                 r"no ha sido seleccionad|infelizmente|não foi selecionad)\w*"),
    ("interview", r"\b(?:invite you to (?:an? )?interview|interview invitation|schedule (?:an? |your )?(?:interview|call|chat)|"
                  r"phone screen|availability for (?:an? )?(?:interview|call)|book a time|"
                  r"convocation (?:à|a) (?:un )?entretien|entrevue|entretien (?:téléphonique|vidéo)|"
                  r"invitación a (?:una )?entrevista|convite para (?:uma )?entrevista)\b"),
    ("assessment", r"\b(?:assessment|online test|coding (?:challenge|test)|case study|take-home|hackerrank|codility|"
                   r"test en ligne|évaluation en ligne|prueba técnica|teste online)\b"),
    ("confirmation", r"\b(?:(?:we have |we've )?received your application|thank you for (?:your )?appl(?:ying|ication)|"
                     r"application (?:has been )?(?:received|submitted)|nous avons (?:bien )?reçu votre candidature|"
                     r"merci (?:pour|de) votre candidature|hemos recibido tu (?:solicitud|candidatura)|"
                     r"recebemos (?:a )?sua candidatura)\b"),
]
OUTCOME_FOR = {"rejected": "rejected", "interview": "interview", "assessment": "assessment", "offer": "offer"}


def classify(subject: str, body: str) -> str:
    text = f"{subject}\n{body}"
    for kind, rx in RULES:
        if re.search(rx, text, re.I):
            return kind
    return "other"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def match(q, sender: str, subject: str, body: str) -> list[dict]:
    text = f"{subject}\n{body}"
    low = _norm(text)
    pool = [j for j in q.all() if j["state"] in ("submitted", "needs_check", "in_progress")]
    by_req = [j for j in pool if j.get("req_id") and re.search(rf"\b{re.escape(str(j['req_id']))}\b", text)]
    if by_req:
        return by_req
    dom = (sender.split("@")[-1].split(">")[0].lower() if "@" in (sender or "") else "")
    def emp(j):
        e = _norm(j.get("employer"))
        return bool(e) and (f" {e} " in f" {low} " or (dom and e.split()[0] in dom))
    by_emp = [j for j in pool if emp(j)]
    with_title = [j for j in by_emp if _norm(j.get("title")) and _norm(j.get("title")) in low]
    return with_title or by_emp


def read_messages(paths: list[Path]) -> list[dict]:
    out = []
    for p in paths:
        p = Path(p)
        if p.suffix.lower() == ".mbox":
            msgs = list(mailbox.mbox(str(p)))
        elif p.suffix.lower() == ".eml":
            msgs = [email.message_from_bytes(p.read_bytes(), policy=policy.default)]
        else:                                           # pasted text: "Subject: ...\nFrom: ...\n\nbody"
            raw = p.read_text(encoding="utf-8")
            msgs = [email.message_from_string(raw, policy=policy.default)]
        for m in msgs:
            body = ""
            if m.is_multipart():
                for part in m.walk():
                    if part.get_content_type() == "text/plain":
                        body += part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            else:
                payload = m.get_payload(decode=True)
                body = payload.decode(m.get_content_charset() or "utf-8", "replace") if isinstance(payload, bytes) else str(m.get_payload())
            out.append({"from": str(m.get("From") or ""), "subject": str(m.get("Subject") or ""),
                        "date": str(m.get("Date") or ""), "body": body, "file": str(p)})
    return out


def scan(cfg, q, messages: list[dict], *, apply: bool = False) -> list[dict]:
    results = []
    for m in messages:
        kind = classify(m["subject"], m["body"])
        jobs = match(q, m["from"], m["subject"], m["body"]) if kind != "other" else []
        row = {"subject": m["subject"][:100], "from": m["from"][:80], "kind": kind,
               "jobs": [j["id"] for j in jobs], "recorded": ""}
        if apply and len(jobs) == 1:
            j = jobs[0]
            if kind == "confirmation" and j["state"] == "needs_check":
                q.resolve_check(j["id"], found_on_portal=True, evidence=f"confirmation email: {m['subject'][:120]}")
                row["recorded"] = "submitted"
            elif kind in OUTCOME_FOR and j["state"] == "submitted":
                have = {r.get("outcome") for r in oc.by_job(oc.load(q.dir)).get(j["id"], [])}
                if OUTCOME_FOR[kind] not in have:
                    oc.record(q.dir, j["id"], OUTCOME_FOR[kind], f"email: {m['subject'][:120]}")
                    row["recorded"] = OUTCOME_FOR[kind]
        elif apply and len(jobs) > 1:
            row["recorded"] = "ambiguous: not recorded"
        results.append(row)
    return results
