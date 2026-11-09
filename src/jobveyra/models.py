"""Shared records passed between sources, evaluation, the queue and reports."""
from __future__ import annotations

import dataclasses as dc
import hashlib
import re
from typing import Any


@dc.dataclass
class Posting:
    """One job as a source returns it. ``text`` is the full description when the source has it."""
    source: str                    # adapter name: greenhouse, lever, un_careers ...
    employer: str
    title: str
    url: str                       # canonical posting page at the employer or ATS
    apply_url: str = ""
    req_id: str = ""               # the employer's requisition / job number
    location: str = ""
    remote: bool | None = None
    posted: str = ""               # ISO date
    deadline: str = ""             # ISO date
    employment: str = ""           # full_time, part_time, contract, temporary, internship
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    lang: str = ""                 # posting language, ISO 639-1
    text: str = ""
    extra: dict[str, Any] = dc.field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        norm = re.sub(r"\s+", " ", f"{self.employer}|{self.title}|{self.text}".lower()).strip()
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]

    def to_queue(self) -> dict[str, Any]:
        """Fields the queue stores (the text itself is cached under postings/)."""
        return {"employer": self.employer, "title": self.title, "url": self.url,
                "apply_url": self.apply_url or self.url, "req_id": self.req_id, "source": self.source,
                "location": self.location, "posted": self.posted, "deadline": self.deadline,
                "lang": self.lang, "content_hash": self.content_hash}


@dc.dataclass
class Evidence:
    """Why a dimension scored what it did. ``basis`` says how sure we are."""
    note: str
    basis: str = "text"            # text: quoted from the posting; structure: from fields; estimate: inferred


@dc.dataclass
class Dimension:
    key: str
    score: float                   # 0..1
    weight: float
    evidence: list[Evidence] = dc.field(default_factory=list)


@dc.dataclass
class Evaluation:
    job_id: str
    fit: int                       # 0..100
    stars: float                   # 1..5, one decimal
    track: str = ""
    dimensions: list[Dimension] = dc.field(default_factory=list)
    blockers: list[str] = dc.field(default_factory=list)     # hard stops: no sponsorship, language ...
    flags: list[str] = dc.field(default_factory=list)        # soft warnings: repost, stale, vague pay ...
    lane: str = ""                 # excluded | fast | full
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dc.asdict(self)
