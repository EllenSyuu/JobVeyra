"""Fabrication guard: nothing specific may appear in a document unless the fact base has it.

``check(document, fact_base)`` extracts every checkable claim from the document and returns,
in order and without duplicates, the ones the fact base does not support:

* numbers and amounts: ``1,200``, ``3.5``, ``40%``, ``40 percent``, ``$2M``, ``7.17M``,
  ``2 million``, ``15k`` (compared by value: ``1,200 == 1200``, ``2M == 2 million``,
  ``40% == 40 percent``; a percentage needs a percentage in the fact base);
* years (``19xx`` / ``20xx``) and month-year dates (``Sep 2026``, ``09/2026``, ``2026-09``,
  ``septembre 2026``); a month-year needs that month, not only the year;
* organisation names after "at", "with", "for", "joined" (and chez, à, con, para, em, bei);
* degrees (``B.Sc.``, ``M.Sc.``, ``MBA``, ``PhD``, ``Master of ...``, ``Bachelor's``);
* certifications (``CFA``, ``FRM``, ``PMP``, ``CFA Level II``, ``AWS Certified ...``,
  ``XYZ certification``).

``story_provenance(story_text, fact_base)`` applies the same test sentence by sentence, for
interview stories.
"""
from __future__ import annotations

import re
import unicodedata

_MONTHS = {
    1: "january jan janvier janv enero ene janeiro jan januar gennaio",
    2: "february feb fevrier fevr febrero feb fevereiro fev februar febbraio",
    3: "march mar mars marzo marco marz",
    4: "april apr avril abril abr",
    5: "may mai mayo maio maggio",
    6: "june jun juin junio junho juni giugno",
    7: "july jul juillet juil julio julho juli luglio",
    8: "august aug aout agosto ago",
    9: "september sep sept septembre septiembre setembro set settembre",
    10: "october oct octobre octubre outubro out oktober ottobre",
    11: "november nov novembre noviembre novembro",
    12: "december dec decembre diciembre dic dezembro dez dezember dicembre",
}
_MONTH_OF = {w: m for m, ws in _MONTHS.items() for w in ws.split()}
_MONTH_RX = "|".join(sorted(_MONTH_OF, key=len, reverse=True))

URL_RX = re.compile(r"https?://\S+|www\.\S+", re.I)
EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RX = re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{7,}\d(?!\w)")
MONTH_YEAR_RX = re.compile(rf"\b({_MONTH_RX})\.?,?\s+(?:de\s+)?((?:19|20)\d{{2}})\b", re.I)
NUM_MONTH_YEAR_RX = re.compile(r"(?<![\d/.-])(0?[1-9]|1[0-2])[/.](?P<y>(?:19|20)\d{2})(?![\d/])")
ISO_MONTH_RX = re.compile(r"(?<![\d-])(?P<y>(?:19|20)\d{2})-(0[1-9]|1[0-2])(?:-\d{2})?(?![\d])")
YEAR_RX = re.compile(r"(?<![\d.,$€£])((?:19|20)\d{2})(?![\d])")
NUM_RX = re.compile(
    r"(?<![\w.,/])(?<![A-Za-z]-)(?P<cur>[$€£¥])?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<suf>\s?(?:%|percent\b|per\s?cent\b|pour\s?cent\b|por\s?ciento\b|[kK]\b|[mM]\b|bn\b|[bB]\b|mn\b|"
    r"million\b|millions\b|billion\b|thousand\b|millones\b|milliards?\b|mil\b))?(?![\w])")
LIST_MARKER = re.compile(r"^\s*\d{1,2}[.)]\s", re.M)

_PREP = r"(?:(?i:at|with|for|joined|joining|chez|à|con|para|em|bei|from))"
_CAPWORD = r"[A-Z][\w&'’-]*(?:\.[A-Za-z]+)*"
_JOIN = r"(?:of|de|du|des|for|and|&|the|la|le|del|da|do|für|und)"
ORG_RX = re.compile(rf"\b{_PREP}\s+((?:the\s+)?{_CAPWORD}(?:\s+{_JOIN}\s+{_CAPWORD}|\s+{_CAPWORD})*)")
_NOT_ORG = {"i", "we", "my", "our", "the", "this", "that", "a", "an", "it", "me", "you", "your", "their", "his",
            "her", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "both", "each",
            "all", "every", "over", "least", "most", "example", "instance", "more", "less", "about"}

