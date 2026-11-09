"""Evidence-based fit scoring.

``evaluate(p, cfg, job_id=...)`` scores a posting on eight dimensions, each 0..1 with a list of
``Evidence`` items whose ``basis`` says how the number was reached:

* ``text``      quoted from or found in the posting text;
* ``structure`` taken from a structured field (title, location, salary fields, dates, config);
* ``estimate``  inferred: a default, a heuristic, an exchange rate, a model suggestion.

A dimension backed only by estimates is capped at ``ESTIMATE_CAP`` (0.6), so guesses can never
look like strong evidence. Hard blockers (no sponsorship, a required language the candidate
does not hold at B2+, security clearance, employment type, avoided employer, closed posting)
force the ``excluded`` lane whatever the fit.

``extract_requirements(text)`` turns a description into required and preferred requirements
(headings, bullets, cue words, years of experience, degree levels) and is reused by the cover
letter and ATS helpers. ``report_markdown(ev, p)`` renders an evaluation for a human.
"""
from __future__ import annotations

import dataclasses as dc
import datetime as dt
import re
import unicodedata
from pathlib import Path

from .. import queue
from ..models import Dimension, Evaluation, Evidence, Posting
from . import comp, lang

DEFAULT_WEIGHTS = {"skills": .30, "track": .15, "seniority": .15, "location": .12, "language": .08,
                   "compensation": .08, "freshness": .06, "employer": .06}
ESTIMATE_CAP = 0.6
FLAG_PENALTY = 10
PENALISED_FLAGS = ("repost", "stale", "evergreen")
REQUIRED_W, PREFERRED_W = 1.0, 0.5
SENIORITY = ("intern", "junior", "mid", "senior", "lead", "principal", "director", "executive")

# ---------------------------------------------------------------- term normalisation

SYNONYMS = {
    "ml": "machine learning", "dl": "deep learning", "ai": "artificial intelligence",
    "nlp": "natural language processing", "cv": "computer vision", "js": "javascript",
    "ts": "typescript", "py": "python", "stats": "statistics", "statistical analysis": "statistics",
    "k8s": "kubernetes", "postgres": "postgresql", "psql": "postgresql", "golang": "go",
    "sklearn": "scikit learn", "scikit": "scikit learn", "tf": "tensorflow", "gcp": "google cloud",
    "google cloud platform": "google cloud", "amazon web services": "aws", "ms excel": "excel",
    "microsoft excel": "excel", "powerbi": "power bi", "ab testing": "a b testing",
    "a b test": "a b testing", "nodejs": "node js", "reactjs": "react", "react js": "react",
    "llms": "llm", "large language model": "llm", "large language models": "llm", "genai": "generative ai",
    "ci cd": "ci cd", "cicd": "ci cd", "bi": "business intelligence", "etl elt": "etl", "elt": "etl",
    "apprentissage automatique": "machine learning", "statistique": "statistics", "statistiques": "statistics",
    "aprendizaje automatico": "machine learning", "estadistica": "statistics", "estatistica": "statistics",
    "aprendizado de maquina": "machine learning", "time-series": "time series", "timeseries": "time series",
    "data viz": "data visualization", "dataviz": "data visualization", "visualisation": "visualization",
    "modelling": "modeling", "optimisation": "optimization",
}

VOCAB = [
    "python", "r", "sql", "java", "javascript", "typescript", "c++", "c#", "go", "rust", "scala", "julia",
    "matlab", "sas", "stata", "spss", "excel", "vba", "tableau", "power bi", "looker", "dbt", "airflow",
    "spark", "pyspark", "hadoop", "kafka", "snowflake", "bigquery", "redshift", "databricks", "aws", "azure",
    "google cloud", "docker", "kubernetes", "terraform", "linux", "git", "ci cd", "react", "node js",
    "django", "flask", "fastapi", "pandas", "numpy", "scikit learn", "tensorflow", "pytorch", "keras",
    "xgboost", "statistics", "machine learning", "deep learning", "natural language processing",
    "computer vision", "data visualization", "data analysis", "data engineering", "etl", "experimentation",
    "a b testing", "forecasting", "time series", "regression", "bayesian", "causal inference",
    "econometrics", "optimization", "simulation", "monte carlo", "survival analysis", "risk management",
    "credit risk", "market risk", "stan", "latex", "html", "css", "rest", "graphql", "postgresql", "mysql",
    "mongodb", "nosql", "stakeholder communication", "project management", "agile", "scrum", "dashboards",
    "product management", "llm", "generative ai", "mlops", "data science", "analytics",
    "business intelligence", "artificial intelligence", "data modeling", "data warehouse", "microservices",
    "probability", "hypothesis testing", "sampling", "survey methodology", "epidemiology", "biostatistics",
    "actuarial", "quantitative finance", "derivatives", "valuation", "accounting", "sales", "marketing",
    "seo", "figma", "ux", "communication",
]
# terms that are ordinary words in lowercase: matched case-sensitively in the original text
_CASED = {"r": re.compile(r"(?<![\w&/'’.-])R(?![\w&+#/'’-])"),
          "go": re.compile(r"(?<![\w.-])(?:Go(?![\w-])(?! to\b)|[Gg]olang\b)"),
          "rest": re.compile(r"\bREST(?:ful)?\b"),
          "stan": re.compile(r"(?<![\w-])Stan(?![\w-])"),
          "ux": re.compile(r"\bUX\b"),
          "sales": re.compile(r"\b[Ss]ales\b"),
          "communication": re.compile(r"\b[Cc]ommunication\b")}

_STOP = set("""a an the and or of to in on for with by from as at is are be been being will would should can
could may might must this that these those it its our your their we you they he she i me my us them who
whom which what when where why how all any both each few more most other some such no nor not only own
same so than too very just also into over under about across per via within without including include
includes etc using use used ability able strong excellent good great solid proven demonstrated working
knowledge understanding experience experienced skills skill years year plus minimum least required
preferred requirement requirements qualification qualifications ideally candidate candidates role team
work job position degree related field equivalent similar relevant new well highly hands track record
de la le les des et en du un une pour avec dans sur el los las y con para por del que""".split())


def fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


def _stem(tok: str) -> str:
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith(("ss", "us", "is", "ics")):
        return tok[:-1]
    return tok


_SYN_SORTED = sorted(SYNONYMS.items(), key=lambda kv: -len(kv[0]))


