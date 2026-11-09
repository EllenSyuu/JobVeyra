"""Does a document read as written by the candidate? Deterministic checks for the tells.

``check(text, kind="letter"|"cv", lang="en")`` returns findings ``{"rule", "severity", "text", "why"}``
with severity ``"fail"`` (never acceptable) or ``"warn"`` (worth a second look). Rules:

  tool_mention      names an AI or writing tool, or says the text was generated (always fail)
  stock_phrase      openers, fillers and transitions that read as template or machine text
  inflated_verb     "spearheaded", "leveraged", "orchestrated" where a plain verb says it
  empty_praise      abstract praise of the employer instead of one concrete fact
  summary_closer    "In summary", "Ultimately", "I am confident that"
  em_dash           an em dash (a common tell in generated prose)
  same_opening      three or more bullets or paragraphs starting with the same word
  uniform_bullets   every bullet nearly the same length, the "Verb X, resulting in Y" rhythm
  bold_label        bold labels inside a letter body

``materials.voice`` in jobveyra.yml sets how warnings count: ``warn`` (default) reports them,
``strict`` makes them block like failures, ``off`` keeps only ``tool_mention``.
"""
from __future__ import annotations

import re
import statistics

TOOLS = re.compile(
    r"\b(?:chat\s?gpt|gpt-?\d|openai|claude(?:\s+code)?|anthropic|gemini|copilot|bard|llama|mistral|"
    r"jasper|grammarly\s+go|large language model|llm|ai[- ](?:assisted|generated|written|tool|writer)|"
    r"(?:generated|written|drafted) (?:by|with|using) (?:an? )?(?:ai|tool|assistant|model))\b", re.I)

STOCK = {
    "en": [r"i am writing to express my (?:keen |strong )?interest", r"i am (?:thrilled|excited) to (?:apply|bring)",
           r"in today'?s (?:fast-paced|rapidly|ever)", r"\bdelve\b", r"\btapestry\b", r"navigate the (?:complex )?landscape",
           r"a testament to", r"hit the ground running", r"\bsynerg(?:y|ies)\b", r"drive results",
           r"leverage my (?:skills|experience|expertise)", r"i (?:truly )?believe i would be a great fit",
           r"i am passionate about", r"\bmoreover\b", r"\bfurthermore\b", r"\badditionally\b",
           r"not only .{3,60} but also", r"perfect fit", r"proven track record", r"dynamic team",
           r"(?:fast|ever)-evolving", r"cutting-edge", r"wealth of experience", r"unique blend"],
    "fr": [r"je me permets de vous (?:adresser|écrire)", r"c'est avec (?:un grand )?(?:enthousiasme|intérêt) que",
           r"dans un monde en (?:constante|perpétuelle) évolution", r"\bde plus\b", r"\ben outre\b", r"\bpar ailleurs\b",
           r"force de proposition", r"je suis passionnée? par", r"profil idéal", r"véritable atout"],
    "es": [r"me dirijo a ustedes", r"es un placer para mí", r"en el mundo actual", r"\badem[aá]s\b",
           r"\basimismo\b", r"apasionad[oa] por", r"perfil ideal"],
    "pt": [r"venho por meio desta", r"no mundo atual", r"\bal[eé]m disso\b", r"\badicionalmente\b",
           r"apaixonad[oa] por", r"perfil ideal"],
}
INFLATED = re.compile(r"\b(?:spearhead(?:ed|ing)?|orchestrat(?:ed|ing)|leverag(?:ed|ing)|synergi[sz](?:ed|ing)|"
                      r"revolutioni[sz](?:ed|ing)|champion(?:ed|ing)|utili[sz](?:ed|ing))\b", re.I)
PRAISE = re.compile(r"\byour (?:innovative|forward-thinking|cutting-edge|dynamic|world-class|esteemed|prestigious|"
                    r"renowned|inspiring)\b|\b(?:votre|vos) (?:prestigieu|renomm)\w*", re.I)
CLOSERS = re.compile(r"(?:^|[.!?]\s+)(?:in summary|in conclusion|to summarize|ultimately|overall),|"
                     r"\bi am confident that\b|\bje suis convaincue? que\b", re.I)
EM_DASH = re.compile(r"—|(?<=\w) -- (?=\w)")
BOLD = re.compile(r"\*\*[^*]{2,40}\*\*\s*:|\\textbf\{[^}]{2,40}\}\s*:")


def _f(rule: str, severity: str, text: str, why: str) -> dict:
    return {"rule": rule, "severity": severity, "text": text.strip()[:120], "why": why}


def _units(text: str, kind: str) -> list[str]:
    if kind == "cv":
        return [m.group(1) for m in re.finditer(r"^\s*(?:[-*•]|\\item)\s*(?:\\small\s*)?(.+)$", text, re.M)]
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def check(text: str, *, kind: str = "letter", lang: str = "en") -> list[dict]:
    out: list[dict] = []
    for m in TOOLS.finditer(text):
        out.append(_f("tool_mention", "fail", m.group(0), "documents must not name or hint at a writing tool"))
    for pat in STOCK.get(lang, []) + (STOCK["en"] if lang != "en" else []):
        for m in re.finditer(pat, text, re.I):
            out.append(_f("stock_phrase", "warn", m.group(0), "stock phrasing; say the specific thing instead"))
    for m in INFLATED.finditer(text):
        out.append(_f("inflated_verb", "warn", m.group(0), "a plain verb (built, ran, wrote, led) reads as you"))
    for m in PRAISE.finditer(text):
        out.append(_f("empty_praise", "warn", m.group(0), "name one concrete, verified thing about the employer"))
    for m in CLOSERS.finditer(text):
        out.append(_f("summary_closer", "warn", m.group(0), "end on what happens next, not a summary"))
    for m in EM_DASH.finditer(text):
        s = text[max(0, m.start() - 30): m.end() + 30].replace("\n", " ")
        out.append(_f("em_dash", "warn", s, "use a comma, colon or full stop"))
    units = _units(text, kind)
    firsts = [re.sub(r"[^\w]", "", u.split()[0].lower()) for u in units if u.split()]
    for w in sorted(set(firsts)):
        if w and firsts.count(w) >= 3 and w not in ("i", "je", "yo", "eu"):
            out.append(_f("same_opening", "warn", w, f"{firsts.count(w)} {('bullets' if kind == 'cv' else 'paragraphs')} "
                                                     "start the same way; vary them"))
    if kind == "cv" and len(units) >= 5:
        lens = [len(u) for u in units]
        if statistics.pstdev(lens) / max(1, statistics.mean(lens)) < 0.08:
            out.append(_f("uniform_bullets", "warn", f"{len(units)} bullets", "every bullet is about the same length; "
                          "real bullets vary with what they say"))
    if kind == "letter":
        for m in BOLD.finditer(text):
            out.append(_f("bold_label", "warn", m.group(0), "plain paragraphs read as a letter, labels as a form"))
    return out


def blocking(findings: list[dict], level: str = "warn") -> list[dict]:
    """The findings that block a build at the configured level."""
    if level == "strict":
        return findings
    return [f for f in findings if f["severity"] == "fail"]