DEGREE_RX = re.compile(
    r"(?<![\w.])(?:B\.\s?Sc\.?|BSc|B\.\s?S\.|B\.\s?A\.|B\.\s?Eng\.?|BEng|M\.\s?Sc\.?|MSc|M\.\s?S\.|M\.\s?A\.|"
    r"M\.?B\.?A\.?|M\.\s?Eng\.?|MEng|MPH|MPhil|M\.\s?Phil\.?|Ph\.\s?D\.?|PhD|DPhil|D\.\s?Phil\.?|LL\.\s?M\.?|LL\.\s?B\.?)(?![\w])"
    r"|\b(?:Bachelor|Master|Doctor)(?:['’]s)?(?:\s+of\s+[A-Z][a-z]+(?:\s+(?:and|in|&)\s+[A-Z][a-z]+)*|\s+degree)?",
)
_DEGREE_KEYS = {"bsc": "bsc", "bs": "bsc", "ba": "ba", "beng": "beng", "msc": "msc", "ms": "msc", "ma": "ma",
                "mba": "mba", "meng": "meng", "mph": "mph", "mphil": "mphil", "phd": "phd", "dphil": "phd",
                "llm": "llm", "llb": "llb",
                "bachelor of science": "bsc", "bachelor of arts": "ba", "bachelor of engineering": "beng",
                "master of science": "msc", "master of arts": "ma", "master of business administration": "mba",
                "master of engineering": "meng", "master of public health": "mph", "master of philosophy": "mphil",
                "doctor of philosophy": "phd"}
_LEVEL = {"bsc": 1, "ba": 1, "beng": 1, "llb": 1, "bachelor": 1, "msc": 2, "ma": 2, "mba": 2, "meng": 2,
          "mph": 2, "mphil": 2, "llm": 2, "master": 2, "phd": 3, "doctor": 3}

CERTS = ["CFA", "FRM", "PRM", "CPA", "ACCA", "CIMA", "PMP", "PRINCE2", "CISSP", "CISA", "CISM", "CCNA", "CCNP",
         "CAIA", "FSA", "ASA", "ACAS", "FCAS", "FIA", "CERA", "CSM", "PSM", "ITIL", "TOEFL", "IELTS", "TOEIC",
         "DELF", "DALF", "TEF", "TCF", "JLPT", "HSK", "GRE", "GMAT", "CQF", "CAP", "CSPO", "CKA", "CKAD", "OSCP",
         "Security+", "Six Sigma"]
CERT_RX = re.compile(r"(?<![\w])(" + "|".join(re.escape(c) for c in sorted(CERTS, key=len, reverse=True)) +
                     r")(?:\s+Level\s+(?:I{1,3}|[123]))?(?![\w])"
                     r"|(?<![\w])AWS Certified(?:\s+[A-Z][\w-]*)+"
                     r"|(?<![\w])[A-Z][A-Za-z0-9+]{1,10}(?:\s[A-Z][A-Za-z0-9+]{1,10}){0,2}\s+(?:certification|certificate|charter(?:holder)?)\b")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _plain(s: str) -> str:
    return " " + re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+&]+", " ", _fold(s))).strip() + " "


# ---------------------------------------------------------------- extraction

def _blank(text: str, spans) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    return "".join(chars)


def _dates(text: str) -> tuple[list[tuple[str, tuple[int, int]]], list[tuple[int, int]]]:
    found, spans = [], []
    for m in MONTH_YEAR_RX.finditer(text):
        found.append((m.group(0), (int(m.group(2)), _MONTH_OF[_fold(m.group(1))])))
        spans.append(m.span())
    for m in NUM_MONTH_YEAR_RX.finditer(text):
        found.append((m.group(0), (int(m.group("y")), int(m.group(1)))))
        spans.append(m.span())
    for m in ISO_MONTH_RX.finditer(text):
        found.append((m.group(0), (int(m.group("y")), int(m.group(2)))))
        spans.append(m.span())
    return found, spans


def _value(num: str, suf: str) -> tuple[str, float]:
    v = float(num.replace(",", ""))
    s = (suf or "").strip().lower().replace(" ", "")
    if s == "%" or "cent" in s or "ciento" in s:
        return "pct", round(v, 6)
    mult = {"k": 1e3, "thousand": 1e3, "mil": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "millions": 1e6,
            "millones": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9, "milliard": 1e9, "milliards": 1e9}.get(s, 1.0)
    return "num", round(v * mult, 6)


def _strip_noise(text: str) -> str:
    text = URL_RX.sub(" ", text)
    text = EMAIL_RX.sub(" ", text)
    text = PHONE_RX.sub(lambda m: " " if len(re.sub(r"\D", "", m.group(0))) >= 9 else m.group(0), text)
    return LIST_MARKER.sub(" ", text)


