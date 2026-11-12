# Every portal

- Read every page of a search before screening: follow the pager or the offset to the end (or call
  the board's own JSON endpoint) and compare the count read with the total the board reports. A
  sweep that stops at page 1 is incomplete and must be redone.
- Work in the candidate's own browser profile. Never type a password or one-time code, never solve a
  CAPTCHA, never create an account: stop and run `jobveyra block <id> --reason auth:<scope>`.
- Decline non-essential cookies.
- Voluntary self-identification (gender, ethnicity, disability, veteran status and similar): leave it
  to the candidate, or choose "prefer not to answer" only if their saved answers say so.
- Consents beyond this one application (talent pools, group-wide sharing, SMS): the narrowest option.
  Accept only the terms the application itself requires, and only if the candidate approved that.
- Answer every question from the fact base, the CV in the package or `state/answers.csv`. Anything
  else: `jobveyra block <id> --reason hold:<the question>`. One question that blocks many jobs on the
  same portal is asked once.
- Upload the files in `packages/<id>/upload/`. Delete any CV or letter a profile carried over from
  an earlier application: a letter written for another employer must never travel along.
- A carried-over profile is often stale: check names, titles and dates against the fact base.
- The last page (accuracy statement, required terms, e-signature): `jobveyra finalize` decides; never
  stop the run to ask. Ordinary steps never need approval.
- Confirmation is the portal's own success page or the application listed in the candidate's
  dashboard. Nothing else counts as submitted.
