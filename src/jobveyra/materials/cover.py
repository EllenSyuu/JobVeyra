"""Cover-letter angles drawn only from the posting and the candidate's evidence.

``angles(p, cfg)`` returns::

    {"why_company": [sentences from the posting about its mission, product or users],
     "problems":    [what the role is hired to solve: responsibilities, then required items],
     "approach":    [{"requirement", "evidence", "source"}] for requirements the candidate evidences,
     "gaps":        [requirement text the candidate does not evidence]  (for the writer, never the letter),
     "tone":        "formal" | "neutral" | "casual",
     "language":    ISO 639-1 code of the posting,
     "keywords":    the requirement terms worth mirroring, most important first}

Nothing here is invented: every "why" sentence is quoted from the posting, and every approach
item names the skill or CV line that supports it.
"""
from __future__ import annotations

import re
from collections import Counter

from ..evaluate import lang
from ..evaluate.rubric import (_head_kind, _BULLET, candidate_corpus, display, extract_requirements, has_term,
                               norm, norm_term, track_of)

_WHY = re.compile(
    r"\b(?:our mission|mission is|we build|we are building|we're building|we help|we make|we exist|we believe|"
    r"we serve|we power|our product|our platform|our customers|our clients|our users|we are a|we're a|"
    r"founded in|is a leading|is the leading|our goal|our vision|our purpose|on a mission|"
    r"notre mission|nous aidons|nous construisons|nous sommes|nuestra misi[oó]n|ayudamos|somos una?|"
    r"nossa miss[aã]o|ajudamos|somos uma?|unsere mission|wir helfen)\b", re.I)
_FORMAL = re.compile(r"\b(?:we are seeking|the successful candidate|applicants? (?:must|should|will)|incumbent|"
                     r"shall|hereby|in accordance with|duly|candidates are invited|the organization|the organisation|"
                     r"under the supervision of|le ou la titulaire|la personne retenue|el candidato seleccionado)\b", re.I)
_CASUAL = re.compile(r"\b(?:awesome|rockstar|ninja|superstar|crush(?:ing)? it|hey|folks|vibes?|love to|"
                     r"geek out|kick-?ass|fun|we're|you'll|let's)\b|!|[\U0001F300-\U0001FAFF]", re.I)


def _sentences(text: str) -> list[str]:
    out = []
    for line in (text or "").splitlines():
        line = _BULLET.sub("", line.strip())
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
    return out


def _responsibilities(text: str) -> list[str]:
    out, in_resp = [], False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        hk = _head_kind(line)
        if hk:
            f = line.lower()
            in_resp = hk == "other" and bool(re.search(r"responsib|what you.?ll do|what you will do|the role|duties|"
                                                         r"missions|impact|day to day|in this role|tareas|aufgaben", f))
            continue
        if in_resp and _BULLET.match(line):
            out.append(_BULLET.sub("", line).strip())
    return out


def tone_of(text: str) -> str:
    t = text or ""
    words = max(len(t.split()), 1)
    formal = len(_FORMAL.findall(t))
    casual = len(_CASUAL.findall(t))
    if formal >= 2 and formal >= casual:
        return "formal"
    if casual / words > 0.01 and casual >= 3:
        return "casual"
    return "neutral"


def angles(p, cfg) -> dict:
    track = track_of(p.title, cfg.focus) if cfg.focus.tracks else None
    skills, cv_text = candidate_corpus(cfg, track)
    reqs = extract_requirements(p.text, vocab=skills)
    skill_terms = {norm_term(s): s for s in skills if norm_term(s)}
    cv_n = norm(cv_text) if cv_text else ""

    why = []
    for s in _sentences(p.text):
        if _WHY.search(s) and 20 <= len(s) <= 300 and s not in why:
            why.append(s)
    problems = _responsibilities(p.text)[:5]
    problems += [r.text for r in reqs if r.kind == "required" and r.source != "mention" and r.text not in problems]
    problems = problems[:8]

    approach, gaps = [], []
    for r in reqs:
        if not r.terms:
            continue
        ev = []
        for t in r.terms:
            if t in skill_terms:
                ev.append((display(t), "track skills"))
            elif cv_n and has_term(cv_n, t, cv_text):
                ev.append((display(t), "CV"))
        if ev:
            approach.append({"requirement": r.text, "kind": r.kind, "evidence": ", ".join(e for e, _ in ev),
                             "source": ", ".join(dict.fromkeys(s for _, s in ev))})
        else:
            gaps.append(r.text)

    weights: Counter = Counter()
    for r in reqs:
        for t in r.terms:
            weights[t] += 2 if r.kind == "required" else 1
    keywords = [display(t) for t, _ in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))][:10]

    return {"why_company": why[:3], "problems": problems, "approach": approach, "gaps": gaps,
            "tone": tone_of(p.text), "language": (p.lang or lang.detect(p.text) or "en").lower(),
            "keywords": keywords}
