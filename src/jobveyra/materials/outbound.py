"""Outbound guard: no document sent to an employer argues against the candidate.

``check(text)`` returns one message per hit, ``line N: “matched words” (why)``, for wording
that volunteers a gap, a missing skill, a weakness or a hedge, discloses a sponsorship need
nobody asked about, names an AI writing tool, or (in form answers) states a negative answer
the candidate has not confirmed. English, French, Spanish and Portuguese.

Internal notes (evaluations, reviews) are not meant to pass through this: gaps belong there.
A line that ends with ``(confirmed)`` or ``[confirmed]`` is accepted as written: the
candidate has approved that exact wording, e.g. an answer to a direct sponsorship question.

``kind``: ``letter`` (default: every rule), ``cv`` (skips prose-only rules such as stating a
language level, which a CV's language line legitimately does) and ``answers`` (adds the
negative-answer rules for form answers: "Kubernetes: 0 years", "SQL: No").
"""
from __future__ import annotations

import re

CONFIRMED = re.compile(r"[(\[]\s*confirmed\b[^)\]]*[)\]]\s*$", re.I)

_A = r"['’]"
RULES: list[tuple[str, str, str]] = [
    # (regex, reason, scope) scope: all | letter
    # --- English
    (r"\bI (?:currently |still |unfortunately )?lack\b", "volunteers a lack", "all"),
    (r"\bunfortunately,? I\b", "apologises for the candidate", "all"),
    (rf"\bI (?:do not|don{_A}t|did not|didn{_A}t|cannot|can{_A}t|can not) (?:yet |currently |really )?"
     r"(?:have|know|use|possess|bring|speak|meet|hold)\b", "volunteers something the candidate does not have", "all"),
    (rf"\bI (?:have not|haven{_A}t|have never|never) (?:yet |actually |really )?(?:\w+ ){{0,2}}"
     r"(?:used|worked|built|done|had|held|led|managed|programmed|coded|touched)\b", "volunteers missing experience", "all"),
    (r"\b(?:no|limited|little|minimal|basic|scant) (?:direct |prior |hands-on |professional |formal |practical |"
     r"real-world |commercial |industry )?(?:experience|exposure|background|knowledge|familiarity)\b",
     "states limited experience", "all"),
    (r"\bnot (?:yet |very |particularly |overly |fully )?(?:proficient|fluent|experienced|familiar|an expert|"
     r"strong|comfortable|confident|qualified)\b", "states a weakness", "all"),
    (rf"\b(?:I am|I{_A}m) not\b(?! only| just| afraid| the only)", "negative self-description", "all"),
    (rf"\b(?:I am|I{_A}m) (?:new to|still learning|a beginner|a novice)\b", "presents the candidate as a beginner", "all"),
    (r"\b(?:my|the|main|biggest|obvious|clear) (?:skills? )?gaps?\b(?! (?:analysis|filling|in the market))",
     "talks about gaps", "all"),
    (r"\b(?:weakness(?:es)?|shortcomings?|drawbacks?)\b", "names a weakness", "all"),
    (r"\b(?:admittedly|to be honest|to be fair|frankly|I must admit|I confess)\b", "hedges or confesses", "all"),
    (rf"\b(?:I would|I will|I{_A}d|I{_A}ll) (?:need to |have to |expect to |be able to )?"
     r"(?:learn|pick up|get up to speed|be learning|catch up)\b", "says the candidate would have to learn the job", "all"),
    (r"\b(?:only|merely|just) (?:from |through |via )?(?:coursework|self-study|a course|courses|tutorials|"
     r"side projects|a bootcamp)\b", "discounts the candidate's own experience", "all"),
    (r"\b(?:I )?(?:would|will|shall) (?:require|need) (?:a )?(?:visa |work permit |immigration )?sponsorship\b",
     "discloses a sponsorship need nobody asked about", "all"),
    (r"\bI (?:require|need) (?:a )?(?:work )?(?:visa|permit|sponsorship)\b",
     "discloses a sponsorship need nobody asked about", "all"),
    (r"\bmy (?:english|french|spanish|portuguese|german|italian|dutch) is (?:basic|limited|intermediate|rusty|"
     r"not (?:yet )?fluent|developing|improving|a work in progress)\b", "volunteers a language level", "letter"),
    (r"\bas an AI(?: language model)?\b|\b(?:ChatGPT|GPT-[0-9o]+|Claude Code|Claude AI|Gemini AI|"
     r"AI[- ]generated|generated (?:by|with) (?:AI|an AI|a language model)|written (?:by|with)(?: the help of)? "
     r"(?:AI|an AI|ChatGPT))\b", "mentions an AI writing tool", "all"),
    # --- French
    (rf"\bje n{_A}ai (?:pas|jamais|aucune?) (?:encore |vraiment )?(?:d{_A}exp[ée]rience|travaill[ée]|utilis[ée]|"
     rf"de connaissances?|eu|d{_A}expertise|de dipl[ôo]me)", "volunteers missing experience (fr)", "all"),
    (r"\bje ne (?:ma[iî]trise|connais|parle|poss[èe]de|suis) pas\b", "negative self-description (fr)", "all"),
    (r"\b(?:mes|mon|ma) (?:lacunes?|faiblesses?|point faible|points faibles|manque)\b", "names a weakness (fr)", "all"),
    (rf"\b(?:peu|pas|aucune) d{_A}(?:exp[ée]rience|expertise)\b", "states limited experience (fr)", "all"),
    (r"\bmalheureusement,? je\b", "apologises for the candidate (fr)", "all"),
    (r"\bje (?:devrai|devrais|vais devoir|dois encore) (?:apprendre|me former)\b",
     "says the candidate would have to learn the job (fr)", "all"),
    (rf"\b(?:j{_A}aurai|j{_A}aurais) besoin d{_A}(?:un )?(?:parrainage|permis de travail|visa)\b|"
     r"\bje (?:n[ée]cessite|n[ée]cessiterai) (?:un )?(?:parrainage|permis|visa)\b",
     "discloses a sponsorship need nobody asked about (fr)", "all"),
    (r"\bmon (?:anglais|fran[cç]ais|espagnol|portugais) est (?:basique|limit[ée]|interm[ée]diaire|moyen)\b",
     "volunteers a language level (fr)", "letter"),
    # --- Spanish
    (r"\bno tengo (?:mucha |suficiente )?(?:experiencia|conocimientos?|dominio|formaci[óo]n)\b",
     "volunteers missing experience (es)", "all"),
    (r"\bnunca he (?:trabajado|usado|utilizado|manejado)\b", "volunteers missing experience (es)", "all"),
    (r"\b(?:poca|escasa|sin|nula) experiencia\b", "states limited experience (es)", "all"),
    (r"\b(?:mis|mi) (?:debilidad(?:es)?|carencias?|punto d[ée]bil|puntos d[ée]biles)\b", "names a weakness (es)", "all"),
    (r"\bno (?:domino|conozco|manejo|hablo) (?:bien )?\b", "negative self-description (es)", "all"),
    (r"\b(?:desafortunadamente|lamentablemente),? (?:no|yo)\b", "apologises for the candidate (es)", "all"),
    (r"\bno soy (?:experto|experta|especialista)\b", "negative self-description (es)", "all"),
    (r"\b(?:necesitar[ée]|necesitar[íi]a|requerir[ée]|requerir[íi]a) (?:un )?(?:patrocinio|visado|visa)\b",
     "discloses a sponsorship need nobody asked about (es)", "all"),
    (r"\btendr[ée] que aprender\b", "says the candidate would have to learn the job (es)", "all"),
    # --- Portuguese
    (r"\bn[ãa]o tenho (?:muita |suficiente )?(?:experi[êe]ncia|conhecimentos?|dom[íi]nio|forma[çc][ãa]o)\b",
     "volunteers missing experience (pt)", "all"),
    (r"\bnunca (?:trabalhei|usei|utilizei)\b", "volunteers missing experience (pt)", "all"),
    (r"\b(?:pouca|sem|nenhuma) experi[êe]ncia\b", "states limited experience (pt)", "all"),
    (r"\b(?:minhas?|meus?) (?:fraquezas?|lacunas?|ponto fraco|pontos fracos)\b", "names a weakness (pt)", "all"),
    (r"\bn[ãa]o (?:domino|conhe[çc]o|falo)\b", "negative self-description (pt)", "all"),
    (r"\binfelizmente,? (?:n[ãa]o|eu)\b", "apologises for the candidate (pt)", "all"),
    (r"\bn[ãa]o sou (?:especialista|fluente|experiente)\b", "negative self-description (pt)", "all"),
    (r"\bprecisar(?:ei|ia) de (?:um )?(?:patroc[íi]nio|visto)\b",
     "discloses a sponsorship need nobody asked about (pt)", "all"),
    (r"\bterei que aprender\b", "says the candidate would have to learn the job (pt)", "all"),
]
_COMPILED = [(re.compile(rx, re.I), why, scope) for rx, why, scope in RULES]

