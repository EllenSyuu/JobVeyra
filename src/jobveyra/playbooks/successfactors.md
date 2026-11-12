# SAP SuccessFactors

- Candidate accounts are per employer. "Apply" opens a profile form, then job-specific questions.
- Date fields use the employer's locale; check the format shown in the placeholder.
- The data-privacy statement must be accepted to apply: report it to `jobveyra finalize` as `terms`
  (ticked only with the candidate's `application_terms` consent; otherwise the job is parked).
- Listing: the career site renders results in the browser, so the HTML has none. From the career
  site's own origin, POST `/services/recruiting/v1/jobs` with `{"locale":"en_US","pageNumber":N,...}`
  and page until the result list is empty; `totalJobs` gives the count to reconcile against.
  Unsorted pages can overlap: take the union over several `sortBy` values and compare with the total.
- "Apply now" hands off to `careerN.successfactors.com`, a different domain: the browser needs
  permission for it before the form can be filled.
- On the apply form, press "Expand all sections" before answering anything: expanding a section later
  re-renders it and drops radio choices already made.
- The diversity survey and its bypass box are the candidate's own; leave them untouched.
