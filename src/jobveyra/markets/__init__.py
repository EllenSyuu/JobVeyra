"""Market packs: the rules of a job market that are not about the candidate.

A pack is a YAML file. Built-in packs live in ``markets/packs/``; a user can add or override one
in ``<workspace>/markets/<name>.yml``. ``focus.markets`` in jobveyra.yml lists the active packs::

    name: canada-quebec
    description: Montréal, Québec and Canadian federal employers
    applies_to: [canada, quebec, québec, montreal, montréal, ottawa, " qc", " on,"]   # location substrings; empty = everywhere
    rules:
      - id: citizen_or_pr_required
        match: 'canadian citizens? or permanent residents?|permanent residen(?:t|cy) (?:status )?(?:is )?required'
        verdict: fail               # fail: excludes the job | flag: a warning on the evaluation | note
        unless_status: [citizen, permanent_resident]
        note: The employer hires citizens and permanent residents only.
    documents:
      headings: {fr: {experience: Expérience professionnelle}}
      salutation: {fr: "Madame, Monsieur,"}
      closing: {fr: "Cordialement,"}
    guidance: |
      Markdown for the writer: CV conventions, letter conventions, portal habits.

A rule matches when ``match`` (a case-insensitive regex over the posting text) finds a line, and
optionally ``match_title`` / ``match_employment`` / ``match_location`` also match. ``unless_status``
skips the rule when the candidate's ``candidate.status`` has any of those tags; ``if_status`` applies
it only when the candidate has one. The quoted line is kept as evidence.

Packs describe public rules for triage, never legal advice; a FLAG means: read the quoted line.
"""
from __future__ import annotations

import dataclasses as dc
import re
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parent / "packs"
VERDICTS = ("fail", "flag", "note")


class PackError(ValueError):
    pass


@dc.dataclass
class Rule:
    id: str
    verdict: str
    match: str = ""
    match_title: str = ""
    match_employment: str = ""
    match_location: str = ""
    unless_status: list[str] = dc.field(default_factory=list)
    if_status: list[str] = dc.field(default_factory=list)
    note: str = ""


@dc.dataclass
class Pack:
    name: str
    description: str = ""
    applies_to: list[str] = dc.field(default_factory=list)
    rules: list[Rule] = dc.field(default_factory=list)
    documents: dict = dc.field(default_factory=dict)
    guidance: str = ""
    path: str = ""

    def applies(self, location: str, remote: bool | None = None) -> bool:
        if not self.applies_to:
            return True
        loc = f" {(location or '').lower()} "
        # whole tokens only: ", ca" must not match ", canada"
        return any(re.search(_token(a), loc) for a in self.applies_to if a.strip())


def _token(entry: str) -> str:
    """A regex for ``entry`` that only matches at word edges where the entry has a letter there."""
    e = entry.strip().lower()
    return (r"(?<!\w)" if e[0].isalnum() else "") + re.escape(e) + (r"(?!\w)" if e[-1].isalnum() else "")


def _rule(raw: dict, where: str) -> Rule:
    allowed = {f.name for f in dc.fields(Rule)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise PackError(f"{where}: unknown key(s) {', '.join(unknown)}")
    r = Rule(**raw)
    if r.verdict not in VERDICTS:
        raise PackError(f"{where}: verdict must be one of {', '.join(VERDICTS)}")
    if not any((r.match, r.match_title, r.match_employment, r.match_location)):
        raise PackError(f"{where}: a rule needs match, match_title, match_employment or match_location")
    for k in ("match", "match_title", "match_employment", "match_location"):
        try:
            re.compile(getattr(r, k))
        except re.error as e:
            raise PackError(f"{where}.{k}: invalid regex ({e})") from e
    return r


def parse(raw: dict, path: str = "") -> Pack:
    raw = dict(raw or {})
    allowed = {"name", "description", "applies_to", "rules", "documents", "guidance"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise PackError(f"{path or 'pack'}: unknown key(s) {', '.join(unknown)}")
    if not raw.get("name"):
        raise PackError(f"{path or 'pack'}: 'name' is required")
    rules = [_rule(r, f"{raw['name']}.rules[{i}]") for i, r in enumerate(raw.get("rules") or [])]
    return Pack(name=str(raw["name"]), description=str(raw.get("description") or ""),
                applies_to=[str(x) for x in raw.get("applies_to") or []], rules=rules,
                documents=dict(raw.get("documents") or {}), guidance=str(raw.get("guidance") or ""), path=path)


def available(workspace: Path | None = None) -> dict[str, Path]:
    found = {p.stem: p for p in sorted(PACK_DIR.glob("*.yml"))}
    if workspace is not None and (Path(workspace) / "markets").is_dir():
        found.update({p.stem: p for p in sorted((Path(workspace) / "markets").glob("*.yml"))})
    return found


def load(names: list[str], workspace: Path | None = None) -> list[Pack]:
    import yaml
    have = available(workspace)
    packs = []
    for n in names:
        if n not in have:
            raise PackError(f"unknown market pack {n!r}; available: {', '.join(sorted(have))}")
        packs.append(parse(yaml.safe_load(have[n].read_text(encoding="utf-8")) or {}, str(have[n])))
    return packs


def _line(text: str, m: re.Match) -> str:
    start = text.rfind("\n", 0, m.start()) + 1
    end = text.find("\n", m.end())
    return " ".join(text[start: end if end != -1 else len(text)].split())[:200]


def check(packs: list[Pack], posting, status: list[str]) -> list[dict]:
    """``[{"pack", "rule", "verdict", "quote", "note"}]`` for every rule the posting triggers."""
    tags = {s.lower() for s in status or []}
    text = posting.text or ""
    hits = []
    for pack in packs:
        if not pack.applies(posting.location or "", posting.remote):
            continue
        for r in pack.rules:
            if r.unless_status and tags & {s.lower() for s in r.unless_status}:
                continue
            if r.if_status and not tags & {s.lower() for s in r.if_status}:
                continue
            quote = ""
            if r.match:
                m = re.search(r.match, text, re.I)
                if not m:
                    continue
                quote = _line(text, m)
            ok = True
            for field_, value in (("match_title", posting.title), ("match_employment", posting.employment),
                                  ("match_location", posting.location)):
                rx = getattr(r, field_)
                if rx and not re.search(rx, value or "", re.I):
                    ok = False
            if not ok:
                continue
            hits.append({"pack": pack.name, "rule": r.id, "verdict": r.verdict,
                         "quote": quote or (posting.title if r.match_title else ""), "note": r.note})
    return hits


def document_defaults(packs: list[Pack], location: str, lang: str) -> dict:
    """Headings, salutation and closing a pack sets for a language (first applicable pack wins)."""
    out: dict = {"headings": {}, "salutation": "", "closing": "", "guidance": []}
    for p in packs:
        if not p.applies(location):
            continue
        docs = p.documents or {}
        for k, v in ((docs.get("headings") or {}).get(lang) or {}).items():
            out["headings"].setdefault(k, v)
        out["salutation"] = out["salutation"] or (docs.get("salutation") or {}).get(lang, "")
        out["closing"] = out["closing"] or (docs.get("closing") or {}).get(lang, "")
        if p.guidance:
            out["guidance"].append((p.name, p.guidance.strip()))
    return out
