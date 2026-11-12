# The last page of an application

Most applications end on a page with an accuracy statement ("I certify the information provided
is true and complete"), a privacy statement that must be accepted, sometimes a typed signature, and
the Submit button. An agent that has to guess what it may do there either stops and waits (and one
waiting form holds up the whole batch) or ticks something it should not. JobVeyra decides in code.

## Protocol

```
jobveyra next                                  # lease a job, task card
...fill the form (answers via `jobveyra answers ask`)...
jobveyra progress <id> --stage form_completed  # optional checkpoint
jobveyra finalize <id> --page URL --saved draft_saved|not_saved|unknown --reconstructable yes|no|unknown \
  --elements '[{"kind":"accuracy_declaration","text":"I certify ...","required":true},
               {"kind":"terms","text":"I accept the privacy statement"},
               {"kind":"answer","text":"Salary","source":"answers"},
               {"kind":"submit","text":"Apply"}]'
#  exit 0 -> {"click": true, "tick": [...], "leave": [...]}: tick those, press Submit once
#  exit 5 -> parked / excluded / do_not_click: take the next job
jobveyra done <id> --confirmation "..."  |  jobveyra uncertain <id> --why "..."
```

## What is decided

| element | without consent | with consent |
|---|---|---|
| navigation, verified answers, optional consents (left unticked) | proceed | proceed |
| generic accuracy statement | park (final approval) | tick, if every answer is verified |
| statement your known facts contradict, required | job excluded as ineligible, nobody asked | same |
| statement your known facts contradict, optional | left unticked | same |
| statement with a fact nobody established (years, licence, clearance) | park | park |
| required terms / privacy statement | park | tick (`application_terms`) |
| typed e-signature | park | type the legal name (`electronic_signature`) |
| required self-identification | park | your saved answer (`self_identification`) |
| CAPTCHA · MFA, password, account · ID number · extension prompt | technical · auth · park · park | same |

Known facts live in `<state>/claims.json`, e.g.
`[{"pattern": "\\b(citizen|permanent resident)\\b", "true": false, "why": "not a citizen"}]`.
Consents live in `<state>/consents.json` and are recorded only by the candidate:
`jobveyra authorize --consent accuracy_declaration --evidence "<your words, where, when>"`.
Recording one releases every parked job it now fully covers. Approving one job (`jobveyra authorize
<id> --evidence ...` or the board's tick) lets the agent finish that job; it is never a submission.

## Stages

`final_stage` is metadata on the existing queue states, so nothing else changes:

| final_stage | queue state |
|---|---|
| form_in_progress, form_completed, finalization_ready | in_progress (requeued on crash; blocked_auth if the session expired, stage kept) |
| awaiting_final_authorization | blocked_human, reason `hold:final:<kinds>` |
| submit_attempted | in_progress, clicked (written before the click) |
| submission_uncertain | needs_check (resolved only by `jobveyra reconcile`) |
| submission_confirmed | submitted |

Existing queues: `jobveyra migrate-finalization` (additive, idempotent, `--rollback` strips the fields).
