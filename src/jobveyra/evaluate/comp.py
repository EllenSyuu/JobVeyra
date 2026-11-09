"""Salary parsing and annualisation.

``parse_salary(text)`` finds the first pay figure or range that carries a currency and returns
``(min, max, currency, period)`` with both values **annualised** (2080 hours, 260 days, 12
months per year). ``period`` is the period the posting stated (hour, day, week, month, year),
so a caller can say "quoted hourly". Nothing found -> ``(None, None, "", "")``.

Handles ``$90k-$120k``, ``CA$85,000 – 95,000 per year``, ``€45.000 - €55.000``, ``£400/day``,
``USD 40-55 per hour``, ``CHF 120 000``, ``¥6,000,000``, ``45 000 € brut annuel`` and so on.
"""
from __future__ import annotations

import re

PER_YEAR = {"hour": 2080, "day": 260, "week": 52, "month": 12, "year": 1}

# Rough rates to EUR for comparing a posting with a salary floor in another currency. The
# comparison is marked as an estimate wherever these are used.
FX_TO_EUR = {"EUR": 1.0, "USD": 0.92, "CAD": 0.67, "GBP": 1.17, "CHF": 1.05, "JPY": 0.0061,
             "AUD": 0.60, "NZD": 0.55, "SEK": 0.087, "NOK": 0.086, "DKK": 0.134, "PLN": 0.23,
             "BRL": 0.17, "MXN": 0.05, "INR": 0.011, "SGD": 0.68, "HKD": 0.118, "CNY": 0.127}

_SYM = r"(?:CA\$|C\$|US\$|A\$|AU\$|NZ\$|HK\$|S\$|R\$|\$|€|£|¥|￥)"
_CODE = r"(?:CAD|USD|EUR|GBP|CHF|JPY|AUD|NZD|SEK|NOK|DKK|PLN|BRL|MXN|INR|SGD|HKD|CNY|RMB)"
_CUR = rf"(?:{_SYM}|{_CODE}\b\s?)"
_NUM = r"\d{1,3}(?:[,.   ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?"
_MULT = r"(?:\s?(?:k|K|m|M|mil|million|thousand)\b)?"
_SEP = r"\s*(?:-|–|—|to|à|a|bis|até|and)\s*"
_ONE = rf"(?P<c1>{_CUR})?\s?(?P<n1>{_NUM})(?P<k1>{_MULT})\s?(?P<c2>{_CUR})?"
_TWO = rf"(?:{_SEP}(?P<c3>{_CUR})?\s?(?P<n2>{_NUM})(?P<k2>{_MULT})\s?(?P<c4>{_CUR})?)?"
_RX = re.compile(rf"(?<![\w.,]){_ONE}{_TWO}(?![\w])")

_PERIOD = [
    ("hour", r"(?:per|an|a|/|par|la|por|pro|all['’])\s?(?:hour|hr|h|heure|hora|stunde|ora)\b|hourly|\bhoraire|/\s?h\b|\bp/?h\b"),
    ("day", r"(?:per|a|/|par|por|pro|al)\s?(?:day|jour|journee|dia|día|tag|giorno)\b|\bdaily\b|day rate|tjm|taux journalier"),
    ("week", r"(?:per|a|/|par|por|pro)\s?(?:week|wk|semaine|semana|woche|settimana)\b|\bweekly\b"),
    ("month", r"(?:per|a|/|par|por|pro|al)\s?(?:month|mo|mois|mes|monat|mese)\b|\bmonthly\b|\bmensuel|\bmensual|\bmonatlich"),
    ("year", r"(?:per|a|/|par|por|pro|all['’])\s?(?:year|yr|annum|an|année|annee|año|ano|jahr|anno)\b|\bannual\w*|\byearly\b|\bp\.?a\.?\b|\bannuel\w*|\banual\b|\bjährlich|\bbrut\b|\bgross\b"),
]

