"""Discovery: run the configured sources, apply the focus filters, dedupe, cache and enqueue.

For each entry in ``cfg.sources`` (``enabled: false`` skips it) the adapter named by ``type``
fetches postings. Each posting that passes ``filters.passes`` gets a queue id
(:func:`posting_id`), its full text is cached as ``<workspace>/postings/<safe id>.json`` and it is
upserted into the queue as ``discovered``. Postings are deduplicated across sources and against
the queue by job id, and by ``content_hash`` when the posting has text.

A source's *name* is ``spec["name"]`` when given, else its ``type``; it is recorded on each queue
row as ``source`` and keys ``by_source`` (postings fetched per source, including zero) and
``errors``. ``only`` limits a run to sources whose name or type is listed.
"""
from __future__ import annotations

import dataclasses as dc
import json
import os
import re
import tempfile
from pathlib import Path

from . import filters, queue
from . import sources as sources_pkg
from .models import Posting


def source_name(spec: dict) -> str:
    return str(spec.get("name") or spec.get("type") or "?")


def req_key(p: Posting) -> str:
    """The requisition key the queue uses: from the URL when the queue recognises it, else
    ``<source>:<req_id>`` from the adapter, else ''."""
    return queue.req_from(p.url, p.title) or (f"{p.source}:{p.req_id.strip().lower()}" if p.req_id.strip() else "")


def posting_id(p: Posting) -> str:
    """The queue job id for a posting (``queue.job_id`` with :func:`req_key`)."""
    return queue.job_id(p.employer, p.title, p.url, req_key(p), p.location)


def safe_id(jid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", jid).strip("._") or "job"


def posting_path(workspace: Path, jid: str) -> Path:
    return Path(workspace) / "postings" / f"{safe_id(jid)}.json"


def save_posting(workspace: Path, jid: str, p: Posting) -> Path:
    path = posting_path(workspace, jid)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dc.asdict(p)
    data["id"] = jid
    data["content_hash"] = p.content_hash
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".posting.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return path


def load_posting(workspace: Path, jid: str) -> Posting | None:
    """The cached Posting for a job id, or None."""
    path = posting_path(workspace, jid)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    names = {f.name for f in dc.fields(Posting)}
    return Posting(**{k: v for k, v in data.items() if k in names})


def _bump(d: dict, key: str, n: int = 1) -> None:
    d[key] = d.get(key, 0) + n


def run(cfg, http, *, only: list[str] | None = None) -> dict:
    """Run discovery. Returns
    ``{"fetched": n, "new": n, "filtered": {reason: n}, "by_source": {name: n}, "errors": {name: msg}}``.
    ``filtered`` holds filter reason codes (see ``filters``), ``invalid`` (no title or URL) and
    ``duplicate`` (same id or same text as a posting already seen this run or in the queue)."""
    queue.configure(cfg)
    q = queue.Queue(cfg.state_dir)
    stats: dict = {"fetched": 0, "new": 0, "filtered": {}, "by_source": {}, "errors": {}}
    try:
        known = q.all()
        hash_owner = {j["content_hash"]: j["id"] for j in known if j.get("content_hash")}
        seen_run: set[str] = set()
        wanted = set(only or [])

        for spec in cfg.sources:
            name = source_name(spec)
            if spec.get("enabled", True) is False:
                continue
            if wanted and name not in wanted and spec.get("type") not in wanted:
                continue
            try:
                src = sources_pkg.get(str(spec.get("type")))
            except KeyError as e:
                stats["errors"][name] = str(e.args[0] if e.args else e)
                continue
            call_spec = dict(spec)
            call_spec.setdefault("_workspace", str(cfg.workspace))
            try:
                postings = src.fetch(call_spec, http)
            except Exception as e:  # one broken source never stops the others
                stats["errors"][name] = f"{type(e).__name__}: {e}"
                _bump(stats["by_source"], name, 0)
                continue
            stats["fetched"] += len(postings)
            _bump(stats["by_source"], name, len(postings))

            for p in postings:
                if not p.title or not p.url:
                    _bump(stats["filtered"], "invalid")
                    continue
                ok, reason = filters.passes(p, cfg.focus)
                if not ok:
                    _bump(stats["filtered"], reason)
                    continue
                jid = posting_id(p)
                h = p.content_hash if p.text.strip() else ""
                if jid in seen_run or (h and hash_owner.get(h, jid) != jid):
                    _bump(stats["filtered"], "duplicate")
                    continue
                seen_run.add(jid)
                if h:
                    hash_owner[h] = jid
                p.extra = {**p.extra, "source_name": name}
                save_posting(cfg.workspace, jid, p)
                track = filters.track_of(p.title, cfg.focus)
                row = p.to_queue()
                row.update(id=jid, req_id=req_key(p), source=name, state="discovered")
                if track:
                    row["family"] = track.key
                _, created = q.upsert(row)
                if created:
                    stats["new"] += 1
    finally:
        q.close()                   # Queue keeps an in-memory SQLite copy; release it
    return stats
