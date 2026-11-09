"""CV and cover-letter content as plain files a person (or an agent) edits.

A CV is a YAML file per track, optionally per language (``cv/ds.yml``, ``cv/ds.fr.yml``)::

    lang: en
    header:                       # optional; defaults come from `candidate` in jobveyra.yml
      name: Alex Rivera
      city: Lisbon, Portugal
      phone: +351 555 0100
      email: alex.rivera@example.com
      links: [linkedin.com/in/example, github.com/example]
    order: [experience, education, projects, publications, skills, awards]
    headings: {skills: Technical skills}         # optional overrides of the section titles
    experience:
      - org: Example Labs
        title: Data Scientist
        city: Lisbon
        start: Jan 2023
        end: Present
        bullets:
          - Built a demand forecast for 1,200 stores that cut stock-outs by 18%.
    education:
      - {org: University of Lisbon, title: "M.Sc. Statistics", city: Lisbon, start: Sep 2020, end: Jul 2022}
    projects: []                  # same shape as experience
    publications: ["Rivera, A. (2022). Title. *Journal*, 1(2), 3-4."]
    skills:
      - {label: Methods, items: "forecasting, causal inference, A/B testing"}
    awards: ["Best thesis award, University of Lisbon (2022)"]
    custom:                       # any other section: a title and plain lines
      - {title: Certifications, lines: ["..."]}

Text may use ``**bold**`` and ``*italic*``; everything else is escaped for LaTeX.

A cover letter is Markdown with a small front matter block::

    ---
    lang: en
    date: 2026-11-09              # optional, defaults to today
    recipient: [Hiring Team, Example Labs, Lisbon]
    re: Data Scientist (REQ-123)
    salutation: Dear Hiring Manager,   # optional, a default per language
    closing: Sincerely,               # optional, a default per language
    ---
    First paragraph.

    Second paragraph.

HTML comments (``<!-- ... -->``) are notes for the writer and never reach the PDF.
"""
from __future__ import annotations

import dataclasses as dc
import datetime as dt
import re
from pathlib import Path
from typing import Any

SECTIONS = ("experience", "education", "projects", "publications", "skills", "awards")
ENTRY_SECTIONS = ("experience", "education", "projects")
DEFAULT_ORDER = ["experience", "education", "projects", "publications", "skills", "awards"]

HEADINGS = {
    "en": {"experience": "Experience", "education": "Education", "projects": "Projects",
           "publications": "Publications", "skills": "Skills", "awards": "Awards"},
    "fr": {"experience": "Expérience", "education": "Formation", "projects": "Projets",
           "publications": "Publications", "skills": "Compétences", "awards": "Distinctions"},
    "es": {"experience": "Experiencia", "education": "Formación", "projects": "Proyectos",
           "publications": "Publicaciones", "skills": "Competencias", "awards": "Premios"},
    "pt": {"experience": "Experiência", "education": "Formação", "projects": "Projetos",
           "publications": "Publicações", "skills": "Competências", "awards": "Prêmios"},
    "de": {"experience": "Berufserfahrung", "education": "Ausbildung", "projects": "Projekte",
           "publications": "Publikationen", "skills": "Kenntnisse", "awards": "Auszeichnungen"},
    "it": {"experience": "Esperienza", "education": "Formazione", "projects": "Progetti",
           "publications": "Pubblicazioni", "skills": "Competenze", "awards": "Riconoscimenti"},
}
SALUTATION = {"en": "Dear Hiring Manager,", "fr": "Madame, Monsieur,", "es": "Estimado equipo de selección:",
              "pt": "Prezada equipe de recrutamento,", "de": "Sehr geehrte Damen und Herren,",
              "it": "Gentile responsabile della selezione,"}
CLOSING = {"en": "Sincerely,", "fr": "Cordialement,", "es": "Atentamente,", "pt": "Atenciosamente,",
           "de": "Mit freundlichen Grüßen", "it": "Cordiali saluti,"}
MONTHS = {
    "en": "January February March April May June July August September October November December",
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
    "pt": "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro",
    "de": "Januar Februar März April Mai Juni Juli August September Oktober November Dezember",
    "it": "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre",
}
LANGS = tuple(HEADINGS)


class ContentError(ValueError):
    pass


@dc.dataclass
class Header:
    name: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""
    links: list[str] = dc.field(default_factory=list)


@dc.dataclass
class Entry:
    org: str
    title: str = ""
    city: str = ""
    start: str = ""
    end: str = ""
    bullets: list[str] = dc.field(default_factory=list)


@dc.dataclass
class CV:
    lang: str = "en"
    header: Header = dc.field(default_factory=Header)
    order: list[str] = dc.field(default_factory=lambda: list(DEFAULT_ORDER))
    headings: dict[str, str] = dc.field(default_factory=dict)
    experience: list[Entry] = dc.field(default_factory=list)
    education: list[Entry] = dc.field(default_factory=list)
    projects: list[Entry] = dc.field(default_factory=list)
    publications: list[str] = dc.field(default_factory=list)
    skills: list[tuple[str, str]] = dc.field(default_factory=list)
    awards: list[str] = dc.field(default_factory=list)
    custom: list[tuple[str, list[str]]] = dc.field(default_factory=list)

    def heading(self, key: str) -> str:
        return self.headings.get(key) or HEADINGS.get(self.lang, HEADINGS["en"]).get(key, key.title())

    def text(self) -> str:
        """Every word of the CV as plain text, for the fabrication and wording guards."""
        h = self.header
        out = [h.name, h.city, h.phone, h.email, *h.links]
        for key in ENTRY_SECTIONS:
            for e in getattr(self, key):
                out += [f"{e.org} {e.title} {e.city} {e.start} - {e.end}", *e.bullets]
        out += self.publications + [f"{a}: {b}" for a, b in self.skills] + self.awards
        for title, lines in self.custom:
            out += [title, *lines]
        return "\n".join(x for x in out if x)