_SYM_CODE = {"CA$": "CAD", "C$": "CAD", "US$": "USD", "A$": "AUD", "AU$": "AUD", "NZ$": "NZD", "HK$": "HKD",
             "S$": "SGD", "R$": "BRL", "€": "EUR", "£": "GBP", "¥": "JPY", "￥": "JPY", "RMB": "CNY"}


def _currency(tok: str | None, default_dollar: str) -> str:
    if not tok:
        return ""
    t = tok.strip()
    if t == "$":
        return default_dollar
    return _SYM_CODE.get(t, t.upper())


def _number(s: str) -> float:
    s = s.replace(" ", " ").replace(" ", " ")
    if re.fullmatch(r"\d{1,3}(?:[ ,.]\d{3})+", s):
        return float(re.sub(r"[ ,.]", "", s))
    m = re.fullmatch(r"(\d{1,3}(?:[ ,.]\d{3})+)([.,])(\d{1,2})", s)
    if m:
        return float(re.sub(r"[ ,.]", "", m.group(1)) + "." + m.group(3))
    return float(s.replace(",", ".").replace(" ", ""))


def _mult(k: str) -> float:
    k = (k or "").strip().lower()
    if k in ("k", "thousand", "mil"):
        return 1e3
    if k in ("m", "million"):
        return 1e6
    return 1.0


def period_of(context: str) -> str:
    c = context.lower()
    for name, rx in _PERIOD:
        if re.search(rx, c):
            return name
    return ""


def guess_period(value: float) -> str:
    """Period implied by the size of an amount when the posting does not say."""
    if value < 300:
        return "hour"
    if value < 2000:
        return "day"
    if value < 20000:
        return "month"
    return "year"


def annualise(value: float | None, period: str) -> float | None:
    if value is None:
        return None
    return round(value * PER_YEAR.get(period or "year", 1), 2)


def parse_salary(text: str, *, default_dollar: str = "USD") -> tuple[float | None, float | None, str, str]:
    """First salary figure or range with a currency, annualised. See the module docstring."""
    for m in _RX.finditer(text or ""):
        cur_tok = m.group("c1") or m.group("c2") or m.group("c3") or m.group("c4")
        if not cur_tok:
            continue
        n1 = m.group("n1")
        if re.fullmatch(r"(19|20)\d{2}", n1) and not m.group("n2") and not m.group("k1"):
            continue                                      # a year next to a currency code
        lo = _number(n1)
        hi = _number(m.group("n2")) if m.group("n2") else None
        k1, k2 = _mult(m.group("k1")), _mult(m.group("k2"))
        if hi is not None and k2 > 1 and k1 == 1 and lo < 1000:
            k1 = k2                                       # "$90-120k": the k applies to both
        lo *= k1
        if hi is not None:
            hi *= k2
            if hi < lo:
                lo, hi = hi, lo
        top = hi if hi is not None else lo
        if top < 5:                                       # "3 € tickets", stray digits
            continue
        ctx = text[m.end(): m.end() + 40] + " " + text[max(0, m.start() - 25): m.start()]
        period = period_of(text[m.end(): m.end() + 40]) or period_of(ctx) or guess_period(top)
        cur = _currency(cur_tok, default_dollar)
        return annualise(lo, period), annualise(hi if hi is not None else lo, period), cur, period
    return None, None, "", ""


def to_eur(value: float | None, currency: str) -> float | None:
    if value is None:
        return None
    rate = FX_TO_EUR.get((currency or "").upper())
    return None if rate is None else value * rate


def convert(value: float | None, frm: str, to: str) -> float | None:
    """Approximate conversion between two currencies (None when either is unknown)."""
    if value is None:
        return None
    frm, to = (frm or "").upper(), (to or "").upper()
    if frm == to:
        return value
    e = to_eur(value, frm)
    r = FX_TO_EUR.get(to)
    return None if e is None or not r else e / r
