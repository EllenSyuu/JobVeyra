"""The Source interface, the adapter registry and small helpers every adapter shares."""
from __future__ import annotations

import datetime as dt
import html
import importlib
import re
import unicodedata
from typing import Any

from ..models import Posting

ADAPTERS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee", "un_careers",
            "usajobs", "remotive", "jsonld", "linkedin_alert")


class SourceError(RuntimeError):
    """A source cannot run as configured (missing key, missing credentials, unreadable file)."""


class Source:
    name: str = ""

    def fetch(self, spec: dict, http) -> list[Posting]:  # pragma: no cover - interface
        raise NotImplementedError


REGISTRY: dict[str, type[Source]] = {}


def register(cls: type[Source]) -> type[Source]:
    REGISTRY[cls.name] = cls
    return cls


def get(type_name: str) -> Source:
    """An instance of the adapter registered as ``type_name``; KeyError when there is none."""
    if type_name not in REGISTRY and type_name in ADAPTERS:
        importlib.import_module(f"{__package__}.{type_name}")
    try:
        return REGISTRY[type_name]()
    except KeyError:
        raise KeyError(f"unknown source type {type_name!r}; known: {', '.join(ADAPTERS)}") from None


# ---------------------------------------------------------------- helpers

def require(spec: dict, key: str) -> Any:
    v = spec.get(key)
    if v in (None, "", []):
        raise SourceError(f"source {spec.get('type', '?')!r} needs {key!r}")
    return v


def as_list(v: Any) -> list:
    if v in (None, ""):
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


_BLOCK = re.compile(r"<\s*(?:br|/p|/div|/h[1-6]|/tr|/ul|/ol|/table|/section|/article|hr)\b[^>]*>", re.I)


def html_to_text(s: str | None) -> str:
    """Plain text from an HTML fragment: block tags become line breaks, list items get a dash."""
    if not s:
        return ""
    if "&lt;" in s and "<" not in s:          # Greenhouse sends entity-escaped HTML
        s = html.unescape(s)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<\s*(script|style|head)\b.*?<\s*/\s*\1\s*>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<\s*li\b[^>]*>", "\n- ", s, flags=re.I)
    s = re.sub(r"<\s*(?:p|div|h[1-6]|tr|section|article)\b[^>]*>", "\n", s, flags=re.I)
    s = _BLOCK.sub("\n", s)
    s = re.sub(r"<\s*/?\s*(?:td|th|img|input|button)\b[^>]*>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace(" ", " ").replace("\r", "")
    lines = [re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def iso_date(v: Any) -> str:
    """ISO date (YYYY-MM-DD) from an ISO string, epoch seconds or milliseconds; '' if unknown."""
    if v in (None, "", 0):
        return ""
    if isinstance(v, (int, float)):
        secs = v / 1000 if v > 1e11 else v
        try:
            return dt.datetime.fromtimestamp(secs, dt.timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    for fmt in ("%m/%d/%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(s[:20].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


_EMPLOYMENT = (
    ("internship", r"intern|stage|stagiaire|apprenti|trainee|werkstudent|praktik|estagi|practica|becari|co ?op"),
    ("contract", r"contract|freelance|consult|independ|self employed"),
    ("temporary", r"\btemp\b|temporar|fixed term|seasonal|\bcdd\b|befrist|\bterm\b|interim|\bduree determinee"),
    ("part_time", r"part|teilzeit|partiel|parcial|medio tiempo"),
    ("full_time", r"full|permanent|regular|\bcdi\b|vollzeit|temps plein|tiempo completo|integral"),
)


def employment_of(v: Any) -> str:
    """Normalise an ATS employment label to full_time, part_time, contract, temporary, internship."""
    s = fold(" ".join(str(x) for x in as_list(v)))
    if not s:
        return ""
    for key, rx in _EMPLOYMENT:
        if re.search(rx, s):
            return key
    return ""


_REMOTE = re.compile(r"\b(remote|fully remote|work from home|wfh|teletravail|teletrabajo|remoto|anywhere|"
                     r"telecommute|home based)\b")
_ONSITE = re.compile(r"\b(hybrid|hybride|hibrido|on site|onsite|in office|presencial)\b")


def remote_hint(*texts: str) -> bool | None:
    """True when a location says remote, False when it says hybrid/on-site, None when silent."""
    s = fold(" ".join(t for t in texts if t))
    if _ONSITE.search(s):
        return False
    if _REMOTE.search(s):
        return True
    return None


def join(*parts: Any, sep: str = ", ") -> str:
    out: list[str] = []
    for p in parts:
        p = str(p or "").strip()
        if p and p.lower() not in (o.lower() for o in out):
            out.append(p)
    return sep.join(out)


def num(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


_CUR = {"us$": "USD", "usd": "USD", "ca$": "CAD", "c$": "CAD", "cad": "CAD", "€": "EUR", "eur": "EUR",
        "£": "GBP", "gbp": "GBP", "a$": "AUD", "aud": "AUD", "chf": "CHF", "¥": "JPY", "jpy": "JPY", "$": ""}
_CUR_RX = r"(US\$|CA\$|C\$|A\$|\$|€|£|¥|USD|CAD|EUR|GBP|CHF|AUD|JPY)"
_NUM_RX = r"(\d{1,3}(?:[,.  ]\d{3})+|\d+(?:\.\d+)?)\s*([kK])?"
_RANGE = re.compile(_CUR_RX + r"\s?" + _NUM_RX + r"(?:\s*(?:-|–|—|to|à|a)\s*" + _CUR_RX + r"?\s?" + _NUM_RX + r")?")
_RANGE_SUFFIX = re.compile(_NUM_RX + r"\s?" + _CUR_RX + r"(?:\s*(?:-|–|—|to|à|a)\s*" + _NUM_RX + r"\s?" + _CUR_RX + r"?)?")


def _amount(digits: str, k: str | None) -> float:
    d = re.sub(r"[,.  ](?=\d{3}\b)", "", digits)
    v = float(d.replace(",", ""))
    return v * 1000 if k else v


def money_range(text: str, default_currency: str = "") -> tuple[float, float, str] | None:
    """The first money amount or range in ``text`` ("$80k - $100k", "€50,000–60,000",
    "65 000 $ - 75 000 $") as ``(min, max, currency)``; None when there is none."""
    if not text:
        return None
    m = _RANGE.search(text)
    if m:
        cur, lo, k1, cur2, hi, k2 = m.groups()
        currency = _CUR.get(cur.lower(), "") or _CUR.get((cur2 or "").lower(), "") or default_currency
        a = _amount(lo, k1 or k2)
        b = _amount(hi, k2) if hi else a
        return min(a, b), max(a, b), currency
    m = _RANGE_SUFFIX.search(text)
    if m:
        lo, k1, cur, hi, k2, _cur2 = m.groups()
        a = _amount(lo, k1)
        b = _amount(hi, k2) if hi else a
        return min(a, b), max(a, b), _CUR.get(cur.lower(), "") or default_currency
    return None


def clean_title(s: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(s or ""))).strip()