def _entry(raw: Any, where: str) -> Entry:
    if not isinstance(raw, dict):
        raise ContentError(f"{where}: expected a mapping with org, title, city, start, end, bullets")
    allowed = {f.name for f in dc.fields(Entry)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ContentError(f"{where}: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(allowed))}")
    if not raw.get("org"):
        raise ContentError(f"{where}: 'org' is required")
    e = Entry(**{k: (v if k == "bullets" else str(v if v is not None else "")) for k, v in raw.items()})
    e.bullets = [str(b) for b in (e.bullets or [])]
    return e


def _lines(raw: Any, where: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ContentError(f"{where}: expected a list")
    return [str(x) for x in raw]


def cv_from_dict(raw: dict, defaults: Header | None = None) -> CV:
    raw = dict(raw or {})
    allowed = {"lang", "header", "order", "headings", "custom", *SECTIONS}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ContentError(f"CV: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(allowed))}")
    cv = CV(lang=str(raw.get("lang") or "en"))
    hd = dc.asdict(defaults) if defaults else {}
    hd.update({k: v for k, v in (raw.get("header") or {}).items() if v})
    unknown = sorted(set(hd) - {f.name for f in dc.fields(Header)})
    if unknown:
        raise ContentError(f"CV header: unknown key(s) {', '.join(unknown)}")
    cv.header = Header(**{k: (list(v) if k == "links" else str(v)) for k, v in hd.items()})
    order = raw.get("order") or list(DEFAULT_ORDER)
    for k in order:
        if k not in SECTIONS and k != "custom":
            raise ContentError(f"CV order: {k!r} is not one of {', '.join(SECTIONS)}, custom")
    cv.order = list(order)
    cv.headings = {str(k): str(v) for k, v in (raw.get("headings") or {}).items()}
    for key in ENTRY_SECTIONS:
        setattr(cv, key, [_entry(e, f"CV {key}[{i}]") for i, e in enumerate(raw.get(key) or [])])
    cv.publications = _lines(raw.get("publications"), "CV publications")
    cv.awards = _lines(raw.get("awards"), "CV awards")
    for i, s in enumerate(raw.get("skills") or []):
        if not isinstance(s, dict) or "label" not in s or "items" not in s:
            raise ContentError(f"CV skills[{i}]: expected {{label, items}}")
        items = s["items"]
        cv.skills.append((str(s["label"]), ", ".join(map(str, items)) if isinstance(items, list) else str(items)))
    for i, c in enumerate(raw.get("custom") or []):
        if not isinstance(c, dict) or "title" not in c:
            raise ContentError(f"CV custom[{i}]: expected {{title, lines}}")
        cv.custom.append((str(c["title"]), _lines(c.get("lines"), f"CV custom[{i}].lines")))
    if "custom" not in cv.order and cv.custom:
        cv.order.append("custom")
    return cv


def load_cv(path: Path, defaults: Header | None = None) -> CV:
    import yaml
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ContentError(f"{path}: invalid YAML ({e})") from e
    return cv_from_dict(raw, defaults)


def cv_variant(base: Path, lang: str) -> Path:
    """``cv/ds.yml`` asked for in French resolves to ``cv/ds.fr.yml`` when that file exists."""
    base = Path(base)
    alt = base.with_name(f"{base.stem}.{lang}{base.suffix}")
    return alt if alt.is_file() else base


@dc.dataclass
class Letter:
    lang: str = "en"
    date: str = ""
    recipient: list[str] = dc.field(default_factory=list)
    re: str = ""
    salutation: str = ""
    closing: str = ""
    paragraphs: list[str] = dc.field(default_factory=list)

    def body_text(self) -> str:
        return "\n\n".join(self.paragraphs)

    def words(self) -> int:
        return len(re.findall(r"\w+(?:[-'’]\w+)*", self.body_text()))


_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def parse_letter(text: str) -> Letter:
    import yaml
    meta: dict = {}
    m = _FRONT.match(text)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            raise ContentError(f"letter front matter: invalid YAML ({e})") from e
        text = text[m.end():]
    allowed = {"lang", "date", "recipient", "re", "salutation", "closing"}
    unknown = sorted(set(meta) - allowed)
    if unknown:
        raise ContentError(f"letter front matter: unknown key(s) {', '.join(unknown)}")
    body = _COMMENT.sub("", text)
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", body) if p.strip()]
    rec = meta.get("recipient") or []
    return Letter(lang=str(meta.get("lang") or "en"), date=str(meta.get("date") or ""),
                  recipient=[str(x) for x in (rec if isinstance(rec, list) else [rec])],
                  re=str(meta.get("re") or ""), salutation=str(meta.get("salutation") or ""),
                  closing=str(meta.get("closing") or ""), paragraphs=paras)


def format_date(d: dt.date, lang: str) -> str:
    months = MONTHS.get(lang, MONTHS["en"]).split()
    m = months[d.month - 1]
    if lang == "en":
        return f"{m} {d.day}, {d.year}"
    if lang == "de":
        return f"{d.day}. {m} {d.year}"
    if lang in ("es", "pt"):
        return f"{d.day} de {m} de {d.year}"
    if lang == "fr" and d.day == 1:
        return f"1er {m} {d.year}"
    return f"{d.day} {m} {d.year}"


def letter_date(letter: Letter, today: dt.date) -> str:
    if not letter.date:
        return format_date(today, letter.lang)
    try:
        return format_date(dt.date.fromisoformat(letter.date), letter.lang)
    except ValueError:
        return letter.date        # already written out by hand
