# Workday (*.myworkdayjobs.com)

- One account per employer (tenant). Signed in = the email shows in the header.
- `<job URL>/apply/useMyLastApplication` reuses the last profile on that tenant; check every field.
- Steps: My Information, My Experience, Application Questions, Voluntary Disclosures, Review, Submit.
- Dropdowns are `button[aria-haspopup="listbox"]` with `[role=option]` items. Multiselects with a
  search box: click the box, then the option; typing plus Enter works on some tenants only.
- "How did you hear about us" is often a two-level menu: open the category, then pick the item inside.
- After Submit, open the candidate home: the application must appear under Active.
- Job search without clicking: `POST /wday/cxs/<tenant>/<site>/jobs` with
  `{"appliedFacets":{},"limit":20,"offset":0,"searchText":"<query>"}` from the page's own origin.
