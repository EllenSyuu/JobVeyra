# Changelog

## Unreleased

- Playbooks: every search is read to its last page and reconciled with the board's own total; new
  Oracle Recruiting Cloud page; SuccessFactors listing endpoint and the apply hand-off domain.

## 0.2.0

**Documents**
- One CV base per track and language (YAML). `tailor` starts a job's package in the posting's language
  with a letter skeleton and a brief; `build` compiles a one-page CV and letter (LuaLaTeX or XeLaTeX)
  and checks the PDFs: page limit, text layer, contact text, ASCII dates, keywords, layout.
- Writing checks: tool names blocked in text, file names and PDF metadata; stock phrases, inflated verbs
  and em dashes flagged (`materials.voice`). Employer facts need `claims.md` with independent sources.
- `reviewer-prompt` and `apply-edits` for a second reading by any agent; a reviewer agent in the
  Claude Code plugin. `render` and `verify-pdf` for files outside a job.

**Markets and sign-ins**
- Market packs: Canada and Québec, United States, United Kingdom, UN system, or your own.
- `candidate.level` and `candidate.years_experience`: stretch and out-of-reach titles.
- `signins`, `signed-in`, `wait-signin`, `verify-auth`; portal playbooks (`playbook`).

**Every day**
- Answer memory (`answers.yml`, one open question per employer), a Markdown board, `retro` and
  `learnings.md`, `inbox` for recruiting emails, `consistency`, a phone page, and the JobVeyra Pulse
  browser card.

## 0.1.2

- Windows support: file locking, UTF-8 everywhere; CI on Windows, macOS and Linux.

## 0.1.1

- First release on PyPI.
