"""ATS text check: what an applicant-tracking parser will read from a CV's text layer.

``check_text(text, keywords)`` takes the text extracted from the PDF (pypdf / pdftotext) and the
posting's keywords and reports keyword coverage, contact details as literal text, extraction
noise (``(cid:123)`` markers, U+FFFD replacement characters, private-use glyphs, unexpanded
ligatures and the word gaps a dropped ligature leaves) and very long lines, then a 0-100 score
with the reason for every point lost.

Keywords are matched with the rubric's normalisation (case, accents, plurals and synonyms such
as ML / machine learning), so a synonym counts; tightening it to the posting's exact term is
still worth doing, which ``synonym_only`` lists.
"""
from __future__ import annotations

import re

from ..evaluate.rubric import has_term, norm, norm_term

EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RX = re.compile(r"(?<![\w])\+?\(?\d[\d\s().-]{6,}\d(?![\w])")
CID_RX = re.compile(r"\(cid:\d+\)")
LIGATURES = "ﬀﬁﬂﬃﬄﬅﬆ"
# words that lose "fi", "ff", "fl", "ffi" when a ligature glyph has no text mapping
LIG_GAP_RX = re.compile(
    r"\b(?:e (?:cient|ciency|ective|ectively)|o (?:ered|ering|ce|cer|cers|cial)|di (?:erent|erence|cult|culty)|"
    r"su cient|signi cant|speci c|identi ed|veri ed|certi (?:ed|cation)|quali (?:ed|cation|cations)|modi ed|"
    r"classi cation|bene ts?|con (?:dent|guration)|in uence|work ows?|pro (?:le|les|cient|ciency)|de ned?|re ned?)\b"
    r"|(?<![\w-])(?:nancial|nance|rst|eld|elds|xed)(?![\w-])")
LONG_LINE = 160


def _literal(text: str, kw: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(kw.strip()) + r"(?![\w])", text, re.I) is not None


def check_text(text: str, keywords: list[str]) -> dict:
    text = text or ""
    n = norm(text)
    kws = [k for k in dict.fromkeys(k.strip() for k in keywords or []) if k]
    matched, missing, synonym_only = [], [], []
    for k in kws:
        if has_term(n, k, text) or (norm_term(k) and f" {norm_term(k)} " in n):
            matched.append(k)
            if not _literal(text, k):
                synonym_only.append(k)
        else:
            missing.append(k)
    coverage = round(100.0 * len(matched) / len(kws), 1) if kws else 100.0

    phones = [m.group(0) for m in PHONE_RX.finditer(text) if len(re.sub(r"\D", "", m.group(0))) >= 9
              and not re.fullmatch(r"\(?\d{4}\)?\s*[-–]\s*\(?\d{4}\)?", m.group(0).strip())]
    noise = {"cid": len(CID_RX.findall(text)), "replacement": text.count("�"),
             "private_use": len(re.findall(r"[-]", text)),
             "ligatures": sum(text.count(c) for c in LIGATURES), "ligature_gaps": len(LIG_GAP_RX.findall(text))}
    lines = text.splitlines()
    long_lines = sum(1 for ln in lines if len(ln) > LONG_LINE)

    score, reasons = 100.0, []
    if not text.strip():
        return {"coverage": 0.0, "matched": [], "missing": kws, "synonym_only": [], "has_email": False,
                "has_phone": False, "noise": noise, "long_lines": 0, "score": 0,
                "reasons": ["no text could be extracted: an ATS sees an empty document"]}
    lost = round(50 * (100 - coverage) / 100, 1)
    if lost:
        score -= lost
        reasons.append(f"-{lost:g}: keyword coverage {coverage:g}% (missing: {', '.join(missing[:8])}"
                       f"{'…' if len(missing) > 8 else ''})")
    has_email = bool(EMAIL_RX.search(text))
    has_phone = bool(phones)
    if not has_email:
        score -= 15
        reasons.append("-15: no e-mail address in the text layer")
    if not has_phone:
        score -= 10
        reasons.append("-10: no phone number in the text layer")
    if noise["cid"]:
        score -= 20
        reasons.append(f"-20: {noise['cid']} (cid:N) markers: a font has no text mapping")
    if noise["replacement"] or noise["private_use"]:
        score -= 15
        reasons.append(f"-15: {noise['replacement'] + noise['private_use']} unreadable characters (U+FFFD / private use)")
    if noise["ligatures"] or noise["ligature_gaps"] >= 2:
        score -= 10
        reasons.append(f"-10: ligature problems ({noise['ligatures']} glyphs, {noise['ligature_gaps']} split words)")
    if long_lines > 5:
        score -= 5
        reasons.append(f"-5: {long_lines} lines over {LONG_LINE} characters (columns may have merged)")
    return {"coverage": coverage, "matched": matched, "missing": missing, "synonym_only": synonym_only,
            "has_email": has_email, "has_phone": has_phone, "noise": noise, "long_lines": long_lines,
            "score": int(round(max(0.0, score))), "reasons": reasons}
