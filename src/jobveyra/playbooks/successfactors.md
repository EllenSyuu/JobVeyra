# SAP SuccessFactors

- Candidate accounts are per employer. "Apply" opens a profile form, then job-specific questions.
- Date fields use the employer's locale; check the format shown in the placeholder.
- The data-privacy statement must be accepted to apply: leave it to the candidate unless approved.
- Listing: the career site renders results in the browser, so the HTML has none. From the career
  site's own origin, POST `/services/recruiting/v1/jobs` with `{"locale":"en_US","pageNumber":N,...}`
  and page until the result list is empty; `totalJobs` gives the count to reconcile against.
- "Apply now" hands off to `careerN.successfactors.com`, a different domain: the browser needs
  permission for it before the form can be filled.
