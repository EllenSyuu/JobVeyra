"""Focus filters applied at discovery: region and remote policy, seniority, title and employer blocks.

``passes`` returns ``(ok, reason)``. Reason codes are machine-readable and stable:
  avoid_employer        employer is in focus.avoid_employers
  title:<word>          title contains a focus.exclude_titles entry (whole words)
  employment:<type>     known employment type not in focus.employment
  seniority:<level>     title seniority outside focus.seniority_min..seniority_max
  remote:only           focus.remote is "only" and the job is not remote
  remote:excluded       focus.remote is "exclude" and the job is remote
  region                no focus region matches the location
Unknown values (no employment type, no location on a remote job) never fail a filter on their own.
"""
from __future__ import annotations

import re
import unicodedata

from .config import SENIORITY, Focus, Region, Track
from .models import Posting
from .queue import employer_key

ANY_REGION = Region(name="any", match=[], remote_ok=True)


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " " + re.sub(r"[^a-z0-9]+", " ", s).strip() + " "


def _has(folded: str, phrase: str) -> bool:
    p = _fold(phrase)
    return p.strip() != "" and p in folded


_REMOTE = re.compile(r" (remote|fully remote|work from home|teletravail|teletrabajo|remoto|anywhere|worldwide|"
                     r"telecommute|home based) ")
_OPEN_LOCATION = re.compile(r"^ ((fully )?remote|anywhere|worldwide|global|work from home|teletravail|remoto)? $")


# ---------------------------------------------------------------- region

def region_of(location: str, remote: bool | None, focus: Focus) -> Region | None:
    """The first focus region whose ``match`` strings occur in ``location`` (case-insensitive).

    A match string counts as a plain substring when it has 4 or more characters, and as a whole
    word (accents ignored) at any length, so "us" matches "Austin, US" but not "Austin, TX".

    ``remote`` None is inferred from the location text ("Remote", "Anywhere", "télétravail").
    focus.remote "only" rejects non-remote jobs; "exclude" rejects remote ones. A remote job only
    counts for a region with ``remote_ok``. A remote job whose location names no place ("Remote",
    "Anywhere", empty) counts for the first region with ``remote_ok``. With no regions configured
    every location matches ``ANY_REGION``.
    """
    loc = _fold(location)
    if remote is None and _REMOTE.search(loc):
        remote = True
    if focus.remote == "only" and remote is not True:
        return None
    if focus.remote == "exclude" and remote is True:
        return None
    if not focus.regions:
        return ANY_REGION
    for r in focus.regions:
        if any(_has(loc, m) or (len(m.strip()) >= 4 and m.strip().lower() in (location or "").lower())
               for m in r.match):
            if remote is True and not r.remote_ok:
                continue
            return r
    if remote is True and _OPEN_LOCATION.match(loc):
        return next((r for r in focus.regions if r.remote_ok), None)
    return None


# ---------------------------------------------------------------- seniority

_S = {
    "intern": r"intern|interns|internship|stagiaire|stage d ete|stage de fin d etudes|praktikant(?:in)?|praktikum|"
              r"werkstudent(?:in)?|estagiari[oa]|estagio|becari[oa]|practicante|practicas?|pasantia|pasante|trainee|"
              r"apprentice|apprenti|apprentie|alternance|alternant|co ?op|summer student|working student|azubi",
    "executive": r"chief|ceo|cto|cfo|coo|cio|cdo|cpo|vice president|vp|svp|evp|avp|president|managing director|"
                 r"director general|directeur general|directrice generale|geschaftsfuhrer(?:in)?|vorstand|"
                 r"diretor executivo|diretora executiva|executive director|directeur executif|director ejecutivo",
    "lead_compound": r"team ?lead|tech ?lead|teamleiter(?:in)?|gruppenleiter(?:in)?|chef d equipe|"
                     r"lider de equipo|lider tecnico|engineering manager",
    "director": r"director|directora|directeur|directrice|diretor|diretora|head|\w*leiter(?:in)?|general manager",
    "principal": r"principal|principale|distinguished|fellow",
    "lead": r"lead|leader|lider|jefe|jefa|supervisor|superviseur|staff (?:[a-z]+ ){0,2}"
            r"(?:engineer|scientist|developer|architect)",
    "senior": r"senior|sr|snr|experienced|expert|experte|especialista senior",
    "junior": r"junior|jr|entry level|entry|graduate|new grad|recent graduate|associate|assistant|assistante|"
              r"assistente|asistente|debutant|debutante|einsteiger(?:in)?|berufseinsteiger(?:in)?|level 1",
    "mid": r"mid|mid level|intermediate|intermediaire|pleno|semi senior|level 2",
}
_SRX = {k: re.compile(r" (?:" + v + r") ") for k, v in _S.items()}
_EXEC_SUPPORT = re.compile(r" (assistant|aide|secretary|office|analyst|coordinator|associate|support) ")
# Roman-numeral levels ("Analyst II") are matched case-sensitively on the raw title.
_ROMAN = re.compile(r"(?:^|[\s,(/-])(I{1,3}|IV|V)(?=$|[\s,)/-])")


