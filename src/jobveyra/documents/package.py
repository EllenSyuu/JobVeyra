"""One application package per job: tailor, build, check.

``tailor(cfg, job_id)`` writes ``packages/<id>/``:

    cv.yml      a copy of the track's base CV in the chosen language, to edit for this posting
    letter.md   a letter skeleton: recipient, Re line and the writer's notes as HTML comments
    brief.md    for the writer only: the language and why, keywords to mirror, requirements the
                fact base supports, and those it does not (left out of both documents)

``build(cfg, job_id)`` renders both to LaTeX, compiles them, and runs every check:

    fabrication   each number, date, employer, degree in either document is in the fact base
    wording       nothing argues against the candidate (outbound guard)
    placeholders  no [BRACKETED] or TODO text left
    letter_words  body length inside policy (a warning, not a block)
    pages         CV and letter each fit their page limit
    text layer    clean extraction, email and phone as literal text, ASCII date ranges
    keywords      posting keywords present in the CV text layer (absent ones are reported only)
    layout        no orphaned entry, hole, early page end or footer collision

The report is written to ``packages/<id>/report.json``. With ``mark=True`` a passing build moves
the job to ``ready_to_submit`` through ``Queue.package_built``.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path

from . import build as builder
from .content import Header, LANGS, cv_variant, load_cv, parse_letter
from .latex import render_cv, render_letter

PLACEHOLDER = re.compile(r"\[[A-Z][A-Z0-9_ ]{2,}\]|\bTODO\b|\bTBD\b|\bXX+\b")


def package_dir(cfg, jid: str) -> Path:
    from ..discover import safe_id
    return cfg.workspace / "packages" / safe_id(jid)


def header_from(cfg) -> Header:
    c = cfg.candidate
    return Header(name=c.name, city=c.location, phone=c.phone, email=c.email, links=list(c.links))


def choose_language(cfg, posting) -> tuple[str, str]:
    """The document language for a posting, and the reason."""
    from ..evaluate import lang as L
    allowed = [x for x in cfg.materials.languages if x in LANGS] or ["en"]
    text = getattr(posting, "text", "") or ""
    plang = getattr(posting, "lang", "") or (L.detect(text) if text else "")
    if plang in allowed:
        return plang, f"the posting is written in {plang}"
    req = L.required_languages(text) if text else {}
    for code in allowed:
        if req.get(code, {}).get("kind") == "required":
            return code, f"the posting requires {code}"
    return allowed[0], (f"the posting is in {plang or 'an unknown language'}; "
                        f"{allowed[0]} is your first document language")


def fact_base(cfg) -> str:
    parts = []
    for rel in (cfg.candidate.master_cv, cfg.candidate.facts):
        p = cfg.path(rel) if rel else None
        if p and p.is_file():
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _track(cfg, jid: str, posting, evaluation: dict | None, key: str = ""):
    from ..evaluate.rubric import track_of
    key = key or (evaluation or {}).get("track") or ""
    for t in cfg.focus.tracks:
        if t.key == key:
            return t
    return track_of(getattr(posting, "title", "") or "", cfg.focus) if cfg.focus.tracks else None


def tailor(cfg, jid: str, *, posting=None, evaluation: dict | None = None, lang: str = "",
           track: str = "", force: bool = False) -> dict:
    from ..discover import load_posting
    from ..materials import cover
    posting = posting or load_posting(cfg.workspace, jid)
    if posting is None:
        raise FileNotFoundError(f"no cached posting for {jid}; run `jobveyra discover` first")
    if track and track not in {t.key for t in cfg.focus.tracks}:
        raise ValueError(f"unknown track {track!r}; tracks: {', '.join(t.key for t in cfg.focus.tracks)}")
    track = _track(cfg, jid, posting, evaluation, track)
    if track is None or not track.cv:
        raise FileNotFoundError("no track matches this posting's title; pass --track "
                                f"({', '.join(t.key for t in cfg.focus.tracks) or 'none configured'}) "
                                "and make sure that track has a `cv:` base")
    chosen, why = (lang, "chosen by hand") if lang else choose_language(cfg, posting)
    base = cv_variant(cfg.path(track.cv), chosen)
    if base.suffix.lower() not in (".yml", ".yaml"):
        raise ValueError(f"{base.name}: the CV base must be a YAML file (see `jobveyra init` cv/example.yml)")
    if not base.is_file():
        raise FileNotFoundError(f"CV base {base} does not exist")
    d = package_dir(cfg, jid)
    d.mkdir(parents=True, exist_ok=True)
    cv_path, letter_path, brief_path = d / "cv.yml", d / "letter.md", d / "brief.md"
    if cv_path.exists() and not force:
        raise FileExistsError(f"{d} already has a package (use --force to start over)")
    shutil.copyfile(base, cv_path)
    text = cv_path.read_text(encoding="utf-8")
    if re.search(r"^lang:", text, re.M):
        text = re.sub(r"^lang:.*$", f"lang: {chosen}", text, count=1, flags=re.M)
    else:
        text = f"lang: {chosen}\n" + text
    cv_path.write_text(text, encoding="utf-8")

    a = cover.angles(posting, cfg)
    re_line = posting.title + (f" ({posting.req_id})" if posting.req_id else "")
    recipient = [x for x in ("Hiring Team" if chosen == "en" else "", posting.employer,
                             (posting.location or "").split(";")[0]) if x]
    notes = ["Notes for you; comments never reach the PDF.",
             f"Tone: {a.get('tone', 'neutral')}. Keep it to about {cfg.materials.letter_words[0]}-"
             f"{cfg.materials.letter_words[1]} words in 3-4 paragraphs."]
    if a.get("why_company"):
        notes.append("Why this employer, quoted from the posting: " + " | ".join(a["why_company"][:2]))
    for item in a.get("approach", [])[:4]:
        notes.append(f"Evidence for '{item['requirement'][:90]}': {item['evidence']} ({item['source']})")
    body = "\n".join(f"<!-- {n} -->" for n in notes)
    letter_path.write_text(
        "---\n"
        f"lang: {chosen}\n"
        f"recipient: {json.dumps(recipient, ensure_ascii=False)}\n"
        f"re: {json.dumps(re_line, ensure_ascii=False)}\n"
        "---\n" + body + "\n\n[WHY THIS ROLE AND EMPLOYER]\n\n[TWO PIECES OF EVIDENCE]\n\n[CLOSE]\n",
        encoding="utf-8")
    kw = a.get("keywords", [])[:15]
    brief = [f"# {posting.employer} - {posting.title}", "",
             f"- Job id: `{jid}`", f"- Track: {track.label} (base {base.name})",
             f"- Document language: **{chosen}** ({why})", f"- Posting: {posting.url}", "",
             "## Keywords to mirror where your fact base supports them", "",
             ", ".join(kw) or "(none found)", "",
             "## Requirements you can evidence", ""]
    brief += [f"- {x['requirement']} -> {x['evidence']}" for x in a.get("approach", [])] or ["- (none matched)"]
    brief += ["", "## Not shown by your fact base", "",
              "Leave these out of the CV and the letter. A skill that is not written down is unknown, "
              "not absent; if you do have it, add it to your fact base first.", ""]
    brief += [f"- {g}" for g in a.get("gaps", [])] or ["- (none)"]
    brief_path.write_text("\n".join(brief) + "\n", encoding="utf-8")
    (d / "keywords.json").write_text(json.dumps(kw, ensure_ascii=False), encoding="utf-8")
    return {"dir": str(d), "lang": chosen, "why": why, "track": track.key, "base": str(base),
            "files": [str(cv_path), str(letter_path), str(brief_path)]}


def _guards(text: str, facts: str, kind: str) -> list[dict]:
    from ..materials import fabrication, outbound
    out = []
    bad = fabrication.check(text, facts) if facts else []
    out.append(builder._r("fabrication", not bad if facts else None,
                          ("not in your fact base: " + ", ".join(bad)) if bad
                          else ("every fact found in the fact base" if facts else "skipped: no fact base")))
    neg = outbound.check(text, kind=kind)
    out.append(builder._r("wording", not neg, ("argues against you: " + "; ".join(neg)) if neg else "clean"))
    ph = sorted(set(PLACEHOLDER.findall(text)))
    out.append(builder._r("placeholders", not ph, ", ".join(ph) or "none left"))
    return out


def build(cfg, jid: str, *, today: dt.date | None = None, mark: bool = False, queue=None,
          compile_pdf: bool = True) -> dict:
    d = package_dir(cfg, jid)
    cv_path, letter_path = d / "cv.yml", d / "letter.md"
    if not cv_path.is_file():
        raise FileNotFoundError(f"no package for {jid}; run `jobveyra tailor {jid}` first")
    m = cfg.materials
    facts = fact_base(cfg)
    hdr = header_from(cfg)
    kw = json.loads((d / "keywords.json").read_text(encoding="utf-8")) if (d / "keywords.json").is_file() else []
    report: dict = {"job_id": jid, "dir": str(d), "documents": {}}

    cv = load_cv(cv_path, hdr)
    docs = [("cv", cv.text(), render_cv(cv, paper=m.paper, font=m.font), m.cv_pages, "cv")]
    if letter_path.is_file():
        letter = parse_letter(letter_path.read_text(encoding="utf-8"))
        docs.append(("letter", letter.body_text(), render_letter(letter, cv.header, paper=m.paper, today=today, font=m.font),
                     m.letter_pages, "letter"))
    for name, plain, tex, pages, kind in docs:
        res = _guards(plain, facts, kind)
        if name == "letter":
            lo, hi = m.letter_words
            n = letter.words()
            res.append(builder._r("letter_words", True if lo <= n <= hi else None, f"{n} words (aim {lo}-{hi})"))
        tex_path = d / f"{name}.tex"
        tex_path.write_text(tex, encoding="utf-8")
        entry = {"tex": str(tex_path), "checks": res}
        if compile_pdf:
            try:
                pdf = builder.compile_tex(tex_path, engine=m.engine)
                contains = [x for x in (cv.header.email, cv.header.phone) if x]
                pres, text = builder.check_pdf(pdf, pages=pages, contains=contains,
                                               keywords=kw if name == "cv" else [], ascii_dates=name == "cv")
                res += pres
                (d / f"{name}.txt").write_text(text, encoding="utf-8")
                entry["pdf"] = str(pdf)
            except builder.BuildError as e:
                res.append(builder._r("compile", False, str(e)))
        report["documents"][name] = entry
    allc = [c for e in report["documents"].values() for c in e["checks"]]
    report["pass"] = builder.passed(allc)
    report["warnings"] = [f"{c['check']}: {c['detail']}" for c in allc if c["ok"] is None]
    (d / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if mark and report["pass"] and queue is not None and queue.get(jid):
        report["state"] = queue.package_built(jid, str(d))
    return report