def norm(text: str) -> str:
    """Accent- and case-folded token string padded with spaces, synonyms applied, light stemming.
    Keeps ``+`` and ``#`` so C++ and C# survive. Both sides of every comparison go through this."""
    s = fold(text)
    s = re.sub(r"[^a-z0-9+#]+", " ", s)
    s = " " + re.sub(r"\s+", " ", s).strip() + " "
    for k, v in _SYN_SORTED:
        kk = " " + " ".join(re.sub(r"[^a-z0-9+#]+", " ", k).split()) + " "
        if kk in s:
            s = s.replace(kk, " " + v + " ")
    return " " + " ".join(_stem(t) for t in s.split()) + " "


def norm_term(term: str) -> str:
    return norm(term).strip()


def has_term(normed: str, term: str, original: str = "") -> bool:
    t = norm_term(term)
    if not t:
        return False
    if t in _CASED and original:
        return bool(_CASED[t].search(original))
    if t in _CASED:
        return False
    return f" {t} " in normed


_DISPLAY: dict[str, str] = {}


def display(term: str) -> str:
    """Readable spelling of a normalised term ('kubernete' -> 'kubernetes')."""
    return _DISPLAY.get(term, term)


def find_terms(text: str, vocab) -> list[str]:
    """Vocabulary terms present in ``text`` (normalised), longest-match wins over contained ones."""
    n = norm(text)
    hits = []
    for x in vocab:
        v = norm_term(x) if x else ""
        if v:
            _DISPLAY.setdefault(v, re.sub(r"\s+", " ", x.strip().lower()))
    for v in dict.fromkeys(norm_term(x) for x in vocab if x):
        if v and has_term(n, v, text):
            hits.append(v)
    return [h for h in hits if not any(h != o and f" {h} " in f" {o} " for o in hits)]


# ---------------------------------------------------------------- requirement extraction

@dc.dataclass
class Requirement:
    text: str
    kind: str = "required"                          # required | preferred
    terms: list[str] = dc.field(default_factory=list)
    years: float | None = None
    degree: int = 0                                 # 1 bachelor, 2 master, 3 doctorate
    any_of: bool = False                            # "Python or R": one term is enough
    source: str = "section"                         # section | cue | mention


_PREF_HEAD = ["nice to have", "nice-to-have", "preferred", "bonus", "desirable", "desired", "assets",
              "asset", "pluses", "good to have", "would be great", "would be a plus", "atouts", "atout",
              "souhaite", "un plus", "deseable", "valorable", "se valorara", "diferencial", "wunschenswert",
              "von vorteil", "gradito", "pluspunkte", "extra credit", "bonus points"]
_OTHER_HEAD = ["responsibilities", "what you ll do", "what you will do", "what you'll do", "the role",
               "about the role", "about us", "who we are", "benefits", "perks", "what we offer", "how to apply",
               "duties", "missions", "responsabilites", "vos missions", "tareas", "responsabilidades",
               "aufgaben", "we offer", "nous offrons", "about the team", "compensation", "salary", "your impact",
               "day to day", "in this role", "about the company", "our mission", "why join", "equal opportunity",
               "salaire", "salary range", "pay range", "pay", "remuneration", "salario", "salario bruto", "gehalt",
               "verguetung", "location", "lieu de travail", "lieu", "ubicacion", "localizacao", "start date",
               "date de debut", "contract type", "type de contrat", "employment type", "postuler", "apply",
               "avantages", "beneficios", "conditions", "what's in it for you", "our offer"]
_REQ_HEAD = ["requirements", "requirement", "qualifications", "qualification", "must have", "must-have",
             "what you bring", "what we re looking for", "what we're looking for", "what we are looking for",
             "who you are", "you have", "your profile", "about you", "skills", "competencies",
             "minimum qualifications", "basic qualifications", "required", "exigences", "profil",
             "profil recherche", "competences", "qualifications requises", "requisitos", "perfil",
             "requisitos minimos", "anforderungen", "dein profil", "ihr profil", "requisiti", "what you need",
             "you bring", "you will need", "you'll need", "experience", "education", "knowledge"]
_BULLET = re.compile(r"^\s*(?:[-*•·▪◦‣–—]|\d{1,2}[.)]|[a-z][.)])\s+")
_PREF_CUE = re.compile(r"\b(?:preferred|preferably|nice[- ]to[- ]have|(?:is|are|would be) (?:a )?(?:big |strong )?(?:plus|bonus|advantage)|"
                       r"a plus|an asset|(?:is|are) (?:an )?assets?|bonus|desirable|desired|ideally|"
                       r"atouts?|un plus|souhaitee?s?|appreciee?s?|deseable|valorable|se valorara|"
                       r"wunschenswert|von vorteil)\b", re.I)
_REQ_CUE = re.compile(r"\b(?:required|requires?|must(?: have| be)?|mandatory|essential|minimum of|at least|"
                      r"\d+\s*\+?\s*(?:years|yrs|ans|anos|años|jahre)|requis|requise|obligatoire|exige|exigee|"
                      r"indispensable|imprescindible|obligatorio|requerido|obrigatorio|erforderlich)\b", re.I)
_YEARS = re.compile(r"(?:(?:at least|minimum(?: of)?|min\.?|over|more than|au moins|minimo|pelo menos|mindestens)\s+)?"
                    r"(\d{1,2}(?:\.\d)?|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen)"
                    r"\s*(?:\+|plus)?\s*(?:(?:-|–|to|a|à)\s*\d{1,2}\s*)?\+?\s*"
                    r"(?:years?|yrs?|ans|annees|années|anos|años|jahre)\b", re.I)
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "twelve": 12, "fifteen": 15}
_DEGREE_ABBR = re.compile(r"(?<![\w.])(?:(B\.?\s?Sc|B\.?S\.|B\.?A\.|B\.?Eng|BSc|BEng|LL\.?B)|"
                          r"(M\.?\s?Sc|M\.?S\.|M\.?A\.|MBA|M\.?Eng|MSc|MEng|MPH|LL\.?M|MPhil)|"
                          r"(Ph\.?\s?D|DPhil|D\.?Phil))\.?(?![\w])")
_DEGREE_WORD = re.compile(r"\b(?:(bachelor\w*|undergraduate degree|licence|licenciatura|grado|bacharelado)|"
                          r"(master\w*|maitrise (?:en|es)|maestria|mestrado|graduate degree|postgraduate)|"
                          r"(phd|ph d|doctorate|doctoral degree|doctorat|doctorado|doutorado))\b")


def _clean_line(line: str) -> str:
    s = re.sub(r"^\s*#{1,6}\s*", "", line)
    s = re.sub(r"[*_`]+", "", s)
    return s.strip()


