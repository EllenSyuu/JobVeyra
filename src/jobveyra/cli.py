"""jobveyra command line.

Run `jobveyra <command> --help` for details. Every command works on the workspace found by
`paths.workspace()` (JOBVEYRA_HOME, or the nearest folder with jobveyra.yml).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

from . import __version__, paths

TEMPLATES = Path(__file__).resolve().parent / "templates"


# ---------------------------------------------------------------- helpers

def _cfg():
    from . import config, queue
    cfg = config.load()
    queue.configure(cfg)
    return cfg


def _queue(cfg):
    from . import queue
    return queue.Queue(cfg.state_dir)


def _out(obj) -> None:
    if isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _today(s: str | None) -> dt.date:
    from . import queue
    return dt.date.fromisoformat(s) if s else queue.now().date()


def _eval_dir(cfg) -> Path:
    d = cfg.workspace / "reports" / "evaluations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _evaluations(cfg) -> dict[str, dict]:
    out = {}
    d = cfg.workspace / "reports" / "evaluations"
    if d.is_dir():
        for f in d.glob("*.json"):
            try:
                ev = json.loads(f.read_text(encoding="utf-8"))
                out[ev["job_id"]] = ev
            except (ValueError, KeyError):
                continue
    return out


# ---------------------------------------------------------------- setup

def cmd_init(a) -> int:
    ws = Path(a.dir).expanduser().resolve()
    paths.ensure(ws)
    cfgp = ws / paths.CONFIG_NAME
    if cfgp.exists() and not a.force:
        print(f"{cfgp} already exists (use --force to overwrite)")
    else:
        shutil.copyfile(TEMPLATES / "jobveyra.yml", cfgp)
    master = ws / "cv" / "master.md"
    if not master.exists():
        shutil.copyfile(TEMPLATES / "master.md", master)
    example_cv = ws / "cv" / "example.yml"
    if not example_cv.exists():
        shutil.copyfile(TEMPLATES / "cv.yml", example_cv)
    for name in ("AGENTS.md",):          # agent rules where Codex, OpenCode, Cursor and Gemini look
        if not (ws / name).exists():
            shutil.copyfile(TEMPLATES / name, ws / name)
    gi = ws / ".gitignore"
    if not gi.exists():
        shutil.copyfile(TEMPLATES / "gitignore", gi)
    print(f"workspace ready: {ws}\n  edit {cfgp.name} (candidate, focus, policy, sources)\n"
          f"  write your fact base in cv/master.md\n  then run: jobveyra doctor")
    return 0


def cmd_doctor(a) -> int:
    from . import config
    problems, notes = [], []
    try:
        cfg = config.load()
    except config.ConfigError as e:
        print(f"config: {e}")
        return 1
    if not cfg.candidate.name:
        problems.append("candidate.name is empty")
    if not cfg.path(cfg.candidate.master_cv).is_file():
        problems.append(f"fact base {cfg.candidate.master_cv} not found (the fabrication guard needs it)")
    if not cfg.focus.regions:
        notes.append("focus.regions is empty: every location passes")
    if not cfg.focus.tracks:
        notes.append("focus.tracks is empty: postings are not grouped into role families")
    for t in cfg.focus.tracks:
        if t.cv and not cfg.path(t.cv).is_file():
            notes.append(f"track {t.key}: CV variant {t.cv} not found")
    if not cfg.sources:
        problems.append("no sources configured")
    from .sources import base
    for s in cfg.sources:
        if s["type"] not in base.REGISTRY:
            problems.append(f"unknown source type {s['type']!r}; known: {', '.join(sorted(base.REGISTRY))}")
    from .documents import build as docbuild
    if not docbuild.find_engine(cfg.materials.engine):
        notes.append("no LaTeX engine (lualatex/xelatex): `jobveyra build` cannot make PDFs; install TeX Live or MiKTeX")
    if not shutil.which("pdftotext"):
        notes.append("Poppler (pdftotext) not found: the PDF layout check is skipped")
    try:
        import pypdf  # noqa: F401
    except ImportError:
        if not shutil.which("pdftotext"):
            notes.append("neither pypdf nor pdftotext: PDF text checks are skipped (pip install pypdf)")
    for t in cfg.focus.tracks:
        if t.cv and cfg.path(t.cv).is_file() and cfg.path(t.cv).suffix.lower() in (".yml", ".yaml"):
            from .documents.content import ContentError, load_cv
            try:
                load_cv(cfg.path(t.cv))
            except ContentError as e:
                problems.append(f"track {t.key}: {e}")
    try:
        import PIL  # noqa: F401
    except ImportError:
        notes.append("Pillow not installed: reports work, charts are skipped (pip install 'jobveyra[charts]')")
    print(f"workspace: {cfg.workspace}\npolicy: {cfg.policy.submission}, cap {cfg.policy.max_per_day}/day")
    for p in problems:
        print(f"  problem: {p}")
    for n in notes:
        print(f"  note: {n}")
    print("ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


# ---------------------------------------------------------------- discover and evaluate

def cmd_discover(a) -> int:
    from . import discover
    from .sources.http import Http
    cfg = _cfg()
    http = Http(fixtures=Path(a.offline)) if a.offline else Http()
    _out(discover.run(cfg, http, only=a.only or None))
    return 0


def cmd_evaluate(a) -> int:
    from . import discover
    from .evaluate import rubric
    cfg = _cfg()
    q = _queue(cfg)
    history = q.all()
    targets = [q.get(i) for i in a.ids] if a.ids else [j for j in history if j["state"] == "discovered" or a.all]
    done = {"eligible": 0, "excluded": 0, "missing_text": 0}
    for j in filter(None, targets):
        if j["state"] in ("submitted", "in_progress", "needs_check"):
            continue
        p = discover.load_posting(cfg.workspace, j["id"])
        if p is None:
            done["missing_text"] += 1
            continue
        ev = rubric.evaluate(p, cfg, job_id=j["id"], history=[h for h in history if h["id"] != j["id"]])
        base = _eval_dir(cfg) / discover.safe_id(j["id"])
        base.with_suffix(".json").write_text(json.dumps(ev.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        base.with_suffix(".md").write_text(rubric.report_markdown(ev, p), encoding="utf-8")
        hard = ev.blockers[0] if ev.blockers else ""
        state = q.screen(j["id"], ev.fit, reason=ev.summary[:200], hard_fail=hard)
        done[state] = done.get(state, 0) + 1
    _out(done)
    return 0


def cmd_show(a) -> int:
    from .discover import safe_id
    cfg = _cfg()
    p = _eval_dir(cfg) / (safe_id(a.id) + ".md")
    if not p.exists():
        print(f"no evaluation for {a.id}; run `jobveyra evaluate {a.id}`")
        return 1
    print(p.read_text(encoding="utf-8"))
    return 0


# ---------------------------------------------------------------- queue

def cmd_status(a) -> int:
    cfg = _cfg()
    q = _queue(cfg)
    counts = q.counts()
    if a.json:
        _out({"counts": counts, "blocked": [{k: j.get(k) for k in ("id", "state", "reason", "action")}
                                             for j in q.all() if j["state"].startswith("blocked")]})
        return 0
    print("  ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "queue is empty")
    for j in q.all():
        if j["state"].startswith("blocked") or j["state"] == "needs_check":
            print(f"{j['state']:<18} {(j.get('reason') or '')[:32]:<32} {j.get('employer')} · {j.get('title')}")
    return 0


def cmd_package(a) -> int:
    cfg = _cfg()
    q = _queue(cfg)
    _out({"id": a.id, "state": q.package_built(a.id, a.dir)})
    return 0


def cmd_check_materials(a) -> int:
    from .materials import ats, fabrication, outbound
    cfg = _cfg()
    fact_base = cfg.path(cfg.candidate.master_cv).read_text(encoding="utf-8") if cfg.path(cfg.candidate.master_cv).is_file() else ""
    if cfg.candidate.facts and cfg.path(cfg.candidate.facts).is_file():
        fact_base += "\n" + cfg.path(cfg.candidate.facts).read_text(encoding="utf-8")
    d = Path(a.dir)
    files = [f for f in d.rglob("*") if f.suffix.lower() in (".md", ".txt", ".tex", ".html")]
    report, bad = {}, 0
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        r = {"unsupported_facts": fabrication.check(text, fact_base), "self_negative": outbound.check(text),
             "ats": ats.check_text(text, a.keyword or [])}
        bad += len(r["unsupported_facts"]) + len(r["self_negative"])
        report[str(f.relative_to(d))] = r
    _out(report)
    print("PASS" if not bad else f"BLOCK: {bad} finding(s) to fix")
    return 1 if bad else 0


def cmd_tailor(a) -> int:
    from .documents import package
    cfg = _cfg()
    try:
        r = package.tailor(cfg, a.id, evaluation=_evaluations(cfg).get(a.id), lang=a.lang or "",
                           track=a.track or "", force=a.force)
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        print(e)
        return 1
    print(f"package: {r['dir']}\nlanguage: {r['lang']} ({r['why']})\ntrack: {r['track']} (base {r['base']})")
    print("edit cv.yml and letter.md (brief.md has the keywords and what to leave out), then: "
          f"jobveyra build {a.id}")
    return 0


def _print_report(report: dict) -> None:
    mark = {True: "PASS", False: "FAIL", None: "WARN"}
    for name, doc in report["documents"].items():
        print(f"{name}: {doc.get('pdf') or doc['tex']}")
        for c in doc["checks"]:
            print(f"  [{mark[c['ok']]}] {c['check']}: {c['detail']}")
    print("PASS" if report["pass"] else "BLOCK: fix the FAIL lines and build again")


def cmd_build(a) -> int:
    from .documents import package
    from .documents.content import ContentError
    cfg = _cfg()
    try:
        report = package.build(cfg, a.id, mark=not a.no_mark, queue=_queue(cfg), compile_pdf=not a.tex_only)
    except (FileNotFoundError, ContentError) as e:
        print(e)
        return 1
    _print_report(report)
    if report.get("state"):
        print(f"job state: {report['state']}")
    return 0 if report["pass"] else 1


def cmd_reviewer_prompt(a) -> int:
    from .documents import package
    cfg = _cfg()
    try:
        print(package.reviewer_prompt(cfg, a.id), end="")
    except FileNotFoundError as e:
        print(e)
        return 1
    return 0


def cmd_apply_edits(a) -> int:
    from .documents import package
    cfg = _cfg()
    raw = Path(a.file).read_text(encoding="utf-8") if a.file != "-" else sys.stdin.read()
    start, end = raw.find("["), raw.rfind("]")
    try:
        edits = json.loads(raw[start:end + 1]) if start >= 0 else []
    except ValueError as e:
        print(f"no JSON array of edits found: {e}")
        return 1
    res = package.apply_edits(cfg, a.id, edits)
    _out(res)
    print(f"{sum(1 for r in res if r.get('applied') is True and r.get('edit') is not None)}/{len(edits)} applied; "
          f"then: jobveyra build {a.id}")
    return 0


def cmd_render(a) -> int:
    """Render a CV (.yml) or letter (.md) on its own, outside any job package."""
    from .documents import build as docbuild
    from .documents import package
    from .documents.content import ContentError, load_cv, parse_letter
    from .documents.latex import render_cv, render_letter
    cfg = _cfg()
    src = Path(a.file)
    hdr = package.header_from(cfg)
    try:
        if src.suffix.lower() in (".yml", ".yaml"):
            doc = load_cv(src, hdr)
            tex, pages = render_cv(doc, paper=cfg.materials.paper, font=cfg.materials.font), cfg.materials.cv_pages
            header = doc.header
        else:
            tex = render_letter(parse_letter(src.read_text(encoding="utf-8")), hdr, paper=cfg.materials.paper,
                                font=cfg.materials.font)
            pages, header = cfg.materials.letter_pages, hdr
    except ContentError as e:
        print(e)
        return 1
    out = Path(a.out) if a.out else src.with_suffix(".tex")
    out.write_text(tex, encoding="utf-8")
    print(f"tex: {out}")
    if a.tex_only:
        return 0
    try:
        pdf = docbuild.compile_tex(out, engine=cfg.materials.engine)
    except docbuild.BuildError as e:
        print(e)
        return 1
    results, _ = docbuild.check_pdf(pdf, pages=pages, contains=[x for x in (header.email, header.phone) if x],
                                    ascii_dates=src.suffix.lower() in (".yml", ".yaml"))
    _print_report({"documents": {src.stem: {"pdf": str(pdf), "tex": str(out), "checks": results}},
                   "pass": docbuild.passed(results)})
    return 0 if docbuild.passed(results) else 1


def cmd_verify_pdf(a) -> int:
    from .documents import build as docbuild
    results, text = docbuild.check_pdf(Path(a.pdf), pages=a.pages, contains=a.contains or [],
                                       keywords=a.keyword or [], ascii_dates=not a.no_ascii_dates)
    if a.dump_text:
        Path(a.dump_text).write_text(text, encoding="utf-8")
    _print_report({"documents": {Path(a.pdf).name: {"pdf": a.pdf, "tex": "", "checks": results}},
                   "pass": docbuild.passed(results)})
    return 0 if docbuild.passed(results) else 1


def cmd_review(a) -> int:
    from . import approvals
    cfg = _cfg()
    q = _queue(cfg)
    batch = approvals.stage(q, cfg)
    if not batch:
        print("nothing waiting for review")
        return 0
    page = approvals.review_page(batch, cfg, _evaluations(cfg))
    print(f"batch {batch.id}: {len(batch.jobs)} application(s)\nreview: {page}\napprove: jobveyra approve {batch.id}")
    return 0


def cmd_approve(a) -> int:
    from . import approvals
    cfg = _cfg()
    approvals.approve(cfg.state_dir, a.batch, by=a.by or cfg.candidate.name or "candidate",
                      ttl_hours=cfg.policy.approval_ttl_hours, exclude=tuple(a.exclude or ()))
    print(f"approved {a.batch} for {cfg.policy.approval_ttl_hours} h")
    return 0


def cmd_revoke(a) -> int:
    from . import approvals
    approvals.revoke(_cfg().state_dir, a.batch)
    print(f"revoked {a.batch}")
    return 0


def cmd_next(a) -> int:
    from . import worker
    cfg = _cfg()
    job, why = worker.next_job(cfg, _queue(cfg), owner=a.owner, signed_in=tuple(a.signed_in or ()))
    _out(worker.card(cfg, job) if job else {"idle": why})
    return 0


def cmd_clicked(a) -> int:
    _queue(_cfg()).clicked(a.id)
    return 0


def cmd_done(a) -> int:
    _queue(_cfg()).mark_submitted(a.id, a.confirmation)
    print(f"submitted: {a.id}")
    return 0


def cmd_uncertain(a) -> int:
    _queue(_cfg()).mark_uncertain(a.id, a.why)
    return 0


def cmd_fail(a) -> int:
    _out({"state": _queue(_cfg()).fail(a.id, a.error, transient=not a.permanent, error_class=a.error_class or "")})
    return 0


def cmd_block(a) -> int:
    _out({"state": _queue(_cfg()).block(a.id, a.reason)})
    return 0


def cmd_unblock(a) -> int:
    _out({"unblocked": _queue(_cfg()).unblock(portal=a.portal or "", jid=a.id or "")})
    return 0


def cmd_signins(a) -> int:
    from . import signins
    cfg = _cfg()
    rows = signins.waiting(_queue(cfg))
    if a.json:
        _out(rows)
        return 0
    if not rows:
        print("no job is waiting on a sign-in")
        return 0
    for g in rows:
        due = f", earliest deadline {g['earliest_deadline']}" if g["earliest_deadline"] else ""
        print(f"{g['portal']} [{g['scope']}]: {len(g['jobs'])} waiting{due}")
        print(f"  open: {g['open']}\n  {g['hint']}")
        for j in g["jobs"][:5]:
            print(f"   - {j['employer']} · {j['title']}" + (f" (deadline {j['deadline']})" if j["deadline"] else ""))
    print("after signing in: jobveyra signed-in <scope>")
    return 0


def cmd_signed_in(a) -> int:
    from . import signins
    cfg = _cfg()
    row = signins.signal(cfg.state_dir, a.scope, source=a.source)
    print(f"recorded: signed in to {row['scope']}. An agent checks the portal, then runs "
          f"`jobveyra verify-auth {row['scope']} --ok \"<what it saw>\"` to release the jobs.")
    return 0


def cmd_wait_signin(a) -> int:
    from . import signins
    cfg = _cfg()
    p = signins.wait(cfg.state_dir, interval=a.interval, timeout=a.timeout)
    _out(p)
    return 0 if p else 2


def cmd_verify_auth(a) -> int:
    from . import signins
    cfg = _cfg()
    if bool(a.ok) == bool(a.failed):
        print("give exactly one of --ok EVIDENCE or --failed WHY")
        return 1
    _out(signins.verify(_queue(cfg), cfg.state_dir, a.scope, ok=bool(a.ok), evidence=a.ok or a.failed))
    return 0


def cmd_playbook(a) -> int:
    from . import signins
    cfg = _cfg()
    key = a.target
    job = _queue(cfg).get(key)
    if job:
        key = job.get("apply_url") or job.get("url") or ""
    print(signins.playbook(cfg.workspace, key), end="")
    return 0


def cmd_markets(a) -> int:
    from . import markets
    cfg = _cfg()
    have = markets.available(cfg.workspace)
    if a.name:
        if a.name not in have:
            print(f"unknown pack {a.name}; available: {', '.join(sorted(have))}")
            return 1
        print(have[a.name].read_text(encoding="utf-8"), end="")
        return 0
    for name, path in sorted(have.items()):
        pk = markets.load([name], cfg.workspace)[0]
        on = "*" if name in cfg.focus.markets else " "
        print(f"{on} {name:<16} {len(pk.rules):>2} rules  {pk.description}")
    print("* = active (focus.markets in jobveyra.yml)")
    return 0


def cmd_recover(a) -> int:
    _out(_queue(_cfg()).recover())
    return 0


# ---------------------------------------------------------------- outcomes, analytics, interviews

def cmd_outcome(a) -> int:
    from . import outcomes
    cfg = _cfg()
    _out(outcomes.record(cfg.state_dir, a.id, a.outcome, a.note or ""))
    return 0


def cmd_stats(a) -> int:
    from . import outcomes
    from .analytics import calibration, funnel, patterns, skills
    from .report.digest import _jobs
    cfg = _cfg()
    q = _queue(cfg)
    jobs, outs = _jobs(q), outcomes.load(cfg.state_dir)
    if a.view == "funnel":
        _out(funnel.funnel(jobs, outs))
    elif a.view == "patterns":
        _out(patterns.patterns(jobs, outs))
    elif a.view == "calibration":
        _out(calibration.calibrate(jobs, outs, exclude_below=cfg.policy.exclude_below))
    else:
        from .discover import load_posting
        texts = [p.text for j in jobs if (p := load_posting(cfg.workspace, j["id"])) and p.text]
        from .evaluate.rubric import VOCAB
        held = sorted({s for t in cfg.focus.tracks for s in t.skills})
        vocab = sorted(set(VOCAB) | set(held) | set(a.term or []))
        rows = skills.demand(texts, vocab)
        _out({"demand": rows, "gaps": skills.gaps(rows, held)})
    return 0


def cmd_prep(a) -> int:
    from .discover import load_posting
    from .interview import prep, stories
    cfg = _cfg()
    job = _queue(cfg).get(a.id)
    if not job:
        print(f"unknown job {a.id}")
        return 1
    st, problems = stories.load(cfg.workspace)
    for p in problems:
        print(f"note: {p}", file=sys.stderr)
    print(prep.prep_sheet(job, load_posting(cfg.workspace, a.id), st, cfg))
    return 0


def cmd_negotiate(a) -> int:
    from .interview import negotiation
    cfg = _cfg()
    offer = {"base": a.base, "currency": a.currency or cfg.focus.salary_currency, "bonus": a.bonus,
             "equity": a.equity or "", "location": a.location or "", "competing": a.competing or []}
    print(negotiation.script(offer, cfg))
    return 0


def cmd_followups(a) -> int:
    from . import outcomes
    from .interview import followups
    from .report.digest import _jobs
    cfg = _cfg()
    _out(followups.due(_jobs(_queue(cfg)), outcomes.load(cfg.state_dir), _today(a.today), cfg.policy.follow_up_days,
                       name=cfg.candidate.name))
    return 0


# ---------------------------------------------------------------- reports

def cmd_digest(a) -> int:
    from .report import digest, notify
    cfg = _cfg()
    dg = digest.build(cfg, _queue(cfg), _today(a.today))
    _out(dg if a.json else notify.summary(dg))
    return 0


def cmd_newsletter(a) -> int:
    from .report import newsletter
    cfg = _cfg()
    out = Path(a.out) if a.out else cfg.workspace / "reports" / "newsletter"
    if a.action == "build":
        newsletter.build(cfg, _queue(cfg), _today(a.today), out)
        print(f"built {out / 'preview.html'}")
    else:
        print(newsletter.send(out, dry_run=a.dry_run))
    return 0


def cmd_notify(a) -> int:
    from .report import digest, notify
    cfg = _cfg()
    text = a.text or notify.summary(digest.build(cfg, _queue(cfg), _today(None)))
    results = {"telegram": bool(notify.telegram(text)) if cfg.notify.telegram_enabled else "off",
               "webhook": bool(notify.webhook(text, var=cfg.notify.webhook_env))}
    _out(results)
    return 0


def cmd_status_md(a) -> int:
    from .report import chart, digest, status
    cfg = _cfg()
    dg = digest.build(cfg, _queue(cfg), _today(None))
    target = Path(a.path)
    asset_dir = Path(a.assets) if a.assets else target.parent / "assets" / "status"
    try:
        light, dark = chart.render_pair(dg["series"], asset_dir)
        rel = lambda p: Path(p).resolve().relative_to(target.parent.resolve()).as_posix()  # noqa: E731
        cl, cd = rel(light), rel(dark)
    except (ImportError, ValueError):
        cl = cd = ""
    block = status.markdown(dg, cl, cd, limit=a.limit, more_link=a.more or "")
    print("updated" if status.update_block(target, block) else "markers not found; printed instead\n" + block)
    return 0


def cmd_calendar(a) -> int:
    from .report import calendar, digest
    cfg = _cfg()
    dg = digest.build(cfg, _queue(cfg), _today(None))
    Path(a.out).write_text(calendar.ics(calendar.events_from_digest(dg)), encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


def cmd_dashboard(a) -> int:
    from .dashboard import server
    cfg = _cfg()
    return server.run(cfg, host=a.host, port=a.port, read_only=a.read_only, open_browser=not a.no_browser)


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jobveyra", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"jobveyra {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_, description=help_)
        p.set_defaults(fn=fn)
        return p

    p = add("init", cmd_init, "create a workspace with a starter config and fact base")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--force", action="store_true")
    add("doctor", cmd_doctor, "check the config, fact base, sources and optional extras")

    p = add("discover", cmd_discover, "fetch postings from the configured sources into the queue")
    p.add_argument("--only", action="append", help="source name or type (repeatable)")
    p.add_argument("--offline", help="read responses from a fixtures folder instead of the network")
    p = add("evaluate", cmd_evaluate, "score discovered postings and set their lane")
    p.add_argument("ids", nargs="*")
    p.add_argument("--all", action="store_true", help="re-evaluate every open job")
    p = add("show", cmd_show, "print the evaluation report for one job")
    p.add_argument("id")

    p = add("status", cmd_status, "counts per state and every blocker")
    p.add_argument("--json", action="store_true")
    p = add("package", cmd_package, "record the materials folder built for a job")
    p.add_argument("id")
    p.add_argument("dir")
    p = add("check-materials", cmd_check_materials, "fabrication, self-negative wording and ATS checks for a package")
    p.add_argument("dir")
    p.add_argument("--keyword", action="append", help="posting keyword to check coverage for (repeatable)")
    p = add("tailor", cmd_tailor, "start a job's package: CV copy in the right language, letter skeleton, brief")
    p.add_argument("id")
    p.add_argument("--lang", help="document language (default: chosen from the posting)")
    p.add_argument("--track", help="track key whose CV base to use (default: from the evaluation or title)")
    p.add_argument("--force", action="store_true", help="overwrite an existing package")
    p = add("build", cmd_build, "compile a job's CV and letter and run every document check")
    p.add_argument("id")
    p.add_argument("--no-mark", action="store_true", help="do not move the job to ready_to_submit on PASS")
    p.add_argument("--tex-only", action="store_true", help="write .tex and run text checks without compiling")
    p = add("reviewer-prompt", cmd_reviewer_prompt, "print a self-contained review request for a second agent")
    p.add_argument("id")
    p = add("apply-edits", cmd_apply_edits, "apply a reviewer's exact edits (JSON array) to a job's package")
    p.add_argument("id")
    p.add_argument("file", help="file with the reviewer's reply, or - for stdin")
    p = add("render", cmd_render, "render one CV (.yml) or letter (.md) to PDF and check it")
    p.add_argument("file")
    p.add_argument("--out", help="where to write the .tex (default: next to the file)")
    p.add_argument("--tex-only", action="store_true")
    p = add("verify-pdf", cmd_verify_pdf, "check any PDF as an ATS reads it: pages, text layer, layout")
    p.add_argument("pdf")
    p.add_argument("--pages", type=int, default=None)
    p.add_argument("--contains", action="append", help="text that must be in the text layer (repeatable)")
    p.add_argument("--keyword", action="append", help="posting keyword to look for (repeatable)")
    p.add_argument("--dump-text", help="write the extracted text layer here")
    p.add_argument("--no-ascii-dates", action="store_true")
    add("review", cmd_review, "stage the next batch for approval and write its review page")
    p = add("approve", cmd_approve, "approve a staged batch")
    p.add_argument("batch")
    p.add_argument("--exclude", action="append", help="job id to leave out (repeatable)")
    p.add_argument("--by", default="")
    p = add("revoke", cmd_revoke, "withdraw an approval")
    p.add_argument("batch")
    p = add("next", cmd_next, "lease the next job the policy allows and print its task card")
    p.add_argument("--owner", default="agent")
    p.add_argument("--signed-in", action="append", help="portal scope the browser is signed in to")
    for name, fn, help_ in (("clicked", cmd_clicked, "record the moment before the final Submit"),):
        add(name, fn, help_).add_argument("id")
    p = add("done", cmd_done, "record a confirmed submission")
    p.add_argument("id")
    p.add_argument("--confirmation", required=True)
    p = add("uncertain", cmd_uncertain, "no confirmation was seen: needs a manual check")
    p.add_argument("id")
    p.add_argument("--why", required=True)
    p = add("fail", cmd_fail, "record a failure (retried with backoff unless --permanent)")
    p.add_argument("id")
    p.add_argument("--error", required=True)
    p.add_argument("--permanent", action="store_true")
    p.add_argument("--error-class", default="")
    p = add("block", cmd_block, "hold a job (auth:<portal>, hold:<question>, captcha ...)")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p = add("signins", cmd_signins, "jobs waiting on a sign-in, grouped by portal, earliest deadline first")
    p.add_argument("--json", action="store_true")
    p = add("signed-in", cmd_signed_in, "record that you signed in to a portal scope (e.g. workday:acme)")
    p.add_argument("scope")
    p.add_argument("--source", default="cli")
    p = add("wait-signin", cmd_wait_signin, "wait until someone records a sign-in (for a live browser session)")
    p.add_argument("--interval", type=float, default=30)
    p.add_argument("--timeout", type=float, default=3600)
    p = add("verify-auth", cmd_verify_auth, "after checking the portal: release its jobs (--ok) or keep them (--failed)")
    p.add_argument("scope")
    p.add_argument("--ok", help="what the browser showed (e.g. the account email in the header)")
    p.add_argument("--failed", help="why the session is not signed in")
    p = add("playbook", cmd_playbook, "how to get through a portal: general rules plus the portal's own page")
    p.add_argument("target", help="job id, scope or URL")
    p = add("markets", cmd_markets, "list market packs, or print one")
    p.add_argument("name", nargs="?")
    p = add("unblock", cmd_unblock, "release blocked jobs for a portal or one job")
    p.add_argument("--portal")
    p.add_argument("--id")
    add("recover", cmd_recover, "return expired leases to the queue; always run first")

    p = add("outcome", cmd_outcome, "record an employer response")
    p.add_argument("id")
    p.add_argument("outcome", choices=["no_reply", "reply", "screen", "interview", "assessment", "offer",
                                       "rejected", "withdrawn", "hired"])
    p.add_argument("--note")
    p = add("stats", cmd_stats, "funnel, patterns, score calibration or skill demand")
    p.add_argument("view", choices=["funnel", "patterns", "calibration", "skills"])
    p.add_argument("--term", action="append", help="extra skill term for `skills`")
    p = add("prep", cmd_prep, "interview preparation sheet for a job")
    p.add_argument("id")
    p = add("negotiate", cmd_negotiate, "negotiation script for an offer")
    p.add_argument("--base", type=float, required=True)
    p.add_argument("--currency")
    p.add_argument("--bonus", type=float, default=0)
    p.add_argument("--equity")
    p.add_argument("--location")
    p.add_argument("--competing", action="append")
    p = add("followups", cmd_followups, "applications due a follow-up, with a draft message")
    p.add_argument("--today")

    p = add("digest", cmd_digest, "today's numbers")
    p.add_argument("--json", action="store_true")
    p.add_argument("--today")
    p = add("newsletter", cmd_newsletter, "build or send the email digest")
    p.add_argument("action", choices=["build", "send"])
    p.add_argument("--out")
    p.add_argument("--today")
    p.add_argument("--dry-run", action="store_true")
    p = add("notify", cmd_notify, "send a short summary to Telegram and/or a webhook")
    p.add_argument("text", nargs="?")
    p = add("status-md", cmd_status_md, "write the status block into a Markdown file between its markers")
    p.add_argument("path")
    p.add_argument("--assets")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--more")
    p = add("calendar", cmd_calendar, "deadlines and follow-ups as an .ics file")
    p.add_argument("out")
    p = add("dashboard", cmd_dashboard, "local web dashboard: overview, queue, job detail, review, insights")
    p.add_argument("--port", type=int, default=8765, help="port to listen on (default 8765; 0 picks a free one)")
    p.add_argument("--host", default=None,
                   help="address to bind (default 127.0.0.1; any other address must be given explicitly)")
    p.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    p.add_argument("--read-only", action="store_true", help="show everything, record nothing")
    return ap


def main(argv: list[str] | None = None) -> int:
    from .config import ConfigError
    for stream in (sys.stdout, sys.stderr):  # Windows consoles and pipes default to a legacy code page
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a) or 0
    except (ConfigError, KeyError, ValueError) as e:
        print(f"jobveyra: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
