"""The user's configuration: who they are, where and what they want, and how far automation may go.

One YAML file, ``jobveyra.yml``, in the workspace (see ``paths.py``). Every section has safe
defaults, so ``jobveyra init`` can write a short file and grow it later. Validation errors name
the exact key and the allowed values; nothing is silently ignored.

Sections
  candidate  identity and the fact base used by the fabrication guard
  focus      regions, remote policy, tracks (role families), seniority, salary floor, blockers
  policy     submission mode (batch_approve | auto | fill_only), batch size, fit thresholds,
             daily cap, source diversity
  sources    job boards and feeds to scan (see jobveyra.sources)
  materials  document languages, paper size, page limits, letter length, LaTeX engine
  notify     newsletter email, Telegram, generic webhook (Slack, Discord, Teams)
  llm        optional model for semantic scoring and drafting; deterministic code stays the
             source of truth and personal data is masked before any call by default
"""
from __future__ import annotations

import dataclasses as dc
import re
from pathlib import Path
from typing import Any

from . import paths

SUBMISSION_MODES = ("batch_approve", "auto", "fill_only")
REMOTE_MODES = ("allow", "only", "exclude")
SENIORITY = ("intern", "junior", "mid", "senior", "lead", "principal", "director", "executive")
LLM_PROVIDERS = ("none", "anthropic", "openai", "ollama", "openai_compatible")


class ConfigError(ValueError):
    pass


@dc.dataclass
class Region:
    name: str
    match: list[str] = dc.field(default_factory=list)   # case-insensitive substrings of a location
    remote_ok: bool = True                               # remote roles tied to this region count
    weight: float = 1.0                                  # ranking preference, 0..1


@dc.dataclass
class Track:
    key: str
    label: str
    titles: list[str] = dc.field(default_factory=list)  # title keywords that put a job on this track
    skills: list[str] = dc.field(default_factory=list)  # skills the candidate can evidence for it
    cv: str = ""                                         # CV variant path, relative to workspace


@dc.dataclass
class Candidate:
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = dc.field(default_factory=list)
    languages: dict[str, str] = dc.field(default_factory=dict)       # code -> level (native, C1, B2 ...)
    work_authorization: list[str] = dc.field(default_factory=list)   # country / bloc codes: CA, US, EU, UK ...
    needs_sponsorship: bool = False
    master_cv: str = "cv/master.md"
    facts: str = ""                                                  # optional extra verified facts (YAML)
    status: list[str] = dc.field(default_factory=list)               # tags market packs read: citizen, permanent_resident ...
    level: str = ""                                                  # your own level (junior, mid ...): titles 2+ above are out of reach
    years_experience: float | None = None                            # relevant years; postings asking 3+ more are out of reach


@dc.dataclass
class Focus:
    regions: list[Region] = dc.field(default_factory=list)
    remote: str = "allow"
    tracks: list[Track] = dc.field(default_factory=list)
    seniority_min: str = "junior"
    seniority_max: str = "senior"
    exclude_titles: list[str] = dc.field(default_factory=lambda: ["unpaid", "volunteer"])
    employment: list[str] = dc.field(default_factory=lambda: ["full_time"])
    salary_floor: float = 0.0
    salary_currency: str = ""
    languages_ok: list[str] = dc.field(default_factory=lambda: ["en"])  # job languages the candidate works in
    flagship_employers: list[str] = dc.field(default_factory=list)
    avoid_employers: list[str] = dc.field(default_factory=list)
    markets: list[str] = dc.field(default_factory=list)             # market packs: canada-quebec, united-states ...


@dc.dataclass
class Policy:
    submission: str = "batch_approve"
    batch_size: int = 25
    approval_ttl_hours: int = 24
    max_per_day: int = 50
    exclude_below: int = 45
    full_package_at: int = 70
    min_sources: int = 3
    max_source_share: float = 0.6
    follow_up_days: int = 10


@dc.dataclass
class Materials:
    languages: list[str] = dc.field(default_factory=lambda: ["en"])  # document languages, first is the default
    paper: str = "letter"                                            # letter | a4
    cv_pages: int = 1
    letter_pages: int = 1
    letter_words: list[int] = dc.field(default_factory=lambda: [250, 330])
    engine: str = "auto"                                             # auto | lualatex | xelatex
    font: str = "auto"                                               # auto, or any installed font name
    voice: str = "warn"                                              # warn | strict | off (writing tells)


@dc.dataclass
class Notify:
    email_enabled: bool = False
    telegram_enabled: bool = False
    webhook_env: str = "JOBVEYRA_WEBHOOK"


@dc.dataclass
class LLM:
    provider: str = "none"
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    anonymize: bool = True


