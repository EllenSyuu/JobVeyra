"""Persistent job queue: the single source of truth for every posting from discovery to confirmation.

Every job is an explicit row in a state machine with a unique identity, transactional updates
and a durable, diffable text snapshot. A fit score is never evidence of submission: only
``mark_submitted(..., confirmation=...)`` moves a job to ``submitted``.

Storage (in the workspace ``state/`` folder)
  queue.jsonl    canonical snapshot, one job per line sorted by id
  events.jsonl   append-only transition log (who, when, why)
  A process works on an in-memory SQLite copy; every transaction ends by writing the snapshot
  atomically (temp file + rename), so a killed process loses at most the transition it was in.

States
  discovered        found, not screened yet
  excluded          screened out; ``reason`` says why (kept, so nothing is silently lost)
  eligible          passes the gates and the fit threshold; no package or no submit path yet
  ready_to_submit   package built and a submit path exists
  in_progress       claimed under a lease; ``clicked`` = the final submit was pressed
  submitted         confirmation text captured (required to enter this state); terminal
  needs_check       uncertain result; never resubmitted automatically
  retry_wait        transient failure; ``next_attempt_at`` says when it is retried
  blocked_auth      the portal wants a sign-in; ``auth_scope`` names the exact session
  blocked_human     needs the candidate's answer or approval
  blocked_technical CAPTCHA, unsupported form, upload failure, retries exhausted
Every blocked_* row carries ``reason`` (machine code), ``action`` (what unblocks it, in plain
words) and ``last_attempt_at``.

Concurrency: every transaction takes an exclusive file lock and reloads the snapshot first, so
two processes never claim the same job or overwrite each other's writes.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import random
import re
import sqlite3
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import paths

STATE_DIR = Path(os.environ["JOBQUEUE_DIR"]) if os.environ.get("JOBQUEUE_DIR") else None

BLOCKED = ("blocked_auth", "blocked_human", "blocked_technical")
STATES = ("discovered", "excluded", "eligible", "ready_to_submit", "in_progress", "retry_wait",
          "submitted", "needs_check") + BLOCKED + ("blocked",)
OPEN = ("discovered", "eligible", "ready_to_submit", "in_progress", "retry_wait", "needs_check") + BLOCKED
_UNBLOCK = {"eligible", "ready_to_submit", "excluded", "needs_check", "submitted"}
TRANSITIONS = {
    "discovered": {"excluded", "eligible", *BLOCKED},
    "excluded": {"eligible"},                                   # a person may overrule
    "eligible": {"ready_to_submit", "excluded", "submitted", *BLOCKED},
    "ready_to_submit": {"in_progress", "excluded", "eligible", "submitted", *BLOCKED},
    "in_progress": {"submitted", "needs_check", "ready_to_submit", "retry_wait", "excluded", *BLOCKED},
    "retry_wait": {"ready_to_submit", "excluded", "submitted", *BLOCKED},
    "needs_check": {"submitted", "ready_to_submit", "excluded", *BLOCKED},
    "blocked_auth": _UNBLOCK | {"blocked_technical", "blocked_human"},
    "blocked_human": _UNBLOCK | {"blocked_auth", "blocked_technical"},
    "blocked_technical": _UNBLOCK | {"blocked_auth", "blocked_human"},
    "blocked": _UNBLOCK | set(BLOCKED),                         # legacy -> migrate_states()
    "submitted": set(),                                         # terminal: never resubmit
}
FIELDS = ["id", "employer", "employer_key", "req_id", "title", "url", "apply_url", "source", "location",
          "posted", "deadline", "lang", "family", "flagship", "state", "lane", "fit", "fit_key", "reason",
          "portal", "package", "attempts", "next_attempt_at", "lease_until", "clicked", "last_error",
          "confirmation", "tracker_row", "content_hash", "created_at", "updated_at",
          "auth_scope", "action", "last_attempt_at", "error_class", "lease_owner"]
LEASE_MIN = 30
MAX_ATTEMPTS = 4                     # legacy default; per-class limits below
BACKOFF_BASE_MIN = 15
BACKOFF_CAP_MIN = 24 * 60
JITTER = 0.2                         # +-20 % so retries of one portal do not fire in lockstep
# error class -> max attempts before blocked_technical. 0 = never retried (needs a human/tech fix).
RETRY_LIMITS = {"network": 5, "timeout": 4, "portal_error": 3, "browser": 3, "transient": 4,
                "captcha": 0, "unsupported_form": 0, "upload": 2, "closed": 0}
ACTIONS = {
    "auth": "Sign in to {scope} in your browser, then run `jobveyra unblock --portal {scope}`",
    "captcha": "The page asks for a human check: submit it yourself, then record it with `jobveyra done`",
    "unsupported_form": "This form cannot be filled automatically: submit it yourself or skip it",
    "upload": "The CV upload failed: check the posting is still open; it will be retried",
    "retries_exhausted": "Several attempts failed: open the link to see whether it closed, or skip it",
    "hold": "Answer the pending question, then the job continues",
    "approve": "Approve the batch with `jobveyra approve`",
    "closed": "The posting may be closed: confirm and skip it",
}
FAST_MIN, FULL_MIN = 45, 70
FULL_LANE_DAILY_CAP = 3

# Set from the user's config (focus.flagship_employers, policy thresholds) by `configure()`.
FLAGSHIP: tuple[str, ...] = ()
# Login / account portals: a package for these is only useful once the candidate is signed in.
LOGIN_PORTALS = ("workday", "myworkdayjobs", "taleo", "successfactors", "icims", "oracle",
                 "brassring", "phenom", "eightfold", "inspira", "careers.un.org")
NO_LOGIN_PORTALS = ("lever.co", "greenhouse.io", "workable.com", "smartrecruiters.com", "jazzhr", "ashbyhq",
                    "recruitee", "bamboohr", "indeed.com")


def configure(cfg) -> None:
    """Apply a jobveyra Config: flagship employers and fit thresholds."""
    global FLAGSHIP, FAST_MIN, FULL_MIN
    FLAGSHIP = tuple(cfg.focus.flagship_employers)
    FAST_MIN, FULL_MIN = cfg.policy.exclude_below, cfg.policy.full_package_at


def now() -> dt.datetime:
    fixed = os.environ.get("JOBQUEUE_NOW")
    return dt.datetime.fromisoformat(fixed) if fixed else dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def iso(t: dt.datetime | None) -> str:
    return t.isoformat(timespec="seconds") if t else ""


# ---------------------------------------------------------------- identity

def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def employer_key(name: str) -> str:
    s = fold(name)
    s = re.sub(r"\b(inc|ltd|limited|llc|corp|corporation|company|co|group|groupe|the|of|du|de|la|le)\b", " ", s)
    return re.sub(r"\s+", "-", s.strip())[:40] or "unknown"


REQ_PATTERNS = [
    (r"jobs\.lever\.co/[^/]+/([0-9a-f-]{36})", "lever"),
    (r"greenhouse\.io/.*?/jobs/(\d+)", "greenhouse"),
    (r"[?&]gh_jid=(\d+)", "greenhouse"),
    (r"workable\.com/(?:[^/]+/)?j/([0-9A-F]{8,12})", "workable"),
    (r"jobs\.workable\.com/view/([0-9a-f-]{36}|[A-Za-z0-9]{18,})", "workable"),
    (r"smartrecruiters\.com/[^/]+/(\d{6,})", "smartrecruiters"),
    (r"myworkdayjobs\.com/.*?_((?:R|JR|REQ)?-?\d{4,}[A-Z0-9-]*)", "workday"),
    (r"linkedin\.com/jobs/view/(?:[^/]*?-)?(\d{6,})", "linkedin"),
    (r"[?&]jk=([0-9a-f]{16})", "indeed"),
    (r"[?&](?:jobId|jobid|job_id|reqId|requisitionId|JobOpeningId)=([A-Za-z0-9_-]{3,})", "query"),
]


def req_from(url: str, title: str = "") -> str:
    for rx, kind in REQ_PATTERNS:
        m = re.search(rx, url or "", re.I)
        if m:
            return f"{kind}:{m.group(1).lower()}"
    m = re.search(r"\((?:ref|req|job|id)?\s*#?\s*([A-Z]{0,4}-?\d{4,})\)", title or "", re.I)
    if m:
        return f"ref:{m.group(1).lower()}"
    m = re.search(r"\b(\d{6,})\b", title or "")
    return f"ref:{m.group(1)}" if m else ""


def job_id(employer: str, title: str = "", url: str = "", req_id: str = "", location: str = "") -> str:
    """Employer + requisition ID when known; otherwise a hash of the normalised posting. Two
    requisitions with the same title at the same employer always get different ids."""
    ek = employer_key(employer)
    rid = req_id or req_from(url, title)
    if rid:
        return f"{ek}:{rid}"
    base = "|".join([fold(title), fold(location), re.sub(r"[?#].*$", "", (url or "").lower())])
    return f"{ek}:h{hashlib.sha1(base.encode()).hexdigest()[:12]}"


def content_hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text or "").strip().encode()).hexdigest()[:16]


def is_flagship(employer: str) -> bool:
    e = " " + fold(employer) + " "
    return any((" " + fold(f) + " ") in e for f in FLAGSHIP)


def portal_of(url: str) -> str:
    u = (url or "").lower()
    for p in LOGIN_PORTALS + NO_LOGIN_PORTALS:
        if p in u:
            return p.split(".")[0]
    host = urlparse(u).netloc
    return host.replace("www.", "") or "unknown"


def needs_login(url: str) -> bool:
    u = (url or "").lower()
    return any(p in u for p in LOGIN_PORTALS)


def auth_scope_of(url: str) -> str:
    """The sign-in session a URL depends on. Workday sessions are per tenant (acme.wd3... and
    globex.wd10... are different logins), so the tenant is part of the scope."""
    host = urlparse((url or "").lower()).netloc.replace("www.", "")
    m = re.match(r"([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com$", host)
    if m:
        return f"workday:{m.group(1)}"
    m = re.match(r"([a-z0-9-]+)\.(taleo\.net|icims\.com|successfactors\.\w+)$", host)
    if m:
        return f"{m.group(2).split('.')[0]}:{m.group(1)}"
    return host or "unknown"


# ---------------------------------------------------------------- lanes (no gaps)

def lane(score: float | None, flagship: bool) -> str:
    """Every score lands in exactly one bucket: below FAST_MIN excluded; flagship at FULL_MIN or more
    gets the full package; everything else the fast package."""
    if score is None:
        return "unscored"
    if score < FAST_MIN:
        return "excluded"
    if flagship and score >= FULL_MIN:
        return "full"
    return "fast"


# ---------------------------------------------------------------- store

def classify_block(reason: str) -> str:
    """Structured blocker code -> blocked_* state. Unknown codes are technical (visible, never retried)."""
    r = (reason or "").lower()
    if r.startswith(("auth:", "login", "session")):
        return "blocked_auth"
    if r.startswith(("hold:", "human:", "approve", "question")):
        return "blocked_human"
    return "blocked_technical"


def action_for(reason: str, scope: str = "") -> str:
    code = (reason or "").split(":")[0].lower()
    if classify_block(reason) == "blocked_auth":
        code = "auth"
    if code in ("max_attempts", "retries_exhausted"):
        code = "retries_exhausted"
    return ACTIONS.get(code, "Open the link to see where it stopped, then unblock or skip it").format(scope=scope or "the portal")


def backoff_minutes(attempt: int, seed: str = "") -> int:
    """Exponential backoff with +-JITTER; deterministic per (job, attempt) so tests and restarts agree."""
    base = min(BACKOFF_BASE_MIN * 2 ** max(attempt - 1, 0), BACKOFF_CAP_MIN)
    rnd = random.Random(f"{seed}:{attempt}").uniform(-JITTER, JITTER)
    return max(1, int(round(base * (1 + rnd))))


class Queue:
    def __init__(self, state_dir: Path | str | None = None):
        self.dir = Path(state_dir or STATE_DIR or paths.state_dir())
        self.dir.mkdir(parents=True, exist_ok=True)
        self.snap = self.dir / "queue.jsonl"
        self.log = self.dir / "events.jsonl"
        self.lockfile = self.dir / ".queue.lock"
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        cols = ", ".join(f"{f} TEXT" if f not in ("fit", "attempts", "clicked", "flagship") else f"{f} REAL"
                         for f in FIELDS if f != "id")
        self.db.execute(f"CREATE TABLE jobs (id TEXT PRIMARY KEY, {cols})")
        self._loaded_sig = None
        self._load()

    def close(self) -> None:
        """Release the in-memory database (the snapshot on disk is always current)."""
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # snapshot I/O --------------------------------------------------
    def _sig(self):
        try:
            st = self.snap.stat()
            return (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            return None

    def _load(self) -> None:
        self.db.execute("DELETE FROM jobs")
        self._loaded_sig = self._sig()
        if not self.snap.exists():
            return
        rows = []
        for line in self.snap.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                rows.append(tuple(d.get(f) for f in FIELDS))
        self.db.executemany(f"INSERT INTO jobs ({','.join(FIELDS)}) VALUES ({','.join('?' * len(FIELDS))})", rows)

    def refresh(self) -> None:
        """Pick up writes made by another process since this one loaded."""
        if self._sig() != self._loaded_sig:
            self._load()

    def _checkpoint(self) -> None:
        cur = self.db.execute(f"SELECT {','.join(FIELDS)} FROM jobs ORDER BY id")
        lines = [json.dumps({k: v for k, v in zip(FIELDS, r) if v not in (None, "")}, ensure_ascii=False,
                            sort_keys=True) for r in cur]
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".queue.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.snap)
        self._loaded_sig = self._sig()

    def _event(self, jid: str, frm: str, to: str, note: str = "") -> None:
        with self.log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": iso(now()), "id": jid, "from": frm, "to": to, "note": note},
                                ensure_ascii=False) + "\n")

    @contextlib.contextmanager
    def tx(self):
        """One transaction = exclusive file lock + reload + apply + checkpoint. Rolled back (and
        nothing written) on any exception. The lock makes claim() atomic across processes."""
        with self.lockfile.open("a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                self.refresh()
                self.db.execute("BEGIN IMMEDIATE")
                try:
                    yield self.db
                    self.db.execute("COMMIT")
                except BaseException:
                    self.db.execute("ROLLBACK")
                    raise
                self._checkpoint()
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    # reads ---------------------------------------------------------
    def get(self, jid: str) -> dict | None:
        self.refresh()
        r = self.db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(r) if r else None

    def all(self, state: str | None = None) -> list[dict]:
        self.refresh()
        q = "SELECT * FROM jobs" + (" WHERE state=?" if state else "") + " ORDER BY id"
        return [dict(r) for r in self.db.execute(q, (state,) if state else ())]

    def counts(self) -> dict:
        self.refresh()
        return {r[0]: int(r[1]) for r in self.db.execute("SELECT state, COUNT(*) FROM jobs GROUP BY state")}

    def scope(self, j: dict) -> str:
        return j.get("auth_scope") or auth_scope_of(j.get("apply_url") or j.get("url") or "")

    # writes --------------------------------------------------------
    def _set(self, db, jid: str, to: str, note: str = "", **fields) -> None:
        cur = db.execute("SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()
        if cur is None:
            raise KeyError(jid)
        frm = cur[0]
        if to != frm and to not in TRANSITIONS[frm]:
            raise ValueError(f"illegal transition {frm} -> {to} for {jid}")
        fields.update(state=to, updated_at=iso(now()))
        if to not in BLOCKED and to != "blocked" and "action" not in fields:
            fields["action"] = ""
        db.execute(f"UPDATE jobs SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), jid))
        if to != frm:
            self._event(jid, frm, to, note)

    def _row(self, db, jid: str) -> dict:
        r = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if r is None:
            raise KeyError(jid)
        return dict(r)

    def upsert(self, job: dict) -> tuple[str, bool]:
        """Add a discovered posting. Idempotent on id: an existing job keeps its state; only empty
        metadata is filled and a changed posting text updates content_hash (re-screen if not yet decided)."""
        jid = job.get("id") or job_id(job.get("employer", ""), job.get("title", ""), job.get("url", ""),
                                      job.get("req_id", ""), job.get("location", ""))
        with self.tx() as db:
            old = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
            if old:
                old = dict(old)
                upd = {k: v for k, v in job.items() if k in FIELDS and k not in ("id", "state") and v not in (None, "")
                       and (old.get(k) in (None, "") or (k == "content_hash" and v != old.get(k)))}
                if upd.get("content_hash") and old["state"] in ("discovered", "eligible") and old.get("content_hash"):
                    upd["fit_key"] = ""            # changed text: the cached fit no longer applies
                if upd:
                    upd["updated_at"] = iso(now())
                    db.execute(f"UPDATE jobs SET {', '.join(f'{k}=?' for k in upd)} WHERE id=?", (*upd.values(), jid))
                return jid, False
            row = {f: job.get(f) for f in FIELDS if f in job}
            row.update(id=jid, employer_key=employer_key(job.get("employer", "")), state=job.get("state", "discovered"),
                       attempts=0, clicked=0, flagship=1 if is_flagship(job.get("employer", "")) else 0,
                       portal=job.get("portal") or portal_of(job.get("apply_url") or job.get("url", "")),
                       created_at=iso(now()), updated_at=iso(now()))
            row.setdefault("auth_scope", auth_scope_of(job.get("apply_url") or job.get("url", "")))
            db.execute(f"INSERT INTO jobs ({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
            self._event(jid, "", row["state"], job.get("source", ""))
            return jid, True

    def update_meta(self, jid: str, **fields) -> None:
        """Non-state metadata (apply_url, auth_scope, package, deadline...)."""
        bad = set(fields) - set(FIELDS) | ({"state"} & set(fields))
        if bad:
            raise ValueError(f"not metadata: {bad}")
        with self.tx() as db:
            self._row(db, jid)
            fields["updated_at"] = iso(now())
            db.execute(f"UPDATE jobs SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), jid))

    def screen(self, jid: str, fit: float | None, *, reason: str = "", hard_fail: str = "", fit_key: str = "") -> str:
        """Record the screening result. Hard gate failures and fit < 45 -> excluded WITH a reason."""
        j = self.get(jid)
        with self.tx() as db:
            if hard_fail:
                self._set(db, jid, "excluded", hard_fail, reason=hard_fail, fit=fit, fit_key=fit_key)
                return "excluded"
            ln = lane(fit, bool(j["flagship"]))
            if ln == "excluded":
                self._set(db, jid, "excluded", f"fit {fit}", reason=f"low_fit:{fit}", fit=fit, lane="", fit_key=fit_key)
                return "excluded"
            if ln == "unscored":
                raise ValueError("screen() needs a fit score or a hard_fail reason")
            self._set(db, jid, "eligible", reason or f"fit {fit}", fit=fit, lane=ln, reason=reason, fit_key=fit_key)
            return "eligible"

    def open_auth_scopes(self) -> set[str]:
        """Sessions known to be signed out right now (an unresolved blocked_auth row exists)."""
        return {self.scope(j) for j in self.all("blocked_auth")}

    def package_built(self, jid: str, package: str, *, browser_ok: bool = True, signed_in: tuple[str, ...] = (),
                      cv_uploadable: bool = True) -> str:
        """A package makes the job ready_to_submit. Whether THIS environment has a browser is a
        property of the executor, not of the job, so `browser_ok` no longer blocks anything. The job
        goes straight to the holding pen only when its sign-in session is already known to be
        signed out (another job on the same scope is blocked_auth), so nobody re-discovers it."""
        j = self.get(jid)
        url = j.get("apply_url") or j.get("url") or ""
        scope = self.scope(j)
        with self.tx() as db:
            if not url:
                self._set(db, jid, "blocked_technical", "no_apply_url", package=package, reason="no_apply_url",
                          action="No application link found: add one or skip the job")
                return "blocked_technical"
            if scope in self.open_auth_scopes() and scope not in signed_in:
                self._set(db, jid, "blocked_auth", f"auth:{scope}", package=package, reason=f"auth:{scope}",
                          auth_scope=scope, action=action_for("auth:", scope))
                return "blocked_auth"
            if not cv_uploadable and not any(p in url.lower() for p in ("indeed.com", "linkedin.com", "myworkdayjobs")):
                self._set(db, jid, "blocked_technical", "upload", package=package, reason="upload",
                          action=action_for("upload"))
                return "blocked_technical"
            self._set(db, jid, "ready_to_submit", "package", package=package, reason="", auth_scope=scope)
            return "ready_to_submit"

    def promote_due(self) -> list[str]:
        """retry_wait rows whose backoff elapsed -> ready_to_submit. Survives restarts (time is in the row)."""
        t = iso(now())
        due = [j["id"] for j in self.all("retry_wait") if (j.get("next_attempt_at") or "") <= t]
        if due:
            with self.tx() as db:
                for jid in due:
                    self._set(db, jid, "ready_to_submit", "backoff elapsed")
        return due

    def runnable(self, *, signed_in_ok: bool = True) -> list[dict]:
        """Jobs an executor with a browser could act on now (ready, backoff elapsed)."""
        t = iso(now())
        return [j for j in self.all("ready_to_submit") if not j.get("next_attempt_at") or j["next_attempt_at"] <= t]

    def claim(self, *, browser_ok: bool = True, signed_in: tuple[str, ...] = (), limit_portals: tuple[str, ...] = (),
              owner: str = "", accept=None) -> dict | None:
        """Atomically lease the highest-priority ready job. Selection and lease happen inside one
        locked transaction, so two workers can never get the same job. Without a browser nothing
        is claimed (and nothing is blocked): the executor reports a hand-off instead of idle.
        `accept(job) -> bool` narrows the candidates (the approval gate uses it)."""
        if not browser_ok:
            return None
        self.promote_due()
        t = now()
        with self.tx() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM jobs WHERE state='ready_to_submit'")]
            cands = [j for j in rows if (not j.get("next_attempt_at") or j["next_attempt_at"] <= iso(t))
                     and (not limit_portals or j.get("portal") in limit_portals)
                     and (accept is None or accept(j))]
            if not cands:
                return None
            j = sorted(cands, key=lambda x: priority(x, t))[0]
            self._set(db, j["id"], "in_progress", "claim", lease_until=iso(t + dt.timedelta(minutes=LEASE_MIN)),
                      clicked=0, last_attempt_at=iso(t), lease_owner=owner)
        return self.get(j["id"])

    def clicked(self, jid: str) -> None:
        """Call immediately BEFORE pressing the final submit button: from here on a crash means 'uncertain'."""
        with self.tx() as db:
            n = db.execute("UPDATE jobs SET clicked=1, updated_at=? WHERE id=? AND state='in_progress'",
                           (iso(now()), jid)).rowcount
            if not n:
                raise ValueError(f"clicked() needs an in_progress lease on {jid} (claim it first)")

    def mark_submitted(self, jid: str, confirmation: str) -> None:
        if not (confirmation or "").strip():
            raise ValueError("submitted needs the portal's confirmation text (or use mark_uncertain)")
        with self.tx() as db:
            if self._row(db, jid)["state"] == "submitted":
                return                                          # idempotent: never a second record
            self._set(db, jid, "submitted", confirmation[:200], confirmation=confirmation[:500], lease_until="",
                      last_error="", reason="", next_attempt_at="")

    def mark_uncertain(self, jid: str, why: str) -> None:
        with self.tx() as db:
            self._set(db, jid, "needs_check", why, reason=f"uncertain:{why}", lease_until="",
                      action="Check the portal's My Applications page for this job before deciding to resubmit")

    def fail(self, jid: str, error: str, *, transient: bool = True, error_class: str = "") -> str:
        """A failed attempt BEFORE the submit click. Retryable classes -> retry_wait with jittered
        exponential backoff; when the class limit is reached -> blocked_technical (visible, with an
        action) — never silently dropped. Non-retryable classes go straight to blocked_technical."""
        j = self.get(jid)
        if j["state"] == "in_progress" and int(j.get("clicked") or 0):
            self.mark_uncertain(jid, f"error after submit click: {error}")
            return "needs_check"
        cls = error_class or ("transient" if transient else "unsupported_form")
        limit = RETRY_LIMITS.get(cls, MAX_ATTEMPTS)
        attempts = int(j.get("attempts") or 0) + 1
        with self.tx() as db:
            if limit == 0 or attempts >= limit:
                code = cls if limit == 0 else f"retries_exhausted:{cls}"
                self._set(db, jid, "blocked_technical", error, attempts=attempts, last_error=error[:300],
                          reason=code, error_class=cls, lease_until="", action=action_for(code))
                return "blocked_technical"
            wait = backoff_minutes(attempts, jid)
            self._set(db, jid, "retry_wait", f"retry in {wait} min", attempts=attempts, last_error=error[:300],
                      error_class=cls, next_attempt_at=iso(now() + dt.timedelta(minutes=wait)), lease_until="")
            return "retry_wait"

    def block(self, jid: str, reason: str, *, action: str = "") -> str:
        """Durable blocker with a structured code. auth:* -> blocked_auth (+ every other unfinished
        job on the same sign-in scope), hold:* -> blocked_human, anything else -> blocked_technical."""
        j = self.get(jid)
        if j["state"] == "in_progress" and int(j.get("clicked") or 0):
            self.mark_uncertain(jid, f"blocked after submit click: {reason}")
            return "needs_check"
        to = classify_block(reason)
        if to == "blocked_auth":
            scope = reason.split(":", 1)[1] if ":" in reason and reason.split(":", 1)[1] else self.scope(j)
            self.update_meta(jid, auth_scope=scope)
            self.block_portal(scope, f"auth:{scope}", include=(jid,))
            return to
        with self.tx() as db:
            self._set(db, jid, to, reason, reason=reason, lease_until="", last_attempt_at=iso(now()),
                      action=action or action_for(reason, self.scope(j)))
        return to

    def block_portal(self, scope: str, reason: str = "", include: tuple[str, ...] = ()) -> list[str]:
        """A sign-in wall on one session: EVERY unfinished job on that scope (eligible, ready,
        retry_wait, unclicked in_progress) goes to the holding pen at once; other portals continue.
        Accepts a legacy portal name too (matches `portal` when no job has that auth_scope)."""
        reason = reason or f"auth:{scope}"
        movable = ("discovered", "eligible", "ready_to_submit", "retry_wait", "in_progress", "blocked_technical", "blocked")
        rows = self.all()
        by_scope = [j for j in rows if self.scope(j) == scope]
        pool = by_scope or [j for j in rows if j.get("portal") == scope]
        hit = [j["id"] for j in pool if (j["state"] in movable and not (j["state"] == "in_progress" and int(j.get("clicked") or 0))
                                          and not (j["state"] == "blocked_technical" and j["id"] not in include))
               or j["id"] in include]
        hit = [h for h in dict.fromkeys(hit) if self.get(h)["state"] not in ("submitted", "excluded", "needs_check")]
        with self.tx() as db:
            for jid in hit:
                if self._row(db, jid)["state"] == "blocked_auth":
                    continue
                self._set(db, jid, "blocked_auth", reason, reason=reason, auth_scope=scope, lease_until="",
                          last_attempt_at=iso(now()), action=action_for(reason, scope))
        return hit

    def release_auth(self, scope: str, evidence: str) -> list[str]:
        """Release the holding pen for ONE verified session. `evidence` must describe what the
        executor saw in the browser (e.g. 'candidate home shows the signed-in account'): a tick on a
        board alone is not proof of a valid session."""
        if not (evidence or "").strip():
            raise ValueError("release_auth needs browser evidence that the session is signed in")
        hit = [j for j in self.all("blocked_auth") if self.scope(j) == scope]
        with self.tx() as db:
            for j in hit:
                to = "ready_to_submit" if j.get("package") or j.get("apply_url") else "eligible"
                self._set(db, j["id"], to, f"auth verified: {evidence[:80]}", reason="", next_attempt_at="")
        return [j["id"] for j in hit]

    def unblock(self, *, portal: str = "", reason_prefix: str = "", jid: str = "") -> list[str]:
        """Human override (the candidate fixed it or answered). Never touches needs_check or submitted."""
        hit = [j for j in self.all() if j["state"] in BLOCKED + ("blocked",)
               and (not jid or j["id"] == jid)
               and (not portal or j.get("portal") == portal or self.scope(j) == portal)
               and (not reason_prefix or (j.get("reason") or "").startswith(reason_prefix))]
        with self.tx() as db:
            for j in hit:
                to = "ready_to_submit" if j.get("package") or j.get("apply_url") else "eligible"
                self._set(db, j["id"], to, "unblocked", reason="", next_attempt_at="", attempts=0)
        return [j["id"] for j in hit]

    def recover(self) -> dict:
        """After a crash or a stall: expired leases go back to the queue if the submit button was never
        pressed, or to needs_check if it was (never auto-resubmit an uncertain application).
        Also promotes elapsed retries, so a restart resumes exactly where the schedule left off."""
        t = iso(now())
        out = {"requeued": [], "uncertain": [], "retry_due": self.promote_due()}
        stale = [j for j in self.all("in_progress") if (j.get("lease_until") or "") <= t]
        with self.tx() as db:
            for j in stale:
                if int(j.get("clicked") or 0):
                    self._set(db, j["id"], "needs_check", "lease expired after submit click",
                              reason="uncertain:interrupted_after_click", lease_until="",
                              action="Check the portal's My Applications page for this job before deciding to resubmit")
                    out["uncertain"].append(j["id"])
                else:
                    self._set(db, j["id"], "ready_to_submit", "lease expired before submit", lease_until="")
                    out["requeued"].append(j["id"])
        return out

    def resolve_check(self, jid: str, *, found_on_portal: bool, evidence: str = "") -> str:
        """needs_check is resolved by READING the portal's 'my applications' page, never by resubmitting."""
        if found_on_portal:
            self.mark_submitted(jid, evidence or "found in portal application list")
            return "submitted"
        with self.tx() as db:
            self._set(db, jid, "ready_to_submit", "not found on portal", reason="", clicked=0)
        return "ready_to_submit"

    def set_state(self, jid: str, to: str, note: str = "", **fields) -> None:
        with self.tx() as db:
            self._set(db, jid, to, note, **fields)

    def migrate_states(self) -> dict:
        """One-time, idempotent: legacy `blocked` -> blocked_auth/human/technical by reason code;
        legacy ready_to_submit with a pending next_attempt_at -> retry_wait; browser_unavailable was
        an executor property, never a job blocker -> ready_to_submit. History/ids/evidence untouched."""
        out: dict[str, list[str]] = {}
        t = iso(now())
        with self.tx() as db:
            for j in [dict(r) for r in db.execute("SELECT * FROM jobs")]:
                to = None
                fields: dict = {}
                r = j.get("reason") or ""
                if j["state"] == "blocked":
                    if r.startswith("browser_unavailable"):
                        to, fields = ("ready_to_submit" if j.get("package") or j.get("apply_url") or j.get("url") else "eligible"), {"reason": ""}
                    else:
                        to = classify_block(r)
                        if r.startswith("max_attempts"):
                            r = "retries_exhausted:" + r.split(":", 1)[-1]
                            fields["reason"] = r
                        scope = r.split(":", 1)[1] if to == "blocked_auth" and ":" in r else self.scope(j)
                        fields.update(action=action_for(r, scope), auth_scope=scope if to == "blocked_auth" else j.get("auth_scope") or self.scope(j))
                elif j["state"] == "ready_to_submit" and (j.get("next_attempt_at") or "") > t:
                    to = "retry_wait"
                if not j.get("auth_scope") and "auth_scope" not in fields:
                    db.execute("UPDATE jobs SET auth_scope=? WHERE id=?", (self.scope(j), j["id"]))
                if to:
                    self._set(db, j["id"], to, "migrate_states", **fields)
                    out.setdefault(to, []).append(j["id"])
        return out


def submit_path_blocker(url: str, portal: str, *, browser_ok: bool, signed_in: tuple[str, ...] = (),
                        cv_uploadable: bool = True) -> str:
    """Legacy helper kept for callers/tests: '' when an executor could try this job now."""
    if not url:
        return "no_apply_url"
    if not browser_ok:
        return "browser_unavailable"
    if not cv_uploadable and not any(p in (url or "").lower() for p in ("indeed.com", "linkedin.com", "myworkdayjobs")):
        return "upload"
    return ""


def priority(j: dict, t: dt.datetime) -> tuple:
    """Flagship employers first (they hire on a rolling basis), then deadlines within 7 days,
    then newest posted. Full lane before fast lane inside each group."""
    dl = j.get("deadline") or ""
    soon = 0
    if dl:
        try:
            soon = 1 if (dt.date.fromisoformat(dl[:10]) - t.date()).days <= 7 else 0
        except ValueError:
            pass
    posted = j.get("posted") or j.get("created_at") or ""
    return (-int(j.get("flagship") or 0), -soon, 0 if j.get("lane") == "full" else 1,
            "".join(chr(255 - ord(c)) for c in posted[:10]), j["id"])
