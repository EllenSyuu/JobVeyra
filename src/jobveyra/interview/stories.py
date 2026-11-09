"""STAR+R story bank: ``<workspace>/stories/*.yml``.

Each file holds one story (a mapping) or several (a list of mappings)::

    id: churn-model
    title: Cut churn-model scoring time
    situation: ...
    task: ...
    action: ...
    result: ...
    reflection: ...
    skills: [python, forecasting, stakeholder communication]
    metrics:
      - {value: "40% faster", source: "cv/master.md: Example Labs, 2024"}

Every metric must name its ``source`` (a line of the CV or the facts file), so a number never
reaches an interview answer without a place it can be checked. ``load`` keeps stories with
unsourced metrics but reports them.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

REQUIRED = ("id", "title", "situation", "task", "action", "result")
TEXT_FIELDS = ("title", "situation", "task", "action", "result", "reflection")

STOPWORDS = frozenset("""
a about above across after all also an and any are as at be been being both but by can could
do does each either etc for from has have having how if in including into is it its job least
like make may more most must new not of on one or other our ours over own per plus role should
so such than that the their them then there these they this those through to under up us very
was we well were what when where which while who will with within work working would you your
years year experience strong ability able knowledge understanding skills skill excellent good
great proven demonstrated solid preferred required requirement requirements minimum degree
related relevant equivalent field team teams candidate ideal including e.g i.e eg ie using use
""".split())
_REQ_HEAD = re.compile(r"^\s*(?:#+\s*)?(requirements?|qualifications?|what you(?:'ll)? (?:bring|need|have)|"
                       r"you have|must have|skills|about you|who you are|nice to have|preferred|"
                       r"responsibilities|what you(?:'ll)? do|key duties|duties)\b.*$", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•●▪]|\d+[.)])\s+(.*\S)")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def terms(text: str) -> set[str]:
    """Content words and adjacent-word pairs of ``text`` (folded, stopwords removed)."""
    words = re.findall(r"[a-z0-9][a-z0-9+#/.-]*[a-z0-9+#]|[a-z0-9]", fold(text))
    # light plural folding so "stakeholders" meets the skill tag "stakeholder"
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")) else w for w in words]
    words = [w for w in words if w not in STOPWORDS and not w.isdigit()]
    out = {w for w in words if len(w) > 1 or w in ("r", "c")}
    out.update(f"{a} {b}" for a, b in zip(words, words[1:]))
    return out


def posting_text(posting) -> str:
    """Text of a Posting, a dict with ``text`` (plus title), or a plain string."""
    if posting is None:
        return ""
    if isinstance(posting, str):
        return posting
    if isinstance(posting, dict):
        return "\n".join(str(posting.get(k) or "") for k in ("title", "text"))
    return "\n".join(str(getattr(posting, k, "") or "") for k in ("title", "text"))


def requirements(text: str, limit: int | None = None) -> list[str]:
    """Requirement lines: bullets (preferably under a requirements-like heading), else sentences
    that state a need ("experience with", "you will", "must")."""
    lines = (text or "").splitlines()
    under, bullets = [], []
    in_req = False
    for ln in lines:
        if _REQ_HEAD.match(ln) and len(ln) < 80:
            in_req = True
            continue
        m = _BULLET.match(ln)
        if m:
            item = m.group(1).strip().rstrip(";.")
            bullets.append(item)
            if in_req:
                under.append(item)
        elif ln.strip() and in_req and len(ln.strip()) > 60:
            in_req = False                      # a paragraph ends the section
    picked = under or bullets
    if not picked:
        sents = re.split(r"(?<=[.!?])\s+|\n+", text or "")
        cue = re.compile(r"\b(experience (?:with|in)|proficien|knowledge of|familiar|you will|you'll|must|"
                         r"required|ability to|skills? in|degree in)\b", re.I)
        picked = [s.strip().rstrip(".") for s in sents if cue.search(s) and 15 < len(s.strip()) < 300]
    seen, out = set(), []
    for p in picked:
        k = fold(p)
        if k and k not in seen:
            seen.add(k)
            out.append(p)
    return out[:limit] if limit else out


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def validate(story: dict) -> list[str]:
    """Problems with one story (empty list = valid)."""
    sid = story.get("id") or "(no id)"
    probs = [f"{sid}: missing {k}" for k in REQUIRED if not str(story.get(k) or "").strip()]
    for i, m in enumerate(_as_list(story.get("metrics"))):
        if not isinstance(m, dict) or not str(m.get("source") or "").strip():
            label = m.get("value", m) if isinstance(m, dict) else m
            probs.append(f"{sid}: metric {i + 1} ({label}) has no source; point it to a CV line or the facts file")
    return probs


def load(workspace) -> tuple[list[dict], list[str]]:
    """Read ``<workspace>/stories/*.yml`` (or a stories directory given directly).

    Returns ``(stories, problems)``. Stories missing a required field are left out; stories whose
    metrics lack a ``source`` are kept with ``unsourced`` listing those metrics. Duplicate ids keep
    the first file (alphabetical) and are reported."""
    import yaml
    base = Path(workspace)
    d = base if base.name == "stories" or not (base / "stories").is_dir() else base / "stories"
    stories, problems, ids = [], [], set()
    if not d.is_dir():
        return [], []
    for f in sorted([*d.glob("*.yml"), *d.glob("*.yaml")]):
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            problems.append(f"{f.name}: invalid YAML ({e})")
            continue
        for s in _as_list(raw):
            if not isinstance(s, dict):
                problems.append(f"{f.name}: each story must be a mapping")
                continue
            s = dict(s)
            s["skills"] = [str(x) for x in _as_list(s.get("skills"))]
            s["metrics"] = _as_list(s.get("metrics"))
            probs = validate(s)
            missing = [p for p in probs if ": missing " in p]
            problems.extend(f"{f.name}: {p}" for p in probs)
            if missing:
                continue
            s["id"] = str(s["id"])
            if s["id"] in ids:
                problems.append(f"{f.name}: duplicate story id {s['id']}")
                continue
            ids.add(s["id"])
            s["unsourced"] = [m for m in s["metrics"] if not (isinstance(m, dict) and str(m.get("source") or "").strip())]
            s["file"] = f.name
            stories.append(s)
    return stories, problems


def story_terms(story: dict) -> tuple[set[str], set[str]]:
    skills = set()
    for sk in story.get("skills") or []:
        skills.add(fold(sk))
        skills.update(terms(sk))
    body = terms(" ".join(str(story.get(k) or "") for k in TEXT_FIELDS))
    return skills, body


def match(stories: list[dict], posting, *, limit: int | None = None) -> list[dict]:
    """Stories ranked by overlap with the posting's requirement terms. A skill tag that appears
    in the requirements counts three times a word shared with the story text; stories with
    unsourced metrics rank after equally scored sourced ones. Zero-overlap stories are dropped.
    Each item: ``{"story", "score", "matched"}``."""
    text = posting_text(posting)
    reqs = requirements(text)
    want = terms("\n".join(reqs) if reqs else text)
    ranked = []
    for s in stories:
        skills, body = story_terms(s)
        hit_sk = skills & want
        hit_body = (body & want) - hit_sk
        score = 3 * len(hit_sk) + len(hit_body)
        if score:
            ranked.append({"story": s, "score": score,
                           "matched": sorted(hit_sk) + sorted(t for t in hit_body if " " not in t)})
    ranked.sort(key=lambda r: (-r["score"], bool(r["story"].get("unsourced")), str(r["story"].get("id"))))
    return ranked[:limit] if limit else ranked