def extract(text: str) -> dict:
    """Every checkable claim in ``text``: ``{"numbers": [(raw, kind, value)], "years": [(raw, y)],
    "dates": [(raw, (y, m))], "orgs": [raw], "degrees": [(raw, key)], "certs": [raw]}``."""
    t = _strip_noise(text or "")
    dates, spans = _dates(t)
    t2 = _blank(t, spans)
    years, yspans = [], []
    for m in YEAR_RX.finditer(t2):
        years.append((m.group(1), int(m.group(1))))
        yspans.append(m.span())
    t3 = _blank(t2, yspans)
    # degree and certification tokens can contain digits (PRINCE2): blank them before numbers
    degrees = []
    dspans = []
    for m in DEGREE_RX.finditer(t3):
        degrees.append((m.group(0).strip(), _degree_key(m.group(0))))
        dspans.append(m.span())
    certs = []
    for m in CERT_RX.finditer(t3):
        if _fold(m.group(0).split()[0]) in _NOT_ORG:
            continue
        certs.append(m.group(0).strip())
        dspans.append(m.span())
    t4 = _blank(t3, dspans)
    numbers = []
    for m in NUM_RX.finditer(t4):
        kind, v = _value(m.group("num"), m.group("suf") or "")
        raw = ((m.group("cur") or "") + m.group("num") + (m.group("suf") or "")).strip()
        numbers.append((raw, kind, v))
    orgs = []
    for m in ORG_RX.finditer(text or ""):
        org = re.sub(r"^the\s+", "", m.group(1).strip(" .,;:'’"), flags=re.I)
        org = re.sub(r"\s+(?:in|on|as|and|&)$", "", org)
        first = _fold(org.split()[0]) if org.split() else ""
        if not org or first in _NOT_ORG or first in _MONTH_OF or len(org) < 2:
            continue
        orgs.append(org)
    return {"numbers": numbers, "years": years, "dates": dates, "orgs": orgs, "degrees": degrees, "certs": certs}


def _degree_key(raw: str) -> str:
    f = re.sub(r"['’]s\b", "", _fold(raw))
    f = re.sub(r"[.\s]+", " ", f).strip()
    compact = f.replace(" ", "")
    if compact in _DEGREE_KEYS:
        return _DEGREE_KEYS[compact]
    for phrase, key in _DEGREE_KEYS.items():
        if " " in phrase and f.startswith(phrase):
            return key
    m = re.match(r"(bachelor|master|doctor)(?: of (.+))?", f)
    if m:
        if m.group(2):
            return f"{m.group(1)} of {m.group(2).replace(' degree', '').strip()}"
        return m.group(1)                                  # generic level: "a Master's degree"
    return compact


def _level(key: str) -> int:
    return _LEVEL.get(key.split(" ")[0], 0)


# ---------------------------------------------------------------- comparison

class _Facts:
    def __init__(self, fact_base: str):
        self.text = fact_base or ""
        self.plain = _plain(self.text)
        x = extract(self.text)
        self.values = {(k, v) for _, k, v in x["numbers"]}
        self.any_values = {v for _, _, v in x["numbers"]} | {float(y) for _, y in x["years"]}
        self.years = {y for _, y in x["years"]} | {y for _, (y, _) in x["dates"]}
        self.months = {d for _, d in x["dates"]}
        self.degrees = {k for _, k in x["degrees"]}
        self.levels = {_level(k) for k in self.degrees}

    def number_ok(self, kind: str, v: float) -> bool:
        if kind == "pct":
            return ("pct", v) in self.values
        return v in self.any_values or ("pct", v) in self.values

    def phrase_ok(self, s: str) -> bool:
        p = _plain(s).strip()
        return bool(p) and f" {p} " in self.plain

    def degree_ok(self, raw: str, key: str) -> bool:
        if key in self.degrees or self.phrase_ok(raw):
            return True
        if key in ("bachelor", "master", "doctor"):
            return _level(key) in self.levels
        m = re.match(r"(bachelor|master|doctor) of (.+)", key)
        if m:
            return _level(m.group(1)) in self.levels and self.phrase_ok(m.group(2))
        return False


def check(document: str, fact_base: str) -> list[str]:
    """Claims in ``document`` that ``fact_base`` does not contain (see the module docstring)."""
    facts = _Facts(fact_base)
    return _unsupported(extract(document), facts)


def _unsupported(x: dict, facts: _Facts) -> list[str]:
    out: list[str] = []
    for raw, kind, v in x["numbers"]:
        if not facts.number_ok(kind, v):
            out.append(raw)
    for raw, y in x["years"]:
        if y not in facts.years:
            out.append(raw)
    for raw, ym in x["dates"]:
        if ym not in facts.months:
            out.append(raw)
    for org in x["orgs"]:
        parts = [q for q in re.split(r"\s+(?:and|&|und)\s+", org) if q]
        if not (facts.phrase_ok(org) or all(facts.phrase_ok(q) for q in parts)):
            out.append(org)
    for raw, key in x["degrees"]:
        if not facts.degree_ok(raw, key):
            out.append(raw)
    for raw in x["certs"]:
        if not facts.phrase_ok(raw):
            out.append(raw)
    return list(dict.fromkeys(out))


def story_provenance(story_text: str, fact_base: str) -> list[dict]:
    """Sentences of an interview story that carry claims the fact base does not support:
    ``[{"sentence": str, "unsupported": [claim, ...]}]`` (empty when every claim is traceable)."""
    facts = _Facts(fact_base)
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", story_text or ""):
        s = sent.strip()
        if not s:
            continue
        bad = _unsupported(extract(s), facts)
        if bad:
            out.append({"sentence": s, "unsupported": bad})
    return out
