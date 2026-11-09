"""Where a user's data lives.

jobveyra keeps code and personal data apart: the package never stores anything inside
itself. Everything a user owns (profile, CVs, queue, packages, reports) lives in a
*workspace* directory, found in this order:

1. the ``JOBVEYRA_HOME`` environment variable;
2. the nearest parent of the current directory that contains ``jobveyra.yml``;
3. the current directory.

Layout of a workspace::

    jobveyra.yml        profile, focus, policy, sources, notifications
    cv/                 master CV and track variants (the fact base)
    state/              queue.jsonl, events.jsonl, approvals.jsonl, answers.csv
    postings/           cached posting text, one file per job id
    packages/           tailored materials per job
    reports/            evaluations, newsletters, analytics
    stories/            interview story bank
"""
from __future__ import annotations

import os
from pathlib import Path

CONFIG_NAME = "jobveyra.yml"
SUBDIRS = ("cv", "state", "postings", "packages", "reports", "stories")


def workspace(start: Path | None = None) -> Path:
    env = os.environ.get("JOBVEYRA_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path.cwd()).resolve()
    for p in (here, *here.parents):
        if (p / CONFIG_NAME).is_file():
            return p
    return here


def state_dir(ws: Path | None = None) -> Path:
    return (ws or workspace()) / "state"


def ensure(ws: Path) -> Path:
    for d in SUBDIRS:
        (ws / d).mkdir(parents=True, exist_ok=True)
    return ws
