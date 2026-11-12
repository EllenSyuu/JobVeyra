# Oracle Recruiting Cloud (Candidate Experience)

- Sign-in is by email and a one-time code; the code is the candidate's to enter.
- Text fields need the native value setter plus `input` and `change` events; dropdowns are typeahead
  comboboxes: type a few letters, then click the option itself (arrow keys can pick the wrong one).
- Work and education entries are sub-forms saved with their own "Add" button. Re-read the list after
  each save: a save that seemed to fail may still have stored the entry, so duplicates are common.
- Numeric fields (compensation, phone) reject text; title fields are often capped at 50 characters.
- Screening answers of "Yes" can reveal required follow-up text boxes only on submit: read the error
  summary and answer each one in full, without referring to other sections.
- After the code is entered the employer may email a request for more information (references,
  certificates): that is part of the same application, not a new one.
