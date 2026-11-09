"""Skill demand: how many postings mention each vocabulary term, and the candidate's gaps.

Matching is case- and accent-insensitive on word boundaries, so "R" does not match inside
"React" and "SQL" matches "sql," but not "nosql". A small synonym map folds common variants;
a vocabulary entry may also carry its own variants as ``"term|variant|variant"``.
"""
from __future__ import annotations

import re
import unicodedata

SYNONYMS: dict[str, tuple[str, ...]] = {
    "machine learning": ("ml",),
    "deep learning": ("neural networks", "neural network"),
    "natural language processing": ("nlp",),
    "nlp": ("natural language processing",),
    "statistics": ("statistical", "stats"),
    "javascript": ("js",),
    "typescript": ("ts",),
    "kubernetes": ("k8s",),
    "postgresql": ("postgres",),
    "excel": ("spreadsheets", "spreadsheet"),
    "a/b testing": ("ab testing", "a/b tests", "experimentation"),
    "experimentation": ("a/b testing", "ab testing"),
    "power bi": ("powerbi",),
    "scikit-learn": ("sklearn", "scikit learn"),
    "aws": ("amazon web services",),
    "gcp": ("google cloud",),
}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s)


def _variants(entry: str) -> tuple[str, list[str]]:
    parts = [p.strip() for p in entry.split("|") if p.strip()]
    term = parts[0] if parts else entry.strip()
    vs = [term, *parts[1:], *SYNONYMS.get(fold(term).strip(), ())]
    return term, list(dict.fromkeys(fold(v).strip() for v in vs if v.strip()))


def _pattern(variants: list[str], single_letter: bool) -> re.Pattern:
    alts = "|".join(re.escape(v).replace(r"\ ", r"\s+") for v in sorted(variants, key=len, reverse=True))
    # single-letter terms (R, C) must not be part of R&D, C-suite, C++, C# or a contraction
    tail = r"(?![a-z0-9&'+#-])" if single_letter else r"(?![a-z0-9])"
    return re.compile(rf"(?<![a-z0-9]){'(?:' + alts + ')'}{tail}")


def demand(texts: list[str], vocabulary: list[str]) -> list[tuple[str, int]]:
    """(term, number of texts mentioning it), most demanded first; ties alphabetical."""
    folded = [fold(t) for t in texts]
    out = []
    for entry in vocabulary:
        term, vs = _variants(entry)
        if not vs:
            continue
        rx = _pattern(vs, len(fold(term).strip()) == 1)
        out.append((term, sum(1 for t in folded if rx.search(t))))
    return sorted(out, key=lambda x: (-x[1], fold(x[0])))


def gaps(demand_rows: list[tuple[str, int]], candidate_skills: list[str], *, min_count: int = 1,
         top: int | None = None) -> list[tuple[str, int]]:
    """In-demand terms (mentioned by at least ``min_count`` postings) the candidate does not list.
    A skill counts as held when it equals the term or one of its synonyms."""
    held = set()
    for s in candidate_skills:
        _, vs = _variants(s)
        held.update(vs)
    out = []
    for term, count in demand_rows:
        if count < min_count:
            continue
        _, vs = _variants(term)
        if not held.intersection(vs):
            out.append((term, count))
    return out[:top] if top else out