def _head_kind(line: str) -> str | None:
    """'required' | 'preferred' | 'other' when the line is a heading, else None."""
    if _BULLET.match(line):
        return None
    raw = line.strip()
    s = _clean_line(raw)
    head = s.split(":", 1)[0] if ":" in s else s
    f = re.sub(r"[^a-z' ]+", " ", fold(head)).strip()
    f = re.sub(r"\s+", " ", f)
    if not f or len(f) > 60:
        return None
    marked = raw.startswith("#") or raw.startswith("**") or ":" in s
    words = len(f.split())
    if not marked and (words > 6 or s.endswith(".")):
        return None
    for keys, kind in ((_PREF_HEAD, "preferred"), (_OTHER_HEAD, "other"), (_REQ_HEAD, "required")):
        for k in keys:
            kf = re.sub(r"[^a-z' ]+", " ", fold(k)).strip()
            if re.search(r"(?<![a-z])" + re.escape(kf) + r"(?![a-z])", f):
                slack = 3 if marked else 1                # "Experience with Python" is not a heading
                if words > len(kf.split()) + slack:
                    continue
                return kind
    return None


def years_in(text: str) -> float | None:
    found = []
    for m in _YEARS.finditer(text):
        v = m.group(1).lower()
        found.append(float(_WORDNUM.get(v, v)))
    return min(found) if found else None


def degree_level(text: str) -> int:
    lvl = 0
    for m in _DEGREE_ABBR.finditer(text or ""):
        lvl = max(lvl, 1 if m.group(1) else 2 if m.group(2) else 3)
    for m in _DEGREE_WORD.finditer(fold(text or "")):
        lvl = max(lvl, 1 if m.group(1) else 2 if m.group(2) else 3)
    return lvl


def _make_req(text: str, kind: str, vocab, source: str) -> Requirement:
    terms = find_terms(text, vocab)
    f = fold(text)
    any_of = bool(re.search(r"\b(?:or|ou|oder|either)\b", f)) or bool(re.search(r"\w\s?/\s?\w", text))
    return Requirement(text=text.strip(), kind=kind, terms=terms, years=years_in(text), degree=degree_level(text),
                       any_of=any_of, source=source)


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+(?=[A-Z0-9•\-])", text) if s.strip()]


def extract_requirements(text: str, vocab=None) -> list[Requirement]:
    """Required and preferred requirements, in posting order.

    Inside a requirements-like section every bullet or line is a requirement (kind from the
    section, overridden by a cue in the line). Outside one, only lines with a cue ("required",
    "is a plus", "3+ years") count. With no section and no cue, every vocabulary term mentioned
    becomes a one-term requirement (``source="mention"``).
    """
    vocab = list(vocab or []) + VOCAB
    out: list[Requirement] = []
    section: str | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        hk = _head_kind(line)
        if hk:
            section = hk
            rest = _clean_line(line).split(":", 1)[1].strip() if ":" in _clean_line(line) else ""
            if rest and hk in ("required", "preferred"):
                out.append(_make_req(rest, hk if not _PREF_CUE.search(rest) else "preferred", vocab, "section"))
            continue
        body = _BULLET.sub("", line).strip()
        if len(body) < 3:
            continue
        pieces = [body] if _BULLET.match(line) else _split_sentences(body)
        for piece in pieces:
            pref, req = bool(_PREF_CUE.search(piece)), bool(_REQ_CUE.search(piece))
            if section in ("required", "preferred"):
                kind = "preferred" if pref else ("required" if req else section)
                out.append(_make_req(piece, kind, vocab, "section"))
            elif pref or req:
                r = _make_req(piece, "preferred" if pref else "required", vocab, "cue")
                if r.terms or r.years is not None or r.degree or lang.required_languages(piece):
                    out.append(r)
    if not out:
        for t in find_terms(text or "", vocab):
            out.append(Requirement(text=t, kind="required", terms=[t], source="mention"))
    return out


# ---------------------------------------------------------------- helpers

def _now() -> dt.datetime:
    return queue.now()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    except OSError:
        return ""


def candidate_corpus(cfg, track=None) -> tuple[list[str], str]:
    """(evidenced skills from every track, text of the master CV and the track's CV variant)."""
    skills: list[str] = []
    for t in cfg.focus.tracks:
        skills += t.skills
    texts = [_read(cfg.path(cfg.candidate.master_cv))] if cfg.candidate.master_cv else []
    if track is not None and track.cv:
        texts.append(_read(cfg.path(track.cv)))
    if cfg.candidate.facts:
        texts.append(_read(cfg.path(cfg.candidate.facts)))
    return list(dict.fromkeys(skills)), "\n".join(x for x in texts if x)


_SEN_WORDS = [
    ("intern", r"\b(?:intern|internship|stagiaire|stage|trainee|co-?op|apprentice|praktikant\w*|becari[oa]|estagi\w+)\b"),
    ("executive", r"\b(?:chief|c[eotf]o|cxo|president|managing director)\b"),
    ("director", r"\b(?:director|directeur|directrice|director[a]?|head of|vp|vice president)\b"),
    ("principal", r"\b(?:principal|distinguished)\b"),
    ("lead", r"\b(?:lead|staff|team lead|tech lead|chef d'equipe)\b"),
    ("senior", r"\b(?:senior|sr\.?|snr|confirme|experimente|iii|iv)\b"),
    ("junior", r"\b(?:junior|jr\.?|entry[- ]level|graduate|new grad|debutant|i)\b"),
    ("mid", r"\b(?:mid|intermediate|ii)\b"),
]


def _seniority_local(title: str) -> tuple[str, bool]:
    f = fold(title)
    for level, rx in _SEN_WORDS:
        if re.search(rx, f):
            return level, True
    return "mid", False


def title_seniority(title: str) -> tuple[str, bool]:
    """(level, explicit). Uses ``filters.seniority_of`` when that module exists."""
    _, explicit = _seniority_local(title)
    try:
        from .. import filters                          # written separately; optional here
        lvl = filters.seniority_of(title)
        if lvl in SENIORITY:
            return lvl, explicit or lvl != "mid"
    except (ImportError, AttributeError):
        pass
    return _seniority_local(title)


def _track_local(title: str, focus):
    f = " " + fold(title) + " "
    best, blen = None, 0
    for t in focus.tracks:
        for kw in t.titles:
            k = fold(kw).strip()
            if k and re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", f) and len(k) > blen:
                best, blen = t, len(k)
    return best


def track_of(title: str, focus):
    try:
        from .. import filters
        return filters.track_of(title, focus)
    except (ImportError, AttributeError):
        return _track_local(title, focus)


