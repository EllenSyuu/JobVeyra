"""Interview prep sheet (Markdown) for one job.

Built only from the posting text, the queue row, the story bank and the config: every
"evidence" line points to a story or a track skill the candidate already declared, and a
requirement without evidence says so instead of inventing any.
"""
from __future__ import annotations

import re

from . import stories as st

SOFT = re.compile(r"\b(stakeholder|communicat|collaborat|team|lead|mentor|present|influenc|prioriti|deadline|"
                  r"ambigu|conflict|cross-functional|partner|client|customer|ownership|initiative|"
                  r"independen|adapt|feedback|organi[sz])\w*", re.I)
FLAG_TEXT = {
    "closed": "the posting may already be closed",
    "repost": "the role has been reposted {n} times; ask why it is open again",
    "stale": "the posting is {n} days old; confirm it is still being filled",
    "evergreen": "it looks like an evergreen or pipeline posting; ask whether there is a specific opening",
    "no_salary": "no salary is published; ask for the range early",
    "vague_title": "the title is vague; ask what the day-to-day work is",
}
TECH_HINTS = ("python", "sql", "r", "statistics", "machine learning", "forecasting", "experimentation", "spark",
              "tableau", "power bi", "excel", "aws", "gcp", "azure", "docker", "kubernetes", "dbt", "airflow",
              "pandas", "pytorch", "tensorflow", "scikit-learn", "bayesian", "regression", "causal inference",
              "a/b testing", "time series", "nlp", "deep learning", "etl", "data pipelines", "git", "stan",
              "survival analysis", "monte carlo", "optimization", "dashboards", "java", "scala", "javascript")


def _flags(job: dict, posting) -> list[str]:
    raw = []
    for src in (job.get("flags"), getattr(posting, "extra", {}).get("flags") if posting is not None and not isinstance(posting, (str, dict)) else None,
                posting.get("flags") if isinstance(posting, dict) else None):
        if isinstance(src, str):
            raw += [x.strip() for x in src.split(",") if x.strip()]
        elif src:
            raw += [str(x) for x in src]
    out = []
    for f in dict.fromkeys(raw):
        code, _, n = f.partition(":")
        tpl = FLAG_TEXT.get(code)
        out.append(tpl.format(n=n or "several") if tpl else f.replace("_", " "))
    return out


def _skills_in(text: str, extra: list[str]) -> list[str]:
    """Known skill terms present in ``text``, in order of first appearance."""
    from ..analytics.skills import _pattern, _variants, fold
    folded, found = fold(text), []
    for entry in dict.fromkeys([*extra, *TECH_HINTS]):
        term, vs = _variants(entry)
        m = _pattern(vs, len(term.strip()) == 1).search(folded)
        if m:
            # show the term as the posting writes it (SQL, PyTorch) when it appears verbatim
            orig = re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.I)
            found.append((m.start(), orig.group(0) if orig else term))
    return list(dict.fromkeys(t for _, t in sorted(found)))


