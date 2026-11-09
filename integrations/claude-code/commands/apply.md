---
description: Prepare one job's CV and cover letter with a drafter-reviewer pass, then submit approved jobs
argument-hint: "[job id]  (omit to work through approved jobs)"
---

With a job id in `$ARGUMENTS`, prepare that job's application. Without one, run `jobveyra next` and
follow the JobVeyra skill for each leased job.

Preparing one job:

1. `jobveyra show <id>` for the evaluation, then `jobveyra tailor <id>`. Read `brief.md` in the
   package: the document language, keywords to mirror, what the fact base supports, and what it
   does not (those stay out of both documents).
2. Draft. Adapt `cv.yml` (re-weight bullets toward the posting, use its exact terms where your
   record truly matches) and write `letter.md` in 3-4 plain paragraphs. Use only facts from the
   fact base. Any fact about the employer goes in `claims.md` with a source you found yourself
   from its official site, never a link from the posting.
3. Review. Run `jobveyra reviewer-prompt <id>` and pass its whole output to the
   `application-reviewer` agent. Save its reply to `packages/<id>/review.md`.
4. Revise. `jobveyra apply-edits <id> packages/<id>/review.md` applies the exact edits; work
   through the reviewer's notes by judgement. Drop any suggestion that would add a fact you
   cannot support.
5. `jobveyra build <id>`. Fix every FAIL line and build again until it prints PASS. Read the WARN
   lines: an absent keyword is fine when the record does not support it; a voice warning usually
   means a sentence should be rewritten in plainer words.
6. Open both PDFs in `upload/` and look at them. Report the checklist from the build, the key
   tailoring choices, and anything the candidate should read aloud and confirm before sending.