def _region_local(location: str, remote, focus):
    loc = fold(location)
    loc_s = re.sub(r"[^a-z0-9]+", " ", loc)
    for r in focus.regions:
        for m in r.match:
            mf = fold(m)
            if mf and (mf in loc or re.sub(r"[^a-z0-9]+", " ", mf).strip() in loc_s):
                return r
    return None


def region_of(location: str, remote, focus):
    try:
        from .. import filters
        return filters.region_of(location, remote, focus)
    except (ImportError, AttributeError):
        return _region_local(location, remote, focus)


EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT",
      "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
_COUNTRY = [
    ("CA", r"\b(?:canada|canadian|montreal|toronto|vancouver|ottawa|calgary|edmonton|quebec|winnipeg|halifax|"
           r"ontario|british columbia|alberta|qc|on|bc|ab)\b"),
    ("US", r"\b(?:united states|usa|u\.s\.a?|us|new york|nyc|san francisco|seattle|boston|chicago|austin|"
           r"los angeles|washington,? dc|denver|atlanta|california|texas|massachusetts)\b"),
    ("UK", r"\b(?:united kingdom|uk|england|scotland|wales|london|manchester|edinburgh|bristol|cambridge,? uk)\b"),
    ("IE", r"\b(?:ireland|dublin|cork)\b"),
    ("PT", r"\b(?:portugal|lisbon|lisboa|porto)\b"),
    ("ES", r"\b(?:spain|espana|madrid|barcelona|valencia|sevilla)\b"),
    ("FR", r"\b(?:france|paris|lyon|marseille|toulouse)\b"),
    ("DE", r"\b(?:germany|deutschland|berlin|munich|munchen|hamburg|frankfurt|cologne)\b"),
    ("NL", r"\b(?:netherlands|nederland|amsterdam|rotterdam|the hague|utrecht)\b"),
    ("IT", r"\b(?:italy|italia|milan|milano|rome|roma|turin)\b"),
    ("BE", r"\b(?:belgium|belgique|brussels|bruxelles|antwerp)\b"),
    ("CH", r"\b(?:switzerland|suisse|schweiz|zurich|geneva|geneve|basel|lausanne|bern)\b"),
    ("SE", r"\b(?:sweden|stockholm|gothenburg)\b"), ("DK", r"\b(?:denmark|copenhagen)\b"),
    ("PL", r"\b(?:poland|warsaw|krakow)\b"), ("AT", r"\b(?:austria|vienna|wien)\b"),
    ("JP", r"\b(?:japan|tokyo|osaka|kyoto)\b"), ("HK", r"\b(?:hong kong)\b"),
    ("SG", r"\b(?:singapore)\b"), ("AU", r"\b(?:australia|sydney|melbourne|brisbane)\b"),
    ("BR", r"\b(?:brazil|brasil|sao paulo|rio de janeiro)\b"), ("MX", r"\b(?:mexico|cdmx)\b"),
    ("IN", r"\b(?:india|bangalore|bengaluru|mumbai|delhi|hyderabad)\b"),
]


def country_of(location: str) -> str:
    f = fold(location)
    for code, rx in _COUNTRY:
        if re.search(rx, f):
            return code
    return ""


def authorized(country: str, auth: list[str]) -> bool:
    a = {x.strip().upper().replace("GB", "UK") for x in auth or []}
    c = country.upper().replace("GB", "UK")
    if c in a:
        return True
    if c in EU and ("EU" in a or "EEA" in a):
        return True
    return False


_NO_SPONSOR = re.compile(
    r"\b(?:no (?:visa |work permit |immigration )?sponsorship|"
    r"(?:unable|not able|cannot|can ?not|can't|will not|won't|do not|don't|does not|doesn't|is not able|are not able)"
    r" (?:to )?(?:provide |offer |support )?(?:visa |immigration |work permit )?sponsor\w*|"
    r"sponsorship (?:is )?not (?:available|provided|offered)|without (?:the need for )?(?:visa )?sponsorship|"
    r"must (?:be (?:legally )?(?:authori[sz]ed|eligible|entitled)|have (?:the )?(?:legal )?right) to work|"
    r"(?:citizens?|citizenship) (?:only|required)|must be an? (?:u\.?s\.?|us|canadian|british|eu) citizen|"
    r"(?:permanent residents?|citizens) (?:or permanent residents? )?only|"
    r"aucun parrainage|sans parrainage|(?:doit|devez) (?:etre|être) autorise\w* a travailler|"
    r"citoyens? canadien\w* ou residents? permanent\w*|"
    r"sin patrocinio|no (?:se )?(?:ofrece|ofrecemos|proporciona) patrocinio|sem patrocinio|"
    r"nao (?:oferecemos|oferece) patrocinio)", re.I)
_CLEARANCE_REQ = re.compile(
    r"\b(?:(?:active|current|valid)?\s*(?:secret|top secret|ts/sci|ts|security|government|dv|sc|nv1|nv2|baseline)"
    r" (?:security )?clearance (?:is )?(?:required|needed|mandatory|essential)|"
    r"(?:must|required to|need to) (?:hold|have|possess|maintain) (?:an? )?(?:active |current |valid )?"
    r"(?:secret |top secret |ts/sci |security |government |dv |sc )?clearance|"
    r"active (?:secret |top secret |ts/sci |security )?clearance|ts/sci|"
    r"habilitation (?:de )?(?:securite|défense|defense) (?:requise|obligatoire)|"
    r"cote de (?:fiabilite|securite) (?:requise|obligatoire|secret))", re.I)
_CLEARANCE_ANY = re.compile(r"\bclearance\b|\bhabilitation de securite\b|\bcote de (?:fiabilite|securite)\b", re.I)

_EMPLOYMENT = {"full_time": "full_time", "fulltime": "full_time", "full time": "full_time", "permanent": "full_time",
               "part_time": "part_time", "parttime": "part_time", "part time": "part_time",
               "contract": "contract", "contractor": "contract", "freelance": "contract", "temporary": "temporary",
               "temp": "temporary", "internship": "internship", "intern": "internship", "volunteer": "volunteer"}


def employment_of(p: Posting) -> tuple[str, str]:
    """(type, basis) from the structured field, else from the title."""
    if p.employment:
        k = re.sub(r"[-_]+", " ", fold(p.employment)).strip()
        return _EMPLOYMENT.get(k, _EMPLOYMENT.get(k.replace(" ", "_"), k.replace(" ", "_"))), "structure"
    t = fold(p.title)
    if re.search(r"\b(?:intern|internship|stagiaire|stage|co-?op|praktikum)\b", t):
        return "internship", "structure"
    if re.search(r"\b(?:contract|contractor|freelance|consultant \(contract\))\b", t):
        return "contract", "structure"
    if re.search(r"\b(?:part[- ]time|temps partiel)\b", t):
        return "part_time", "structure"
    if re.search(r"\b(?:temporary|temp|fixed[- ]term|cdd)\b", t):
        return "temporary", "structure"
    return "", ""