def _poss(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _short(s: str, n: int = 90) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "..."


def _lc(s: str) -> str:
    s = s.strip().rstrip(".;:")
    return s[:1].lower() + s[1:] if s[:2] != s[:2].upper() else s


def questions(posting_text: str, job: dict, track_skills: list[str]) -> dict[str, list[str]]:
    employer = job.get("employer") or "the employer"
    title = job.get("title") or "this role"
    reqs = st.requirements(posting_text)
    soft = [r for r in reqs if SOFT.search(r)]
    tech = _skills_in(posting_text, track_skills)
    lead = re.compile(r"(?i)^(\d|experience|knowledge|degree|bachelor|master|phd|familiar|proficien|fluent|strong|"
                      r"excellent|proven|demonstrated|solid|at least|minimum)")
    hard = [r for r in reqs if r not in soft and not lead.match(r) and len(r.split()) >= 4]

    beh = [f"Tell me about a time you had to {_lc(_short(r, 80))}." if not re.match(r"(?i)(experience|proven|demonstrated|strong|excellent)", r)
           else f"Give an example that shows: {_short(r, 80)}." for r in soft]
    beh += ["Tell me about a project that did not go to plan. What did you change?",
            "Describe a time you explained a technical result to someone without a technical background.",
            "Tell me about a decision you made with incomplete data.",
            "Describe a time you disagreed with a colleague about an approach. How was it resolved?",
            "Tell me about the piece of work you are proudest of and why."]
    techq = [f"How have you used {t} in practice? Walk through a recent example and the trade-offs." for t in tech[:3]]
    techq += [f"Walk me through how you would {_lc(_short(r, 80))}." for r in hard[:3]]
    techq += ["How do you check that an analysis or model is correct before you share it?",
              "Walk through how you would structure the first version of a project in this team.",
              "Which method or tool would you choose for a problem you have not seen before, and how would you decide?"]
    mot = [f"Why do you want to work at {employer}?",
           f"Why this {title} role, and why now?",
           f"What do you know about {_poss(employer)} work, and which part of it interests you most?",
           "What would you want to have achieved in the first six months?",
           "What kind of team and manager help you do your best work?"]
    dedupe = lambda xs: list(dict.fromkeys(xs))[:5]  # noqa: E731
    return {"behavioral": dedupe(beh), "technical": dedupe(techq), "motivation": dedupe(mot)}


def prep_sheet(job: dict, posting, stories: list[dict], cfg) -> str:
    """Markdown prep sheet: summary, requirements with evidence, likely questions, mapped stories,
    questions to ask, logistics and red flags. Plain text, no emojis."""
    text = st.posting_text(posting)
    employer = job.get("employer") or getattr(posting, "employer", "") or "Employer"
    title = job.get("title") or getattr(posting, "title", "") or "Role"
    track = next((t for t in cfg.focus.tracks if t.key == job.get("family")), None)
    track_skills = list(track.skills) if track else [s for t in cfg.focus.tracks for s in t.skills]
    job = {**job, "employer": employer, "title": title}

    L = [f"# Interview prep: {title} at {employer}", "", "## Role summary", ""]
    L.append(f"- Employer: {employer}")
    L.append(f"- Role: {title}")
    for label, key in (("Location", "location"), ("Source", "source"), ("Posting", "url")):
        v = job.get(key) or getattr(posting, key, "")
        if v:
            L.append(f"- {label}: {v}")
    if track:
        L.append(f"- Track: {track.label}")
    if job.get("fit") not in (None, ""):
        L.append(f"- Fit score: {int(float(job['fit']))} / 100")
    desc = posting if isinstance(posting, str) else (
        posting.get("text", "") if isinstance(posting, dict) else getattr(posting, "text", ""))
    body = re.sub(r"\s+", " ", re.sub(r"(?m)^\s*(?:[-*•]|#+)\s*", "", desc or "")).strip()
    first = " ".join(re.split(r"(?<=[.!?])\s+", body)[:2]).strip()
    if first:
        L += ["", _short(first, 400)]

    reqs = st.requirements(text, limit=6)
    ranked = st.match(stories, posting)
    L += ["", "## Top requirements and your evidence", ""]
    if not reqs:
        L.append("No requirement list found in the posting text.")
    for r in reqs:
        want = st.terms(r)
        ev = [f'story "{m["story"]["title"]}"' for m in st.match(stories, r)[:2]]
        ev += [f"track skill: {s}" for s in track_skills if st.fold(s) in want or st.terms(s) & want][:2]
        L.append(f"- {r}")
        L.append(f"  - Evidence: {'; '.join(ev)}" if ev else
                 "  - Evidence: none on file yet. Add a story or a verified fact before claiming this.")

    L += ["", "## Likely questions", ""]
    for cat, qs in questions(text, job, track_skills).items():
        L += [f"### {cat.capitalize()}", ""] + [f"{i}. {q}" for i, q in enumerate(qs, 1)] + [""]

    L += ["## Stories to use", ""]
    if not ranked:
        L.append("No story in the bank overlaps this posting. Write one for the top requirement above.")
    for m in ranked[:5]:
        s = m["story"]
        L.append(f"- **{s['title']}** ({s['id']}): matches {', '.join(m['matched'][:6])}")
        L.append(f"  - Situation and task: {_short(str(s.get('situation', '')) + ' ' + str(s.get('task', '')), 160)}")
        L.append(f"  - Action: {_short(str(s.get('action', '')), 160)}")
        L.append(f"  - Result: {_short(str(s.get('result', '')), 160)}")
        if s.get("unsourced"):
            L.append("  - Check: this story has a metric without a source. Do not quote that number until it is sourced.")

    L += ["", "## Questions to ask them", ""]
    asks = [f"What would success look like in this {title} role after six months?",
            "What is the biggest challenge the team is working on right now?",
            "How is work reviewed and how are priorities set?",
            "What does the rest of the hiring process look like, and what is the timeline?",
            "How does the team measure the impact of its work?"]
    if any("salary" in f for f in _flags(job, posting)):
        asks.insert(3, "What salary range has been budgeted for this role?")
    L += [f"{i}. {q}" for i, q in enumerate(asks[:6], 1)]

    L += ["", "## Logistics", ""]
    dl = job.get("deadline") or getattr(posting, "deadline", "")
    L.append(f"- Application deadline: {dl[:10] if dl else 'not stated'}")
    if job.get("state"):
        L.append(f"- Queue state: {job['state']}")
    apply = job.get("apply_url") or getattr(posting, "apply_url", "")
    if apply:
        L.append(f"- Apply link: {apply}")
    if cfg.candidate.name:
        L.append(f"- Candidate: {cfg.candidate.name}")

    L += ["", "## Red flags", ""]
    flags = _flags(job, posting)
    L += [f"- {f}" for f in flags] if flags else ["None recorded."]
    return "\n".join(L).rstrip() + "\n"
