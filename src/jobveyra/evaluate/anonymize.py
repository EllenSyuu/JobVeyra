"""Mask personal data before any text leaves the machine for a model, and restore it after.

``mask(text, candidate)`` replaces, in this order:

* every e-mail address -> ``[EMAIL_1]``, ``[EMAIL_2]`` ... (the same address keeps its token);
* the candidate's links (with or without scheme / ``www.``) -> ``[LINK_1]`` ...;
* every phone number -> ``[PHONE_1]`` ...; the candidate's own number is recognised by its
  digits whatever the formatting (``+1 (212) 555-0100`` == ``212.555.0100``);
* the candidate's full name -> ``[NAME]``, then each part -> ``[FIRST_NAME]``,
  ``[LAST_NAME]``, ``[MIDDLE_NAME_1]`` ... matched case- and accent-insensitively.

It returns ``(masked, mapping)`` where ``mapping`` is token -> original; ``unmask`` reverses it.
"""
from __future__ import annotations

import re
import unicodedata

EMAIL_RX = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RX = re.compile(r"(?<![\w+])(?:\+|00)?\(?\d[\d\s().\- ]{5,}\d(?!\w)")
_RANGE = re.compile(r"^\(?\d{4}\)?\s*[-–]\s*\(?\d{4}\)?$")


def _variants() -> dict[str, str]:
    out: dict[str, set[str]] = {}
    for cp in list(range(0x00C0, 0x0250)) + list(range(0x1E00, 0x1F00)):
        ch = chr(cp)
        base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
        if len(base) == 1 and base.isascii() and base.isalpha():
            out.setdefault(base.lower(), set()).update({ch, ch.lower(), ch.upper()})
    return {k: "".join(sorted(v)) for k, v in out.items()}


_VAR = _variants()


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


def name_pattern(name: str) -> re.Pattern:
    """Regex for a name that ignores case, accents and the kind of space or hyphen between parts."""
    parts = []
    for ch in _fold(name.strip()):
        if ch.isalpha() and ch.isascii():
            cls = ch + ch.upper() + _VAR.get(ch, "")
            parts.append("[" + re.escape(cls) + "]")
        elif ch.isspace():
            parts.append(r"[\s ]+")
        elif ch in "-‐–'’":
            parts.append(r"[-‐–'’\s]?")
        else:
            parts.append(re.escape(ch))
    return re.compile(r"(?<!\w)" + "".join(parts) + r"(?!\w)", re.I)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _link_core(link: str) -> str:
    s = re.sub(r"^[a-z]+://", "", (link or "").strip(), flags=re.I)
    s = re.sub(r"^www\.", "", s, flags=re.I)
    return s.rstrip("/")


def mask(text: str, candidate) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    out = text or ""

    # e-mail addresses (all of them: a model never needs one)
    seen: dict[str, str] = {}

    def email_sub(m: re.Match) -> str:
        key = m.group(0).lower()
        if key not in seen:
            tok = f"[EMAIL_{len(seen) + 1}]"
            seen[key] = tok
            mapping[tok] = m.group(0)
        return seen[key]

    cand_email = (getattr(candidate, "email", "") or "").strip()
    if cand_email:                                   # the candidate's address is always EMAIL_1
        seen[cand_email.lower()] = "[EMAIL_1]"
        mapping["[EMAIL_1]"] = cand_email
    out = EMAIL_RX.sub(email_sub, out)

    # the candidate's links
    n = 0
    for link in getattr(candidate, "links", []) or []:
        core = _link_core(link)
        if not core:
            continue
        rx = re.compile(r"(?:https?://)?(?:www\.)?" + re.escape(core) + r"/?(?![\w/-])", re.I)
        if rx.search(out):
            n += 1
            tok = f"[LINK_{n}]"
            mapping[tok] = link
            out = rx.sub(tok, out)

    # phone numbers
    cand_digits = _digits(getattr(candidate, "phone", "") or "")
    phones: dict[str, str] = {}

    def same_phone(d: str) -> bool:
        if not cand_digits or len(cand_digits) < 7:
            return False
        tail = min(len(cand_digits), len(d), 10)
        return tail >= 7 and d[-tail:] == cand_digits[-tail:] and abs(len(d) - len(cand_digits)) <= 4

    def phone_sub(m: re.Match) -> str:
        raw = m.group(0)
        d = _digits(raw)
        if _RANGE.match(raw.strip()):
            return raw
        is_cand = same_phone(d)
        if not is_cand and not (len(d) >= 9 or (raw.startswith(("+", "00")) and len(d) >= 8)):
            return raw
        key = "cand" if is_cand else d
        if key not in phones:
            tok = f"[PHONE_{len(phones) + 1}]"
            phones[key] = tok
            mapping[tok] = getattr(candidate, "phone", "") if is_cand else raw
        return phones[key]

    if cand_digits:
        phones["cand"] = "[PHONE_1]"
        mapping["[PHONE_1]"] = getattr(candidate, "phone", "")
    out = PHONE_RX.sub(phone_sub, out)
    if "[PHONE_1]" in mapping and "[PHONE_1]" not in out:
        del mapping["[PHONE_1]"]
    if cand_email and "[EMAIL_1]" not in out:
        del mapping["[EMAIL_1]"]

    # the name: full first, then the parts
    name = (getattr(candidate, "name", "") or "").strip()
    if name:
        rx = name_pattern(name)
        if rx.search(out):
            mapping["[NAME]"] = name
            out = rx.sub("[NAME]", out)
        parts = [p for p in re.split(r"\s+", name) if len(_fold(p)) >= 2]
        if len(parts) > 1:
            labels = ["[FIRST_NAME]"] + [f"[MIDDLE_NAME_{i}]" for i in range(1, len(parts) - 1)] + ["[LAST_NAME]"]
            pairs = list(zip(parts, labels))
            for part, tok in list(pairs):                 # "Martín-López": each half on its own too
                pieces = [x for x in re.split(r"[-‐–'’]", part) if len(_fold(x)) >= 2]
                if len(pieces) > 1:
                    pairs += [(x, f"{tok[:-1]}_PART_{i}]") for i, x in enumerate(pieces, 1)]
            for part, tok in sorted(pairs, key=lambda x: -len(x[0])):
                prx = name_pattern(part)
                if prx.search(out):
                    mapping[tok] = part
                    out = prx.sub(tok, out)
    return out, mapping


def unmask(text: str, mapping: dict[str, str]) -> str:
    out = text or ""
    for tok in sorted(mapping, key=len, reverse=True):
        out = out.replace(tok, mapping[tok])
    return out
