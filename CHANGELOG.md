# Changelog

## 0.3.0

**The last page of an application**
- `jobveyra finalize <id> --elements JSON`: the agent reports what the final page shows and the engine
  decides. Ordinary steps never need approval; an accuracy statement or required terms are ticked only
  with a standing consent the candidate recorded in their own words (`jobveyra authorize --consent`),
  every answer verified and a true or generic statement. A required declaration that the candidate's
  known facts contradict (`<state>/claims.json`) excludes the job without asking; an optional one is
  left unticked. CAPTCHA, MFA, passwords, accounts, ID numbers and browser-extension prompts are never
  worked around.
- Finalization lifecycle as metadata on the existing states (no new state machine): form_in_progress,
  form_completed, finalization_ready, awaiting_final_authorization (`blocked_human`), submit_attempted,
  submission_uncertain (`needs_check`), submission_confirmed (`submitted`); page, required action,
  draft saved, reconstructable and a recovery note are kept for every parked form.
- Durable attempt record before the click, idempotent: a second `finalize` on the same lease never
  clicks; an earlier attempt that was never reconciled blocks the click and goes to `needs_check`.
  `jobveyra reconcile` resolves needs_check only from the portal's application list, with evidence.
- Board: a "Final approval" section with one tick per portal and kind (an authorization, never a
  submission); "I applied myself" now needs the portal to list it. `jobveyra holding` groups every
  blocker: auth, final approval, question, technical, status unknown.
- `jobveyra migrate-finalization [--dry-run|--rollback]`: additive and idempotent, with a backup.
- `consistency` reports final-stage / state mismatches.

**Playbooks**: every search is read to its last page and reconciled with the board's own total; new
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
