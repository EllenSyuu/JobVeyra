"""Posting language detection and required-language phrases.

``detect(text)`` is a small stopword vote for en, fr, es, pt, de, it and nl, plus script
detection for zh and ja. It needs no model and no data files: a job posting is long enough
that a few dozen function words decide it reliably.

``required_languages(text)`` finds language demands ("fluent French required", "bilingue",
"français requis", "an asset: Spanish") and says whether each is required or preferred and
the CEFR level it implies.
"""
from __future__ import annotations

import re
import unicodedata

CODES = ("en", "fr", "es", "pt", "de", "it", "nl", "zh", "ja")

_STOP = {
    "en": "the and of to in with for you we our is are will be on as this that your from have an or "
          "team role work about who what which they their",
    "fr": "les des et une pour avec vous nous dans sur aux votre notre sera etre poste est sont du au "
          "qui que ou chez nos vos",
    "es": "el los las y del en con para una por que nuestro nuestra trabajo equipo somos buscamos "
          "es son tu sus como",
    "pt": "o os e do da dos das em com para uma por que nosso nossa trabalho equipe voce nao sao "
          "na no ao como seu sua",
    "de": "der die das und mit fur wir sie ist sind ein eine zu von auf im unser ihre bei dich du "
          "oder nicht auch",
    "it": "il lo gli e di del della con per una che sono siamo nostro lavoro nel alla le dei "
          "anche come sua",
    "nl": "de het een en van met voor wij je jij ons onze zijn is bij als op ook niet naar wat",
}
_WEIGHT: dict[str, dict[str, float]] = {}
_counts: dict[str, int] = {}
for _c, _words in _STOP.items():
    for _w in set(_words.split()):
        _counts[_w] = _counts.get(_w, 0) + 1
for _c, _words in _STOP.items():
    _WEIGHT[_c] = {w: 1.0 / _counts[w] for w in set(_words.split())}

# Language names in the languages postings are usually written in (accent-folded, lowercase).
NAMES = {
    "en": ["english", "anglais", "ingles", "englisch", "inglese", "engels"],
    "fr": ["french", "francais", "frances", "franzosisch", "francese", "frans"],
    "es": ["spanish", "espagnol", "espanol", "spanisch", "spagnolo", "espanhol", "castellano", "spaans"],
    "pt": ["portuguese", "portugais", "portugues", "portugiesisch", "portoghese", "portugees"],
    "de": ["german", "allemand", "aleman", "deutsch", "tedesco", "alemao", "duits"],
    "it": ["italian", "italien", "italiano", "italienisch", "italiaans"],
    "nl": ["dutch", "neerlandais", "hollandais", "neerlandes", "niederlandisch", "olandese", "nederlands"],
    "zh": ["chinese", "mandarin", "cantonese", "chinois", "chino", "chines", "chinesisch", "cinese"],
    "ja": ["japanese", "japonais", "japones", "japanisch", "giapponese", "japans"],
}
_NAME_RX = re.compile(r"\b(" + "|".join(sorted({n for v in NAMES.values() for n in v}, key=len, reverse=True)) + r")\b")
_NAME_TO_CODE = {n: c for c, v in NAMES.items() for n in v}

_PREF_CUES = re.compile(r"\b(prefer\w*|asset|a plus|is a plus|nice to have|bonus|desirable|advantage\w*|ideally|"
                        r"beneficial|atout|souhait\w*|apprecie\w*|un plus|valorable|deseable|se valorara|valoriza\w*|"
                        r"diferencial|wunschenswert|von vorteil|gradit\w|preferibil\w*|pluspunkt)\b")
_REQ_CUES = re.compile(r"\b(required|requires?|requirement|must|mandatory|essential|necessary|fluen\w*|proficien\w*|"
                       r"command of|native|excellent|strong|requis\w*|exige\w*|obligatoire|maitrise\w*|indispensable|"
                       r"imprescindible|requerid\w*|obligatori\w*|necesari\w*|dominio|fluid\w*|obrigatori\w*|"
                       r"exigid\w*|erforderlich|fliessend|verhandlungssicher|richiest\w*|vereist|bilingu\w*|"
                       r"working knowledge|conversational|intermediate|basic)\b")
_LOW_LEVEL = re.compile(r"\b(working knowledge|conversational|intermediate|basic|notions|intermedio|basico|basique)\b")
_BILINGUAL = re.compile(r"\bbilingu(?:al|e|ism|isme)\b")

