# Architecture

jobveyra is a Python package (`src/jobveyra`) plus a user **workspace** that holds every
piece of personal data. Code never writes inside the package. See `paths.py` for the
workspace layout and `examples/jobveyra.yml` for the full configuration.

```
sources/*        fetch postings from boards and feeds          -> list[Posting]
discover.py      run enabled sources, apply focus filters,
                 dedupe, cache text, enqueue `discovered`
evaluate/        legitimacy (liveness, repost, ghost signals)
                 rubric (dimensions with evidence, blockers)
                 -> Evaluation; queue.screen(fit) sets the lane
materials/       fabrication guard, outbound guard, ATS text check,
                 cover-letter angles
approvals.py     batch review page and approval tokens
worker.py        lease, package, clicked, done, uncertain, fail
analytics/       funnel, patterns, calibration, skill demand
interview/       story bank, prep sheets, negotiation, follow-ups
report/          digest, newsletter (email), status markdown,
                 Telegram and webhook notifications, calendar files
cli.py           `jobveyra <command>`
```

## Module contracts

These signatures are the integration points between modules. Every function takes plain
data or a `Config` (see `config.py`) and returns plain data; none of them prints.

### Sources (`jobveyra/sources/`)

- `sources/base.py`: `class Source` with `name: str` and
  `fetch(spec: dict, http: Http) -> list[Posting]`; `REGISTRY: dict[str, type[Source]]`;
  `get(type_name) -> Source`.
- `sources/http.py`: `class Http` wrapping `urllib` with a user agent, timeouts, retries with
  backoff, a per-host rate limit, robots.txt checks via `robots_check`, and an optional
  offline fixture directory (`Http(fixtures=Path)`) used by tests. `get_json(url)`,
  `get_text(url)`, `post_json(url, body)`, `head(url) -> int status`.
- Adapters: `greenhouse`, `lever`, `ashby`, `workable`, `smartrecruiters`, `recruitee`,
  `un_careers` (careers.un.org public API), `usajobs` (needs `USAJOBS_API_KEY`),
  `remotive`, `jsonld` (any careers page exposing schema.org `JobPosting`),
  `linkedin_alert` (parses a pasted LinkedIn job-alert email; never logs in to LinkedIn).

### Discovery (`jobveyra/discover.py`)

- `filters.py`: `region_of(location: str, remote: bool|None, focus) -> Region|None`,
  `seniority_of(title: str) -> str`, `track_of(title: str, focus) -> Track|None`,
  `passes(p: Posting, focus) -> tuple[bool, str]` (reason when it fails).
- `discover.run(cfg, http, *, only: list[str]|None = None) -> dict` returns
  `{"fetched": n, "new": n, "filtered": {reason: n}, "by_source": {name: n}, "errors": {name: msg}}`.

### Evaluation (`jobveyra/evaluate/`)

- `legitimacy.py`: `check(p: Posting, history: list[dict], http: Http|None) -> list[str]` flags:
  `closed`, `repost:<n>`, `stale:<days>`, `evergreen`, `no_salary`, `vague_title`.
- `rubric.py`: `evaluate(p: Posting, cfg: Config, *, job_id: str, history=()) -> Evaluation`.
  Dimensions (weights sum to 1): `skills`, `seniority`, `location`, `language`,
  `compensation`, `track`, `freshness`, `employer`. Every dimension carries `Evidence` with
  `basis` in {text, structure, estimate}; a dimension supported only by estimates is capped
  at 0.6. Blockers (`no_sponsorship`, `language:<code>`, `clearance`, `employment:<type>`,
  `avoid_employer`) force `lane = "excluded"`.
- `comp.py`: `parse_salary(text) -> (min, max, currency, period)`, annualised.
- `llm.py`: `Provider` interface (`complete(system, user) -> str`) for anthropic, openai,
  ollama and any OpenAI-compatible endpoint via `urllib`; `get(cfg) -> Provider|None`.
  `anonymize.py`: `mask(text, candidate) -> (masked, mapping)` and `unmask(text, mapping)`.

### Materials (`jobveyra/materials/`)

- `fabrication.py`: `check(document: str, fact_base: str) -> list[str]` returns every
  number, date, percentage, employer and degree in the document that the fact base does not
  contain.
- `outbound.py`: `check(text: str) -> list[str]` returns self-negative or disqualifying
  phrases (ported from the outbound guard).
- `ats.py`: `check_text(text: str, keywords: list[str]) -> dict` for coverage, missing
  contact details and extraction noise.
- `cover.py`: `angles(p: Posting, cfg) -> dict` for why-this-company, problems, approach, tone.

### Approvals (`jobveyra/approvals.py`)

- `stage(q, cfg) -> Batch` picks up to `policy.batch_size` ready jobs.
- `review_page(batch, cfg) -> Path` writes a static HTML page listing each job (employer,
  role, link, fit, blockers, drafted answers, CV variant).
- `approve(batch_id, *, by: str) -> str` returns a token (HMAC over job ids and content
  hashes, secret in `state/.approval_key`) valid `policy.approval_ttl_hours`.
- `allowed(job, cfg) -> tuple[bool, str]`: `auto` always true; `fill_only` always false;
  `batch_approve` true only when a live token covers this job id **and** its current
  content hash.

### Analytics, interview, report

- `analytics/funnel.py`: `funnel(jobs, outcomes) -> dict`.
- `analytics/patterns.py`: `patterns(jobs, outcomes) -> list[dict]` (response rate by source,
  portal, track, seniority, lane, with counts and Wilson intervals).
- `analytics/calibration.py`: `calibrate(jobs, outcomes) -> dict` (response rate by fit
  bucket, Brier score, AUC, monotonicity check).
- `analytics/skills.py`: `demand(texts: list[str], vocabulary: list[str]) -> list[tuple[str, int]]`.
- `interview/stories.py`: STAR+R story bank in `stories/*.yml`; `match(stories, posting) -> list`.
- `interview/prep.py`: `prep_sheet(job, posting, stories, cfg) -> str` (Markdown).
- `interview/negotiation.py`: `script(offer: dict, cfg) -> str`.
- `interview/followups.py`: `due(jobs, outcomes, today, days) -> list[dict]`.
- `report/digest.py`: `build(cfg, q, today) -> dict` (the numbers every report uses).
- `report/newsletter.py`: HTML, text and animated chart from a digest; SMTP send.
- `report/notify.py`: `telegram(text)`, `webhook(text)`; both no-ops without settings.
- `report/status.py`: Markdown status block for a README or dashboard.

## Rules for contributors

- Standard library plus `pyyaml`; `pillow` only for charts and optional.
- No network in tests: sources read fixtures through `Http(fixtures=...)`.
- No personal data in the repository: examples use the fictional candidate Alex Rivera.
- Deterministic code is the source of truth; a model may assist but never decides alone.
