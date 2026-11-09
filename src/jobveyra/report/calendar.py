"""iCalendar (RFC 5545) export for deadlines, interviews and follow-ups.

An event is a dict::

    {"kind": "deadline" | "interview" | "followup",
     "summary": "...",                    # or "title"
     "date": "YYYY-MM-DD"                  # all-day event, or
     "start": "YYYY-MM-DDTHH:MM[:SS][+hh:mm|Z]", "end": ..., "duration_min": 60,
     "description": "...", "location": "...", "url": "...", "uid": "..."}

Datetimes with an offset are written in UTC (``...Z``); naive ones as floating local time.
Lines end in CRLF and are folded at 75 octets.
"""
from __future__ import annotations

import datetime as dt
import hashlib

from .. import outcomes as oc

PRODID = "-//jobveyra//job search//EN"
KINDS = {"deadline": "Deadline", "interview": "Interview", "followup": "Follow up"}


def _esc(s) -> str:
    return (str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> list[str]:
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]
    out, cur, limit = [], b"", 75
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > limit:
            out.append(cur.decode("utf-8"))
            cur, limit = b"", 74            # continuation lines start with one space
        cur += b
    out.append(cur.decode("utf-8"))
    return [out[0]] + [" " + x for x in out[1:]]


def _to_dt(value) -> dt.datetime:
    """A datetime from a datetime or an ISO string, keeping its offset (unlike parse_time)."""
    if isinstance(value, dt.datetime):
        return value
    s = str(value)
    return dt.datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s)


def _dtval(value) -> tuple[str, str]:
    """(param suffix, value) for DTSTART/DTEND."""
    if isinstance(value, dt.datetime) or (isinstance(value, str) and "T" in value):
        t = _to_dt(value)
        if t.tzinfo is not None:
            return "", t.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return "", t.strftime("%Y%m%dT%H%M%S")
    d = value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)[:10])
    return ";VALUE=DATE", d.strftime("%Y%m%d")


def _uid(e: dict) -> str:
    if e.get("uid"):
        return str(e["uid"])
    key = "|".join(str(e.get(k, "")) for k in ("kind", "job_id", "date", "start", "summary", "title"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + "@jobveyra"


def ics(events: list[dict], *, stamp: dt.datetime | None = None, name: str = "Job search") -> str:
    stamp = stamp or dt.datetime.now(dt.timezone.utc)
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(dt.timezone.utc)
    dtstamp = stamp.strftime("%Y%m%dT%H%M%SZ")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
         f"X-WR-CALNAME:{_esc(name)}"]
    for e in events:
        kind = e.get("kind", "")
        summary = e.get("summary") or e.get("title") or KINDS.get(kind, "Event")
        if "start" in e and e["start"]:
            p, v = _dtval(e["start"])
            if e.get("end"):
                pe, ve = _dtval(e["end"])
            else:
                start = _to_dt(e["start"])
                pe, ve = _dtval(start + dt.timedelta(minutes=int(e.get("duration_min") or 60)))
        else:
            d = oc.as_date(e.get("date"))
            if d is None:
                raise ValueError(f"event {summary!r} needs a date or a start")
            p, v = _dtval(d)
            pe, ve = _dtval(d + dt.timedelta(days=1))
        L += ["BEGIN:VEVENT", f"UID:{_uid(e)}", f"DTSTAMP:{dtstamp}", f"DTSTART{p}:{v}", f"DTEND{pe}:{ve}",
              f"SUMMARY:{_esc(summary)}"]
        if kind in KINDS:
            L.append(f"CATEGORIES:{_esc(KINDS[kind])}")
        for key, prop in (("description", "DESCRIPTION"), ("location", "LOCATION"), ("url", "URL")):
            if e.get(key):
                L.append(f"{prop}:{e[key] if prop == 'URL' else _esc(e[key])}")
        if kind == "deadline" and p == ";VALUE=DATE":
            L += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(summary)}", "TRIGGER:-P2D", "END:VALARM"]
        L.append("END:VEVENT")
    L.append("END:VCALENDAR")
    return "".join(f"{x}\r\n" for line in L for x in _fold(line))


def events_from_digest(digest: dict, interviews: list[dict] = ()) -> list[dict]:
    """Deadlines and follow-ups from a digest, plus any interview events the caller passes."""
    ev = [{"kind": "deadline", "date": d["date"], "job_id": d["job_id"],
           "summary": f"Deadline: {d['employer']}, {d['title']}"} for d in digest["coming_up"]["deadlines"]]
    ev += [{"kind": "followup", "date": digest["date"], "job_id": f["job_id"],
            "summary": f"Follow up: {f['employer']}, {f['title']}",
            "description": f["suggested_message"]} for f in digest["coming_up"]["followups"]]
    return ev + [{"kind": "interview", **i} for i in interviews]