def seniority_of(title: str) -> str:
    """Map a title to one of SENIORITY (intern ... executive). Titles that name no level are "mid".

    Checked from most to least specific: intern, executive (not "assistant to the CEO"), team-lead
    compounds, director / head, principal, lead / staff engineer, senior, junior. A trailing roman
    numeral grades the rest: I junior, II mid, III-V senior. Accents are ignored, so French,
    Spanish, Portuguese and German forms (stagiaire, sénior, directeur, Leiter, estagiário) match.
    Plain "manager" names no level and stays "mid".
    """
    t = _fold(title)
    if _SRX["intern"].search(t):
        return "intern"
    if _SRX["executive"].search(t) and not _EXEC_SUPPORT.search(t):
        return "executive"
    if _SRX["lead_compound"].search(t):
        return "lead"
    if _SRX["director"].search(t):
        return "director"
    if _SRX["principal"].search(t):
        return "principal"
    if _SRX["lead"].search(t):
        return "lead"
    if _SRX["senior"].search(t):
        return "senior"
    if _SRX["junior"].search(t):
        return "junior"
    roman = _ROMAN.findall(title or "")
    level = roman[-1] if roman else ""
    if level in ("III", "IV", "V"):
        return "senior"
    if level == "I":
        return "junior"
    return "mid"


# ---------------------------------------------------------------- track

def track_of(title: str, focus: Focus) -> Track | None:
    """The first track (config order) with a ``titles`` keyword in the title (whole words)."""
    t = _fold(title)
    for tr in focus.tracks:
        if any(_has(t, kw) for kw in tr.titles):
            return tr
    return None


# ---------------------------------------------------------------- the gate

def _avoided(employer: str, focus: Focus) -> bool:
    ek, e = employer_key(employer), _fold(employer)
    return any(a.strip() and (employer_key(a) == ek or _has(e, a)) for a in focus.avoid_employers)


def passes(p: Posting, focus: Focus) -> tuple[bool, str]:
    """Apply avoid_employers, exclude_titles, employment, seniority range and regions, in that order.
    Returns ``(True, "")`` or ``(False, reason)`` with the first reason that fails."""
    if _avoided(p.employer, focus):
        return False, "avoid_employer"
    t = _fold(p.title)
    for word in focus.exclude_titles:
        if _has(t, word):
            return False, f"title:{word.strip().lower()}"
    if p.employment and focus.employment and p.employment not in focus.employment:
        return False, f"employment:{p.employment}"
    s = seniority_of(p.title)
    lo, hi = SENIORITY.index(focus.seniority_min), SENIORITY.index(focus.seniority_max)
    if not lo <= SENIORITY.index(s) <= hi:
        return False, f"seniority:{s}"
    if region_of(p.location, p.remote, focus) is None:
        remote = p.remote if p.remote is not None else (True if _REMOTE.search(_fold(p.location)) else None)
        if focus.remote == "only" and remote is not True:
            return False, "remote:only"
        if focus.remote == "exclude" and remote is True:
            return False, "remote:excluded"
        return False, "region"
    return True, ""