# form answers: "Skill: 0", "Skill: none", "Skill | No"
NEGATIVE_ANSWER = re.compile(
    r"^\s*[-*|]?\s*(?P<q>[^:|\n]{2,80}?)\s*[:|]\s*\**(?P<a>0(?:\.0)?|zero|none|no|non|nope|aucune?|ninguna?|"
    r"nenhuma?|n/?a|never|jamais|nunca)\**\s*(?:years?|yrs?|ans?|años|anos)?\s*(?:[;,|].*)?$", re.I)
ZERO_YEARS = re.compile(r"(?P<skill>[A-Za-z][\w+#./ -]{0,40}?)\s*:\s*0\b(?!\.\d)")
# questions whose negative answer is a standing, deliberate choice of the candidate
STANDING_NEGATIVE = re.compile(
    r"sponsor|parrain|patroc|visa|criminal|convict|non-compete|non-concurrence|relatives?|family member|conflict of "
    r"interest|previous(?:ly)? (?:worked|employed)|former employee|self-identif|disabilit|veteran|indigenous|"
    r"gender|pronoun|race|ethnic|prefer not|relocat|travel", re.I)


def strip_markup(text: str) -> str:
    """Drop LaTeX comments and unwrap the common formatting commands so rules see the words."""
    text = re.sub(r"(?<!\\)%.*", "", text or "")
    for _ in range(3):
        text = re.sub(r"\\(?:textit|textbf|emph|underline|textsc|mbox)\{([^{}]*)\}", r"\1", text)
        text = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
    text = text.replace("\\&", "&").replace("\\%", "%").replace("\\#", "#").replace("~", " ")
    return re.sub(r"[*_]{1,2}([^*_\n]+)[*_]{1,2}", r"\1", text)


def check(text: str, *, kind: str = "letter") -> list[str]:
    """Self-negative or disqualifying wording in outbound ``text`` (empty list = PASS)."""
    if kind not in ("letter", "cv", "answers"):
        raise ValueError("kind must be letter, cv or answers")
    hits: list[str] = []
    body = strip_markup(text)
    for n, line in enumerate(body.splitlines(), 1):
        if not line.strip() or CONFIRMED.search(line):
            continue
        for rx, why, scope in _COMPILED:
            if scope == "letter" and kind != "letter":
                continue
            m = rx.search(line)
            if m:
                hits.append(f"line {n}: “{m.group(0).strip()}” ({why})")
        if kind == "answers" and not STANDING_NEGATIVE.search(line):
            z = list(ZERO_YEARS.finditer(line))
            for m in z:
                hits.append(f"line {n}: “{m.group(0).strip()}” (a skill missing from the CV is unknown, not zero: "
                            "ask the candidate)")
            m = NEGATIVE_ANSWER.match(line)
            if m and not z:
                hits.append(f"line {n}: “{line.strip()[:80]}” (negative answer the candidate has not confirmed)")
    return hits