def _employer_match(name: str, lst) -> bool:
    e = " " + queue.fold(name) + " "
    return any((" " + queue.fold(x) + " ") in e for x in lst if x and queue.fold(x))


def _cap(d: Dimension) -> Dimension:
    if not d.evidence or all(e.basis == "estimate" for e in d.evidence):
        d.score = min(d.score, ESTIMATE_CAP)
    d.score = round(max(0.0, min(1.0, d.score)), 3)
    return d


# ---------------------------------------------------------------- dimensions

def _skills(p: Posting, reqs: list[Requirement], skills: list[str], cv_text: str) -> Dimension:
    skill_terms = {norm_term(s) for s in skills if norm_term(s)}
    cv_n = norm(cv_text) if cv_text else ""
    cv_tokens = set(cv_n.split()) | {t for s in skill_terms for t in s.split()}
    cand_degree = degree_level(cv_text)
    ev: list[Evidence] = []
    tot = got = 0.0
    counts = {"required": [0, 0.0], "preferred": [0, 0.0]}
    missing: list[str] = []
    for r in reqs:
        if r.terms:
            covered = [t for t in r.terms if t in skill_terms or (cv_n and has_term(cv_n, t, cv_text))]
            cov = (1.0 if covered else 0.0) if r.any_of else len(covered) / len(r.terms)
            basis = "text"
            if covered:
                src = ", ".join(f"{display(t)} ({'track skills' if t in skill_terms else 'CV'})" for t in covered)
                note = f"{r.kind} '{_short(r.text)}' covered by {src}"
            else:
                note = f"{r.kind} '{_short(r.text)}' not evidenced ({', '.join(display(t) for t in r.terms)})"
            if not covered or not r.any_of:
                missing += [display(t) for t in r.terms if t not in covered]
            if r.degree and cv_text:
                met = cand_degree >= r.degree
                cov = (cov + (1.0 if met else 0.0)) / 2
                note += "; degree level met by the CV" if met else "; degree level above the CV's highest degree"
        elif r.degree and not lang.required_languages(r.text):
            if not cv_text:
                cov, basis, note = 0.5, "estimate", f"{r.kind} degree '{_short(r.text)}': no CV to check"
            elif cand_degree >= r.degree:
                cov, basis, note = 1.0, "text", f"{r.kind} degree '{_short(r.text)}' met by the CV"
            else:
                eq = bool(re.search(r"equivalent|or (?:related )?experience", r.text, re.I))
                cov, basis = (0.5 if eq else 0.0), "text"
                note = f"{r.kind} degree '{_short(r.text)}' above the CV's highest degree"
        else:
            if r.years is not None and len(_content_words(r.text)) <= 3:
                continue                              # pure years line: scored under seniority
            if lang.required_languages(r.text):
                continue                              # language demand: scored under language
            words = _content_words(r.text)
            if not words:
                continue
            if not cv_tokens:
                cov, basis, note = 0.5, "estimate", f"{r.kind} '{_short(r.text)}': nothing to compare with"
            else:
                hit = [w for w in words if w in cv_tokens]
                cov = len(hit) / len(words)
                basis = "estimate"
                note = f"{r.kind} '{_short(r.text)}': {len(hit)}/{len(words)} key words appear in the CV"
        w = REQUIRED_W if r.kind == "required" else PREFERRED_W
        if r.source == "mention":
            w *= 0.75
        tot += w
        got += w * cov
        counts[r.kind][0] += 1
        counts[r.kind][1] += cov
        ev.append(Evidence(note, basis))
    if tot == 0:
        return _cap(Dimension("skills", 0.5, DEFAULT_WEIGHTS["skills"],
                              [Evidence("no requirements could be extracted from the posting", "estimate")]))
    score = got / tot
    head = (f"covers {counts['required'][1]:.1f} of {counts['required'][0]} required and "
            f"{counts['preferred'][1]:.1f} of {counts['preferred'][0]} preferred requirements")
    basis = "text" if any(e.basis == "text" for e in ev) else "estimate"
    ev = [Evidence(head, basis)] + ev[:14]
    if missing:
        ev.append(Evidence("not evidenced: " + ", ".join(dict.fromkeys(missing)), "text"))
    return _cap(Dimension("skills", score, DEFAULT_WEIGHTS["skills"], ev))


def _content_words(text: str) -> list[str]:
    toks = [t for t in norm(text).split() if len(t) >= 4 and t not in _STOP and not t.isdigit()]
    return list(dict.fromkeys(toks))


def _short(s: str, n: int = 70) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _track(p: Posting, cfg) -> tuple[Dimension, object]:
    w = DEFAULT_WEIGHTS["track"]
    if not cfg.focus.tracks:
        return _cap(Dimension("track", 0.5, w, [Evidence("no tracks configured", "estimate")])), None
    t = track_of(p.title, cfg.focus)
    if t is not None:
        return _cap(Dimension("track", 1.0, w, [Evidence(f"title '{p.title}' is on track {t.label}", "structure")])), t
    n = norm(p.text)
    for tr in cfg.focus.tracks:
        for kw in tr.titles:
            if kw and f" {norm_term(kw)} " in n:
                return _cap(Dimension("track", 0.5, w, [Evidence(
                    f"title is off-track but the text mentions '{kw}' ({tr.label})", "text")])), tr
    return _cap(Dimension("track", 0.15, w, [Evidence(f"title '{p.title}' matches no track", "structure")])), None


def _years_level(years: float) -> str:
    if years < 2:
        return "junior"
    if years < 5:
        return "mid"
    if years < 8:
        return "senior"
    if years < 12:
        return "lead"
    return "principal"


def _range_score(level: str, lo: str, hi: str, near: float, far: float) -> tuple[float, int]:
    i, a, b = SENIORITY.index(level), SENIORITY.index(lo), SENIORITY.index(hi)
    dist = 0 if a <= i <= b else (a - i if i < a else i - b)
    return (1.0 if dist == 0 else near if dist == 1 else far), dist