LEVELS = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6, "native": 7, "mother tongue": 7, "bilingual": 7,
          "fluent": 5, "advanced": 5, "full professional": 5, "professional": 4, "working": 4,
          "upper intermediate": 4, "intermediate": 3, "conversational": 3, "elementary": 2, "basic": 2,
          "beginner": 1}


def fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


def scores(text: str) -> dict[str, float]:
    """Per-language vote, normalised by the number of tokens (latin-script languages only)."""
    toks = re.findall(r"[a-z]+", fold(text))
    out = {c: 0.0 for c in _STOP}
    for t in toks:
        for c, w in _WEIGHT.items():
            if t in w:
                out[c] += w[t]
    n = max(len(toks), 1)
    return {c: v / n for c, v in out.items()}


def detect(text: str) -> str:
    """ISO 639-1 code of the dominant language, or '' when the text is too short to tell."""
    if not text or not text.strip():
        return ""
    kana = len(re.findall(r"[぀-ヿ]", text))
    han = len(re.findall(r"[一-鿿]", text))
    latin = len(re.findall(r"[A-Za-zÀ-ɏ]", text))
    if kana >= 3 and kana >= 0.05 * (kana + han):
        return "ja"
    if han >= 10 and han >= 0.2 * (han + latin):
        return "zh"
    s = scores(text)
    best = max(s, key=s.get)
    toks = len(re.findall(r"[a-z]+", fold(text)))
    if s[best] * toks < 2.0:
        return ""
    return best


def level_rank(level: str) -> int:
    """CEFR-ish rank 0..7 for a level string ('C1', 'native', 'fluent (C1)', 'B2+')."""
    f = fold(level or "").strip()
    m = re.search(r"\b([abc][12])\b", f)
    if m:
        return LEVELS[m.group(1)]
    for k in sorted(LEVELS, key=len, reverse=True):
        if k in f:
            return LEVELS[k]
    return 0


def required_languages(text: str, *, country: str = "") -> dict[str, dict]:
    """``{code: {"kind": "required"|"preferred", "level": "B2"|"B1", "quote": str}}``.

    A language counts only when a cue sits next to its name ("fluent", "required", "an asset"...).
    A preference cue wins over a requirement cue in the same window ("fluent Spanish is an asset").
    "Bilingual" with no language named means English and French when the job is in Canada or
    the text mentions French.
    """
    f = fold(text)
    out: dict[str, dict] = {}

    def put(code: str, kind: str, level: str, quote: str) -> None:
        old = out.get(code)
        if old is None or (old["kind"] == "preferred" and kind == "required"):
            out[code] = {"kind": kind, "level": level, "quote": re.sub(r"^[\s\-*•·]+", "", quote).strip()[:160]}

    for m in _NAME_RX.finditer(f):
        code = _NAME_TO_CODE[m.group(1)]
        lo = max(0, m.start() - 70)
        hi = min(len(f), m.end() + 70)
        # stay within the sentence / bullet
        left = f[lo:m.start()]
        cut = max(left.rfind("."), left.rfind("\n"), left.rfind(";"))
        if cut >= 0:
            lo = lo + cut + 1
        right = f[m.end():hi]
        cuts = [i for i in (right.find("."), right.find("\n"), right.find(";")) if i >= 0]
        if cuts:
            hi = m.end() + min(cuts)
        window = f[lo:hi]
        # "French Polynesia", "German Shepherd" style mentions have no cue and are ignored
        if _PREF_CUES.search(window):
            put(code, "preferred", "B1" if _LOW_LEVEL.search(window) else "B2", window)
        elif _REQ_CUES.search(window):
            put(code, "required", "B1" if _LOW_LEVEL.search(window) else "B2", window)
    for m in _BILINGUAL.finditer(f):
        lo, hi = max(0, m.start() - 80), min(len(f), m.end() + 80)
        window = f[lo:hi]
        named = {_NAME_TO_CODE[x] for x in _NAME_RX.findall(window)}
        if not named and (country.upper() == "CA" or "french" in f or "francais" in f):
            named = {"en", "fr"}
        kind = "preferred" if _PREF_CUES.search(window) else "required"
        for code in named:
            put(code, kind, "B2", window)
    return out