@dc.dataclass
class Config:
    workspace: Path
    candidate: Candidate
    focus: Focus
    policy: Policy
    sources: list[dict[str, Any]]
    notify: Notify
    llm: LLM
    materials: Materials = dc.field(default_factory=Materials)

    def path(self, rel: str) -> Path:
        return (self.workspace / rel).resolve() if rel else self.workspace

    @property
    def state_dir(self) -> Path:
        return self.workspace / "state"


def _pick(cls, raw: dict | None, where: str):
    raw = dict(raw or {})
    names = {f.name for f in dc.fields(cls)}
    unknown = sorted(set(raw) - names)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(names))}")
    return cls(**raw)


def _choice(value: str, allowed: tuple[str, ...], key: str) -> str:
    if value not in allowed:
        raise ConfigError(f"{key}: {value!r} is not one of {', '.join(allowed)}")
    return value


def from_dict(raw: dict, workspace: Path) -> Config:
    raw = dict(raw or {})
    unknown = sorted(set(raw) - {"candidate", "focus", "policy", "sources", "notify", "llm", "materials"})
    if unknown:
        raise ConfigError(f"top level: unknown section(s) {', '.join(unknown)}")
    f = dict(raw.get("focus") or {})
    regions = [_pick(Region, r, f"focus.regions[{i}]") for i, r in enumerate(f.pop("regions", []) or [])]
    tracks = [_pick(Track, t, f"focus.tracks[{i}]") for i, t in enumerate(f.pop("tracks", []) or [])]
    focus = _pick(Focus, f, "focus")
    focus.regions, focus.tracks = regions, tracks
    _choice(focus.remote, REMOTE_MODES, "focus.remote")
    _choice(focus.seniority_min, SENIORITY, "focus.seniority_min")
    _choice(focus.seniority_max, SENIORITY, "focus.seniority_max")
    if SENIORITY.index(focus.seniority_min) > SENIORITY.index(focus.seniority_max):
        raise ConfigError("focus.seniority_min is above focus.seniority_max")
    keys = [t.key for t in tracks]
    if len(keys) != len(set(keys)):
        raise ConfigError("focus.tracks: track keys must be unique")
    for t in tracks:
        if not re.fullmatch(r"[a-z0-9_-]+", t.key):
            raise ConfigError(f"focus.tracks: key {t.key!r} must be lowercase letters, digits, - or _")

    candidate = _pick(Candidate, raw.get("candidate"), "candidate")
    if candidate.level:
        _choice(candidate.level, SENIORITY, "candidate.level")
    from . import markets as _markets
    try:
        _markets.load(focus.markets, workspace)
    except _markets.PackError as e:
        raise ConfigError(f"focus.markets: {e}") from e
    policy = _pick(Policy, raw.get("policy"), "policy")
    _choice(policy.submission, SUBMISSION_MODES, "policy.submission")
    if not 0 <= policy.exclude_below <= policy.full_package_at <= 100:
        raise ConfigError("policy: need 0 <= exclude_below <= full_package_at <= 100")
    if not 0 < policy.max_source_share <= 1:
        raise ConfigError("policy.max_source_share must be in (0, 1]")

    llm = _pick(LLM, raw.get("llm"), "llm")
    _choice(llm.provider, LLM_PROVIDERS, "llm.provider")
    materials = _pick(Materials, raw.get("materials"), "materials")
    _choice(materials.paper, ("letter", "a4"), "materials.paper")
    _choice(materials.engine, ("auto", "lualatex", "xelatex"), "materials.engine")
    _choice(materials.voice, ("warn", "strict", "off"), "materials.voice")
    lw = materials.letter_words
    if not (isinstance(lw, list) and len(lw) == 2 and 0 < int(lw[0]) <= int(lw[1])):
        raise ConfigError("materials.letter_words must be [min, max] with 0 < min <= max")
    if materials.cv_pages < 1 or materials.letter_pages < 1:
        raise ConfigError("materials: page limits must be at least 1")
    from .documents.content import LANGS
    bad = [x for x in materials.languages if x not in LANGS]
    if bad or not materials.languages:
        raise ConfigError(f"materials.languages: use codes from {', '.join(LANGS)}")
    sources = list(raw.get("sources") or [])
    for i, s in enumerate(sources):
        if not isinstance(s, dict) or "type" not in s:
            raise ConfigError(f"sources[{i}]: each source needs a 'type'")
    return Config(workspace=workspace, candidate=candidate,
                  focus=focus, policy=policy, sources=sources,
                  notify=_pick(Notify, raw.get("notify"), "notify"), llm=llm, materials=materials)


def load(workspace: Path | None = None) -> Config:
    import yaml
    ws = workspace or paths.workspace()
    p = ws / paths.CONFIG_NAME
    if not p.is_file():
        raise ConfigError(f"no {paths.CONFIG_NAME} in {ws}; run `jobveyra init` first")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{p}: invalid YAML ({e})") from e
    return from_dict(raw, ws)


def default() -> Config:
    """A config with every default, for tests and for code paths that run before `init`."""
    return from_dict({}, paths.workspace())