def _reach(p: Posting, cfg, reqs: list[Requirement]) -> str:
    """Judge the title against the candidate, not just the target range: one level above their own
    level (or up to two years over their experience) is a stretch worth flagging; two levels above
    (or three or more years over) is out of reach on the stated minimums."""
    c = cfg.candidate
    if c.level:
        level, explicit = title_seniority(p.title)
        if explicit and level in SENIORITY:
            gap = SENIORITY.index(level) - SENIORITY.index(c.level)
            if gap >= 2:
                return f"out_of_reach:{level}"
            if gap == 1:
                return f"stretch:{level}"
    if c.years_experience is not None:
        yrs = [r.years for r in reqs if r.years is not None and r.kind == "required"]
        if yrs:
            over = max(yrs) - float(c.years_experience)
            if over >= 3:
                return f"out_of_reach:{max(yrs):g}y"
            if over > 0:
                return f"stretch:{max(yrs):g}y"
    return ""


def _seniority(p: Posting, cfg, reqs: list[Requirement]) -> Dimension:
    w = DEFAULT_WEIGHTS["seniority"]
    lo, hi = cfg.focus.seniority_min, cfg.focus.seniority_max
    level, explicit = title_seniority(p.title)
    s1, dist = _range_score(level, lo, hi, 0.5, 0.1)
    ev = [Evidence(f"title level {level} vs target {lo}–{hi}" + ("" if dist == 0 else f" ({dist} step(s) away)"),
                   "structure" if explicit else "estimate")]
    yrs = [r.years for r in reqs if r.years is not None and r.kind == "required"] or \
          [r.years for r in reqs if r.years is not None]
    if yrs:
        y = max(yrs)
        lvl = _years_level(y)
        s2, d2 = _range_score(lvl, lo, hi, 0.6, 0.2)
        ev.append(Evidence(f"asks for {y:g}+ years (≈ {lvl})" + ("" if d2 == 0 else f", {d2} step(s) from target"), "text"))
        score = (s1 + s2) / 2 if explicit else s2 * 0.8 + s1 * 0.2
    else:
        score = s1
    return _cap(Dimension("seniority", score, w, ev))


_REMOTE_RX = re.compile(r"\b(?:fully remote|remote[- ]first|100% remote|remote|work from home|teletravail|"
                        r"télétravail|remoto|teletrabajo|home ?office)\b", re.I)
_HYBRID_RX = re.compile(r"\b(?:hybrid|hybride|hibrido|híbrido)\b", re.I)


def _location(p: Posting, cfg) -> Dimension:
    w = DEFAULT_WEIGHTS["location"]
    focus = cfg.focus
    ev: list[Evidence] = []
    remote, rbasis = p.remote, "structure"
    if remote is None:
        if _REMOTE_RX.search(p.location or "") or _REMOTE_RX.search(p.title or ""):
            remote, rbasis = True, "structure"
        elif _REMOTE_RX.search((p.text or "")[:3000]) and not _HYBRID_RX.search((p.text or "")[:3000]):
            remote, rbasis = True, "text"
    if _HYBRID_RX.search(p.location or "") or _HYBRID_RX.search((p.text or "")[:3000]):
        ev.append(Evidence("hybrid arrangement mentioned", "text"))
    if focus.remote == "only" and remote is not True:
        ev.append(Evidence("on-site or hybrid, but focus.remote is only", "structure"))
        return _cap(Dimension("location", 0.1, w, ev))
    if focus.remote == "exclude" and remote is True:
        ev.append(Evidence("remote role, but focus.remote is exclude", rbasis))
        return _cap(Dimension("location", 0.1, w, ev))
    if not focus.regions:
        ev.append(Evidence("no regions configured", "estimate"))
        return _cap(Dimension("location", 0.7, w, ev))
    region = region_of(p.location or "", remote, focus)
    if region is not None:
        score = region.weight
        if remote and not region.remote_ok:
            score *= 0.5
        if _region_local(p.location or "", None, focus) is None:
            ev.append(Evidence(f"remote role counted for region {region.name} (weight {region.weight:g}); "
                               f"location '{p.location}' does not name it", "estimate"))
        else:
            ev.append(Evidence(f"'{p.location}' is in region {region.name} (weight {region.weight:g})"
                               + (", remote" if remote else ""), "structure"))
        return _cap(Dimension("location", score, w, ev))
    if remote:
        if p.location:
            ev.append(Evidence(f"remote, tied to '{p.location}', outside your regions", rbasis))
            return _cap(Dimension("location", 0.3, w, ev))
        ev.append(Evidence("remote, region not stated", "estimate"))
        return _cap(Dimension("location", 0.5, w, ev))
    if not p.location:
        ev.append(Evidence("no location given", "estimate"))
        return _cap(Dimension("location", 0.4, w, ev))
    ev.append(Evidence(f"'{p.location}' is outside your regions", "structure"))
    return _cap(Dimension("location", 0.0, w, ev))


def _language(p: Posting, cfg, country: str) -> tuple[Dimension, list[str]]:
    w = DEFAULT_WEIGHTS["language"]
    held = {k.lower(): lang.level_rank(v) for k, v in (cfg.candidate.languages or {}).items()}
    ok = {x.lower() for x in cfg.focus.languages_ok or []}
    ev: list[Evidence] = []
    blockers: list[str] = []
    code, basis = (p.lang.lower(), "structure") if p.lang else (lang.detect(p.text), "text")
    if code:
        if code in ok or held.get(code, 0) >= lang.LEVELS["b2"]:
            score = 1.0
            ev.append(Evidence(f"posting is in {code}, a language you work in", basis))
        else:
            score = 0.3
            ev.append(Evidence(f"posting is in {code}, not one of your working languages", basis))
    else:
        score = 0.6
        ev.append(Evidence("posting language not detected", "estimate"))
    for c, info in lang.required_languages(p.text, country=country).items():
        need = lang.LEVELS["b1"] if info["level"] == "B1" else lang.LEVELS["b2"]
        have = held.get(c, 0)
        if info["kind"] == "required":
            if have >= need:
                ev.append(Evidence(f"{c} required ('{_short(info['quote'], 60)}'); you hold it", "text"))
            else:
                ev.append(Evidence(f"{c} required ('{_short(info['quote'], 60)}'); not held at {info['level']}+", "text"))
                blockers.append(f"language:{c}")
                score = 0.0
        else:
            if have >= need:
                ev.append(Evidence(f"{c} preferred; you hold it", "text"))
                score = min(1.0, score + 0.1)
            else:
                ev.append(Evidence(f"{c} preferred; not held at {info['level']}+", "text"))
                score *= 0.7
    return _cap(Dimension("language", score, w, ev)), blockers


