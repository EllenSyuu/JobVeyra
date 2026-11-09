"""Legitimacy signals for a posting: is it live, fresh, specific and a real opening?

``check(p, history, http)`` returns a sorted list of flags:
  closed         the URL answers 404/410, or the page says the job is closed (needs ``http``)
  repost:<n>     n earlier queue rows look like the same job: same employer and normalised title
                 under a different id, or the same content hash with a different posted date
  stale:<days>   posted more than STALE_DAYS days ago
  evergreen      talent-pool / always-open / general-application wording
  no_salary      no salary in the structured fields or in the text
  vague_title    a title that names no role ("Various positions", "Join our team")
Flags are signals for the rubric and the reviewer; none of them excludes a job on its own.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

from .. import queue
from ..models import Posting

STALE_DAYS = 45

EVERGREEN = ("talent pool", "talent community", "talent network", "talent pipeline", "candidate pipeline",
             "pipeline requisition", "pipeline role", "pipeline position", "always accepting", "always looking for",
             "always on the lookout", "general application", "spontaneous application", "open application",
             "unsolicited application", "future opportunities", "future openings", "evergreen",
             "candidature spontanee", "banque de candidatures", "reserve de talents", "candidatura espontanea",
             "bolsa de talentos", "banco de talentos", "initiativbewerbung")
VAGUE = re.compile(r"^ ?(?:various|multiple|several|open|general|many|diverse|divers|plusieurs|varios|varias|"
                   r"diversas?|verschiedene)? ?(?:positions?|roles?|jobs?|openings?|opportunit(?:y|ies)|vacanc(?:y|ies)|"
                   r"postes?|emplois?|puestos?|vagas?|stellen|applications?)(?: available| open)? ?$|"
                   r"join (?:our|the) team|we are hiring|we re hiring|now hiring|talent (?:pool|community)|"
                   r"general application|open application|spontaneous application|candidature spontanee|"
                   r"^ ?(?:employee|staff|worker|team member|associate)s? ?$")
CLOSED = ("no longer accepting", "position has been filled", "job not available", "job is no longer available",
          "no longer available", "this job has expired", "job has expired", "posting has closed",
          "posting is closed", "job is closed", "position is closed", "position has been closed",
          "no longer open", "applications are closed", "this position is no longer",
          "n est plus disponible", "offre expiree", "ya no esta disponible", "nao esta mais disponivel",
          "nicht mehr verfugbar")
_MONEY = re.compile(r"(?:US\$|CA\$|C\$|A\$|\$|€|£|¥|\b(?:USD|CAD|EUR|GBP|CHF|AUD|JPY)\b)\s?\d[\d,.  ]*\s*[kK]?\b"
                    r"|\b\d{1,3}(?:[,.  ]\d{3})+\s?(?:\$|€|£|USD|CAD|EUR|GBP|CHF)"
                    r"|\b\d+(?:\.\d+)?\s?[kK]\s?(?:-|–|to)\s?\d+(?:\.\d+)?\s?[kK]\b")
_PAY_WORDS = re.compile(r" (?:salary|salaries|pay range|pay band|pay scale|base pay|compensation range|wage|wages|"
                        r"remuneration|salaire|sueldo|salario|gehalt|verguetung) (?:[a-z]+ ){0,8}"
                        r"(?:\d{2,3} \d{3}|\d{4,}|\d+ ?k) ")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", s).strip() + " "


def norm_title(title: str) -> str:
    """Title without requisition numbers, bracketed notes and punctuation, for repost matching."""
    t = re.sub(r"[(\[].*?[)\]]", " ", title or "")
    t = re.sub(r"\b(?:req|ref|job|id)?\s*#?\s*[A-Z]{0,4}-?\d{4,}\b", " ", t, flags=re.I)
    return _fold(t).strip()


def _date(s: str) -> dt.date | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    try:
        return dt.date(*map(int, m.groups())) if m else None
    except ValueError:
        return None


def has_salary(p: Posting) -> bool:
    if p.salary_min is not None or p.salary_max is not None:
        return True
    text = p.text or ""
    return bool(_MONEY.search(text) or _PAY_WORDS.search(_fold(text)))


def repost_count(p: Posting, history: list[dict], jid: str = "") -> int:
    """How many earlier rows look like this same job reposted."""
    from ..discover import posting_id
    jid = jid or posting_id(p)
    ek, nt, h = queue.employer_key(p.employer), norm_title(p.title), p.content_hash
    matches: set[str] = set()
    for i, j in enumerate(history):
        oid = j.get("id") or f"#{i}"
        jek = j.get("employer_key") or queue.employer_key(j.get("employer", ""))
        if nt and jek == ek and norm_title(j.get("title", "")) == nt and oid != jid:
            matches.add(oid)
        elif h and j.get("content_hash") == h:
            if oid != jid:
                matches.add(oid)
            elif p.posted and j.get("posted") and j["posted"] != p.posted:
                matches.add(f"{oid}@{j['posted']}")
    return len(matches)


def is_closed(p: Posting, http) -> bool:
    from ..sources.http import HttpError
    status = http.head(p.url)
    if status in (404, 410):
        return True
    if not 200 <= status < 400:
        return False
    try:
        page = _fold(http.get_text(p.url))
    except HttpError as e:
        return e.status in (404, 410)
    return any(_fold(c) in page for c in CLOSED)


def check(p: Posting, history: list[dict], http=None, *, today: dt.date | None = None) -> list[str]:
    """Legitimacy flags for ``p`` given earlier queue rows; see the module docstring.
    ``today`` defaults to the queue clock (``JOBQUEUE_NOW`` when set)."""
    flags: set[str] = set()
    today = today or queue.now().date()

    n = repost_count(p, history or [])
    if n:
        flags.add(f"repost:{n}")

    posted = _date(p.posted)
    if posted and (today - posted).days > STALE_DAYS:
        flags.add(f"stale:{(today - posted).days}")

    title, body = _fold(p.title), _fold(p.text)
    if any(_fold(e) in title or _fold(e) in body for e in EVERGREEN) or " pipeline " in title:
        flags.add("evergreen")

    if not has_salary(p):
        flags.add("no_salary")

    if len(title.strip()) < 3 or VAGUE.search(title):
        flags.add("vague_title")

    if http is not None and p.url:
        try:
            if is_closed(p, http):
                flags.add("closed")
        except Exception:
            pass                                    # liveness unknown: no flag
    return sorted(flags)