def _compensation(p: Posting, cfg, country: str) -> Dimension:
    w = DEFAULT_WEIGHTS["compensation"]
    floor, fcur = float(cfg.focus.salary_floor or 0), (cfg.focus.salary_currency or "").upper()
    ev: list[Evidence] = []
    if p.salary_min or p.salary_max:
        lo, hi, cur = p.salary_min, p.salary_max, (p.salary_currency or "").upper()
        top = hi or lo or 0
        period = comp.guess_period(top) if top < 20000 else "year"
        lo, hi = comp.annualise(lo, period), comp.annualise(hi, period)
        basis = "structure"
        ev.append(Evidence(f"salary field {_money(lo, hi, cur)}" + ("" if period == "year" else f" (from {period} rate)"),
                           basis))
    else:
        dollar = {"CA": "CAD", "AU": "AUD", "SG": "SGD", "HK": "HKD", "NZ": "NZD"}.get(country, "USD")
        lo, hi, cur, period = comp.parse_salary(p.text, default_dollar=dollar)
        if lo is None:
            return _cap(Dimension("compensation", 0.5, w, [Evidence("no salary stated", "estimate")]))
        ev.append(Evidence(f"text states {_money(lo, hi, cur)}" + ("" if period == "year" else f" (quoted per {period})"),
                           "text"))
    lo = lo or hi
    hi = hi or lo
    if floor <= 0:
        ev.append(Evidence("no salary floor set", "structure"))
        return _cap(Dimension("compensation", 0.8, w, ev))
    if fcur and cur and cur != fcur:
        clo, chi = comp.convert(lo, cur, fcur), comp.convert(hi, cur, fcur)
        if clo is None:
            ev.append(Evidence(f"cannot compare {cur} with your {fcur} floor", "estimate"))
            return _cap(Dimension("compensation", 0.5, w, ev))
        lo, hi = clo, chi
        ev.append(Evidence(f"converted to {fcur} at approximate rates: {_money(lo, hi, fcur)}", "estimate"))
    if lo >= floor:
        score = 1.0
        ev.append(Evidence(f"minimum meets your floor of {floor:,.0f}", "structure"))
    elif hi >= floor:
        score = 0.5 + 0.5 * (hi - floor) / max(hi - lo, 1)
        ev.append(Evidence(f"range straddles your floor of {floor:,.0f}", "structure"))
    else:
        score = max(0.0, 0.4 * hi / floor)
        ev.append(Evidence(f"maximum is below your floor of {floor:,.0f}", "structure"))
    return _cap(Dimension("compensation", score, w, ev))


def _money(lo, hi, cur) -> str:
    if lo is None:
        return "unknown"
    s = f"{lo:,.0f}" if not hi or hi == lo else f"{lo:,.0f}–{hi:,.0f}"
    return f"{s} {cur}/year".strip()


def _freshness(p: Posting) -> Dimension:
    w = DEFAULT_WEIGHTS["freshness"]
    if not p.posted:
        return _cap(Dimension("freshness", 0.5, w, [Evidence("posting date unknown", "estimate")]))
    try:
        d = dt.date.fromisoformat(p.posted[:10])
    except ValueError:
        return _cap(Dimension("freshness", 0.5, w, [Evidence(f"unreadable posting date {p.posted!r}", "estimate")]))
    age = (_now().date() - d).days
    score = 1.0 if age <= 7 else 0.85 if age <= 14 else 0.65 if age <= 30 else 0.4 if age <= 60 else 0.2
    ev = [Evidence(f"posted {max(age, 0)} day(s) ago ({p.posted[:10]})", "structure")]
    if p.deadline:
        try:
            left = (dt.date.fromisoformat(p.deadline[:10]) - _now().date()).days
            if left < 0:
                score = 0.0
                ev.append(Evidence(f"deadline {p.deadline[:10]} has passed", "structure"))
            else:
                ev.append(Evidence(f"deadline in {left} day(s)", "structure"))
        except ValueError:
            pass
    return _cap(Dimension("freshness", score, w, ev))


def _employer(p: Posting, cfg) -> tuple[Dimension, bool, bool]:
    w = DEFAULT_WEIGHTS["employer"]
    if _employer_match(p.employer, cfg.focus.avoid_employers):
        return _cap(Dimension("employer", 0.0, w, [Evidence(f"{p.employer} is on your avoid list", "structure")])), False, True
    if _employer_match(p.employer, cfg.focus.flagship_employers):
        return _cap(Dimension("employer", 1.0, w, [Evidence(f"{p.employer} is a flagship employer", "structure")])), True, False
    return _cap(Dimension("employer", 0.5, w, [Evidence(f"{p.employer} has no preference set", "estimate")])), False, False


# ---------------------------------------------------------------- assembly

def _weights(cfg) -> dict[str, float]:
    raw = getattr(cfg.focus, "weights", None) or getattr(cfg, "weights", None) or DEFAULT_WEIGHTS
    w = {k: float(raw.get(k, DEFAULT_WEIGHTS[k])) for k in DEFAULT_WEIGHTS}
    s = sum(w.values()) or 1.0
    return {k: v / s for k, v in w.items()}


def _finish(ev: Evaluation, cfg, flagship: bool) -> Evaluation:
    raw = sum(d.score * d.weight for d in ev.dimensions)
    penalty = FLAG_PENALTY * sum(1 for f in ev.flags if f.split(":")[0] in PENALISED_FLAGS)
    ev.fit = max(0, int(round(100 * raw)) - penalty)
    ev.stars = round(1 + 4 * ev.fit / 100, 1)
    if ev.blockers:
        ev.lane = "excluded"
    else:
        queue.configure(cfg)
        ev.lane = queue.lane(ev.fit, flagship)
    ev.summary = _summary(ev, cfg)
    return ev


_BLOCKER_WORDS = {"no_sponsorship": "the posting rules out visa sponsorship and you are not authorised there",
                  "clearance": "a security clearance is required", "avoid_employer": "the employer is on your avoid list",
                  "closed": "the posting is closed"}


def _blocker_words(b: str) -> str:
    if b in _BLOCKER_WORDS:
        return _BLOCKER_WORDS[b]
    if b.startswith("language:"):
        return f"it requires {b.split(':', 1)[1]} at a level you do not hold"
    if b.startswith("employment:"):
        return f"it is a {b.split(':', 1)[1].replace('_', ' ')} role outside your employment types"
    if b.startswith("out_of_reach:"):
        what = b.split(":", 1)[1]
        return (f"it asks for {what[:-1]} years, well beyond yours" if what.endswith("y")
                else f"it is a {what} title, two or more levels above yours")
    if b.startswith("market:"):
        return f"a market rule excludes it ({b.split(':', 1)[1].replace('_', ' ')})"
    return b


def _summary(ev: Evaluation, cfg) -> str:
    if ev.blockers:
        return (f"Excluded because {'; '.join(_blocker_words(b) for b in ev.blockers)} "
                f"(fit would be {ev.fit}/100).")
    label = next((t.label for t in cfg.focus.tracks if t.key == ev.track), "") or "no matching track"
    ranked = sorted(ev.dimensions, key=lambda d: d.score, reverse=True)
    strong = [d.key for d in ranked if d.score >= 0.75][:2]
    weak = [d.key for d in sorted(ev.dimensions, key=lambda d: d.score) if d.score < 0.5][:2]
    s = f"Fit {ev.fit}/100 ({ev.stars} stars, {ev.lane} lane) for {label}"
    if strong:
        s += f", strongest on {' and '.join(strong)}"
    if weak:
        s += f"{',' if strong else ','} weakest on {' and '.join(weak)}"
    if ev.flags:
        s += f", with {len(ev.flags)} warning(s)"
    return s + "."


def evaluate(p: Posting, cfg, *, job_id: str, history=()) -> Evaluation:
    """Score one posting against the configuration. Deterministic: same input, same result."""
    weights = _weights(cfg)
    track_dim, track = _track(p, cfg)
    skills, cv_text = candidate_corpus(cfg, track)
    reqs = extract_requirements(p.text, vocab=skills)
    country = country_of(p.location or "")
    lang_dim, lang_blockers = _language(p, cfg, country)
    emp_dim, flagship, avoid = _employer(p, cfg)
    dims = [_skills(p, reqs, skills, cv_text), track_dim, _seniority(p, cfg, reqs), _location(p, cfg), lang_dim,
            _compensation(p, cfg, country), _freshness(p), emp_dim]
    for d in dims:
        d.weight = round(weights[d.key], 4)

    blockers: list[str] = list(lang_blockers)
    flags: list[str] = []
    text = p.text or ""
    m = _NO_SPONSOR.search(text)
    if m:
        cand = cfg.candidate
        if cand.needs_sponsorship:
            blockers.append("no_sponsorship")
        elif not country:
            flags.append("sponsorship_unclear")
        elif not authorized(country, cand.work_authorization):
            blockers.append("no_sponsorship")
    if _CLEARANCE_REQ.search(text):
        blockers.append("clearance")
    elif _CLEARANCE_ANY.search(text):
        flags.append("clearance_mentioned")
    emp, _ = employment_of(p)
    allowed = {e.replace("-", "_") for e in cfg.focus.employment or []}
    if emp and allowed and emp not in allowed:
        blockers.append(f"employment:{emp}")
    if avoid:
        blockers.append("avoid_employer")
    reach = _reach(p, cfg, reqs)
    if reach:
        (blockers if reach.startswith("out_of_reach") else flags).append(reach)
    market_hits = []
    if cfg.focus.markets:
        from .. import markets
        market_hits = markets.check(markets.load(cfg.focus.markets, cfg.workspace), p, cfg.candidate.status)
        for h in market_hits:
            if h["verdict"] == "fail":
                blockers.append(f"market:{h['rule']}")
            elif h["verdict"] == "flag":
                flags.append(f"market:{h['rule']}")

    try:
        from . import legitimacy                         # written separately; optional here
    except ImportError:
        legitimacy = None
    if legitimacy is not None:
        for f in legitimacy.check(p, list(history or ()), None) or []:
            if f not in flags:
                flags.append(f)
            if f == "closed" and "closed" not in blockers:
                blockers.append("closed")

    ev = Evaluation(job_id=job_id, fit=0, stars=1.0, track=track.key if track is not None else "",
                    dimensions=dims, blockers=list(dict.fromkeys(blockers)), flags=flags, market=market_hits)
    return _finish(ev, cfg, flagship)


def apply_semantic(ev: Evaluation, result: dict, cfg, *, employer: str = "") -> Evaluation:
    """Fold an ``llm.semantic_skill_match`` result into an evaluation: the skills score can only
    rise, by at most ``llm.MAX_BOOST``, and the model's reasons are kept as estimate evidence."""
    from .llm import MAX_BOOST
    boost = max(0.0, min(float(result.get("boost") or 0.0), MAX_BOOST))
    if boost <= 0:
        return ev
    for d in ev.dimensions:
        if d.key == "skills":
            d.score = round(min(1.0, d.score + boost), 3)
            d.evidence.extend(result.get("evidence") or [Evidence(f"model-suggested matches (+{boost:.2f})", "estimate")])
    flagship = _employer_match(employer, cfg.focus.flagship_employers) if employer else False
    return _finish(ev, cfg, flagship)


def report_markdown(ev: Evaluation, p: Posting) -> str:
    """A readable evaluation report: dimension table, evidence with basis tags, blockers, flags."""
    lines = [f"# {p.title} — {p.employer}", ""]
    meta = [x for x in (p.location, "remote" if p.remote else "", p.posted and f"posted {p.posted[:10]}",
                        p.url) if x]
    if meta:
        lines += [" · ".join(meta), ""]
    lines += [f"**Fit {ev.fit}/100** · {ev.stars} / 5 stars · lane **{ev.lane or 'unscored'}**"
              + (f" · track `{ev.track}`" if ev.track else ""), "", ev.summary, ""]
    lines += ["| Dimension | Score | Weight | Points | Basis |", "|---|---:|---:|---:|---|"]
    for d in ev.dimensions:
        bases = sorted({e.basis for e in d.evidence}) or ["estimate"]
        capped = " (capped)" if bases == ["estimate"] and d.score >= ESTIMATE_CAP else ""
        lines.append(f"| {d.key} | {d.score:.2f}{capped} | {d.weight:.2f} | {100 * d.score * d.weight:.1f} | "
                     f"{', '.join(bases)} |")
    lines += ["", "## Evidence", ""]
    for d in ev.dimensions:
        lines.append(f"**{d.key}**")
        for e in d.evidence:
            lines.append(f"- [{e.basis}] {e.note}")
        lines.append("")
    lines += ["## Blockers", ""]
    lines += [f"- `{b}`: {_blocker_words(b)}" for b in ev.blockers] or ["- none"]
    lines += ["", "## Flags", ""]
    lines += [f"- `{f}`" + (f" (−{FLAG_PENALTY} fit)" if f.split(':')[0] in PENALISED_FLAGS else "")
              for f in ev.flags] or ["- none"]
    if ev.market:
        lines += ["", "## Market rules", ""]
        for h in ev.market:
            lines.append(f"- **{h['verdict'].upper()}** `{h['pack']}/{h['rule']}`: {h['note']}"
                         + (f"\n  > {h['quote']}" if h.get("quote") else ""))
    return "\n".join(lines) + "\n"
