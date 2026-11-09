<h1 align="center">JobVeyra</h1>

<p align="center">
  An open-source job-search engine that finds roles in the places you choose, scores each one
  with evidence, prepares honest applications, submits only what you approved, and tells you
  every morning what worked.
</p>

<p align="center">
  <b>English</b> ·
  <a href="docs/i18n/README.zh-CN.md">简体中文</a> ·
  <a href="docs/i18n/README.zh-TW.md">繁體中文</a> ·
  <a href="docs/i18n/README.ja.md">日本語</a> ·
  <a href="docs/i18n/README.ko.md">한국어</a> ·
  <a href="docs/i18n/README.fr.md">Français</a> ·
  <a href="docs/i18n/README.es.md">Español</a> ·
  <a href="docs/i18n/README.pt-BR.md">Português</a> ·
  <a href="docs/i18n/README.de.md">Deutsch</a> ·
  <a href="docs/i18n/README.it.md">Italiano</a> ·
  <a href="docs/i18n/README.ru.md">Русский</a> ·
  <a href="docs/i18n/README.ar.md">العربية</a> ·
  <a href="docs/i18n/README.hi.md">हिन्दी</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/jobveyra/"><img src="https://img.shields.io/pypi/v/jobveyra" alt="PyPI"></a>
  <a href="https://github.com/EllenSyuu/JobVeyra/actions/workflows/ci.yml"><img src="https://github.com/EllenSyuu/JobVeyra/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#compared-with-other-tools">Comparison</a> ·
  <a href="docs/ARCHITECTURE.md">Architecture</a> ·
  <a href="AGENTS.md">Agent rules</a>
</p>

---

Most job-search agents either stop before Submit and leave the clicking to you, or click
Submit on everything and hope. JobVeyra makes the choice yours, per workspace:

| `policy.submission` | What happens |
|---|---|
| `batch_approve` (default) | You review one page listing a batch of applications and approve it once. Each approval is signed over the exact posting content; if a posting changes, it comes back for review. |
| `auto` | Every job that passes your filters, score threshold and daily cap is submitted. |
| `fill_only` | Forms are filled and stop before Submit. You press it. |

In every mode, an application counts as sent only when the employer's confirmation is
recorded. A filled form, a clicked button or a high score is never counted as progress.

## Quick start

```bash
pip install "jobveyra[charts]"     # Python 3.10+; charts need Pillow

jobveyra init ~/my-search && cd ~/my-search
# edit jobveyra.yml (who you are, where you want to work, policy, sources)
# write your fact base in cv/master.md
jobveyra doctor
jobveyra discover && jobveyra evaluate
jobveyra status
```

Then let an agent work through the queue:

| Runtime | Setup |
|---|---|
| Claude Code | `/plugin marketplace add EllenSyuu/JobVeyra` then `/plugin install jobveyra@jobveyra`; commands `/jobveyra:search`, `/jobveyra:review`, `/jobveyra:apply`, `/jobveyra:digest` |
| Codex, OpenCode, Cursor, Gemini CLI, Copilot | Open the workspace; they read [`AGENTS.md`](AGENTS.md) (`GEMINI.md` points to the same file) |
| No agent | Every step is a plain command; see `jobveyra --help` |
| Browser | `jobveyra dashboard` |
| Docker | `docker build -t jobveyra .` then `docker run --rm -v "$PWD:/workspace" jobveyra discover` |

## Focus anywhere

Where you look is configuration, not code. Regions are ordered and weighted, remote work
can be allowed, required or excluded, and each role family (a *track*) carries its own
title keywords, evidenced skills and CV variant.

```yaml
focus:
  regions:
    - {name: Lisbon, match: [lisbon, lisboa, portugal], weight: 1.0}
    - {name: Remote Europe, match: [remote - europe, emea], weight: 0.7}
  remote: allow
  tracks:
    - {key: ds, label: Data science, titles: [data scientist, machine learning],
       skills: [python, sql, statistics], cv: cv/data-science.md}
  seniority_min: junior
  seniority_max: senior
  salary_floor: 40000
  salary_currency: EUR
```

The full annotated file is [`examples/jobveyra.yml`](examples/jobveyra.yml).

## How it works

```
sources        Greenhouse, Lever, Ashby, Workable, SmartRecruiters,
     │         Recruitee, UN Careers, USAJOBS, Remotive, any page
     │         with schema.org JobPosting, LinkedIn alert emails
     ▼
discover       focus filters, dedup by requisition and content
     ▼
evaluate       legitimacy checks, eight scored dimensions with
     │         evidence, hard blockers, lane
     ▼
materials      fabrication guard, self-negative wording guard,
     │         ATS text check
     ▼
approve        batch review page and signed approval
     ▼
submit         an agent drives the browser; the CLI leases one
     │         job at a time and records only confirmed sends
     ▼
learn          outcomes, funnel, patterns, score calibration,
               skill demand, follow-ups, daily digest
```

Every job lives in one persistent queue with exactly one state and the reason for it
(`discovered`, `excluded`, `eligible`, `ready_to_submit`, `in_progress`, `submitted`,
`needs_check`, `retry_wait`, `blocked_auth`, `blocked_human`, `blocked_technical`).
Illegal transitions are rejected, leases expire safely, and a crash after the Submit click
becomes `needs_check` instead of a duplicate application.

## What it does

**Discovery**
- Eleven source adapters using public, no-login endpoints, with retries, backoff, a per-host
  rate limit and robots.txt checks. Discovery costs no model calls.
- Region, remote, seniority (English, French, Spanish, Portuguese, German titles),
  employment-type, title and employer filters, each with a recorded reason when it rejects.
- Deduplication by employer and requisition id, then by posting content.

**Evaluation**
- Eight dimensions: skills, track, seniority, location, language, compensation, freshness,
  employer. Each carries evidence tagged by basis: quoted from the posting, read from
  structured fields, or estimated. A dimension backed only by estimates is capped.
- Requirements are split into required and preferred before skills are matched.
- Hard blockers end the evaluation: no sponsorship for a market you cannot work in, a
  required language you do not speak at B2 or above, security clearance, employment type,
  employers you avoid, a closed posting.
- Legitimacy signals: closed postings, reposts, stale postings, evergreen talent pools,
  missing pay, vague titles.
- Salary parsing across currencies and periods, annualised and compared with your floor.
- An optional model (Anthropic, OpenAI, Ollama or any OpenAI-compatible endpoint) can add
  a semantic skills match, limited and labelled as an estimate. Your name, email, phone and
  links are masked before any call.

**Materials**
- Fabrication guard: every number, date, employer, degree and certification in a document
  must appear in your fact base.
- Self-negative wording guard in English, French, Spanish and Portuguese.
- ATS text check: keyword coverage, contact details, extraction noise.
- Cover-letter angles drawn from the posting and only your evidenced skills.

**After you apply**
- Outcomes ledger, funnel with time to first reply, response patterns by source, portal,
  track and lane with confidence intervals, and score calibration (Brier score, AUC) that
  tells you when your threshold is wrong.
- Skill demand across the postings you saw, and the gaps against your profile.
- Follow-ups due with a draft message; deadlines as calendar files.
- Interview prep sheets, a STAR+R story bank whose metrics must cite a source, and offer
  negotiation scripts.

**Reports**
- A daily email digest with an animated chart that also works in clients that show only
  the first frame, light and dark themes, and a plain-text part.
- Telegram, Slack, Discord or Teams notifications through one webhook setting.
- A status block for any Markdown file, such as a private repository's README.

**Dashboard**
- `jobveyra dashboard` serves a local web page on 127.0.0.1: headline numbers and a 14-day
  chart, what needs attention, the full queue with filters, each job's evaluation, posting and
  history, batch review and approval, and the analytics with their intervals.
- It records decisions only (outcomes, holds, manual checks, approvals). It never submits an
  application or enters credentials. Every action needs a per-session token; `--read-only`
  turns actions off.

## Compared with other tools

Based on each project's public README in November 2026. Corrections are welcome.

| | JobVeyra | career-ops | LinkedIn AI Job Applier Ultimate | JobAppAgent |
|---|---|---|---|---|
| Submission | Your choice: batch approval, auto or fill only | Fills forms; you submit | Auto-submits | Approval per application or batch; agent stops before submit |
| What counts as applied | Employer confirmation only | Not stated | Not stated | Visible confirmation only |
| State model | One persistent queue, 11 states, leases, crash-safe | Markdown tracker | YAML result files | Ledgers |
| Approval bound to posting content | Yes (signed over content hash) | Not applicable (you submit) | No approval step | Approval covers what was shown, 24 h |
| Sources | Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, UN Careers, USAJOBS, Remotive, schema.org pages, LinkedIn alerts | Ashby, Greenhouse, Lever, Wellfound, LinkedIn alerts | LinkedIn, Indeed | Catalogue of boards and careers pages |
| Regions | Ordered, weighted regions per user | Search queries | Search filters | Search filters |
| Scoring | 0–100 over 8 dimensions, evidence basis per dimension, estimate cap | 1–5 over blocks A–H, evidence basis, estimate cap | 1–100 interest score | Fit score |
| Legitimacy checks | Closed, repost, stale, evergreen, no pay, vague title | Liveness, repost, legitimacy block | Not stated | Active-posting check |
| Fabrication guard | Numbers, dates, employers, degrees, certifications | Numbers and facts | Skips questions it cannot answer | Verified facts only |
| Score calibration | Brier, AUC, threshold advice | Advisory calibration | Not stated | Not stated |
| Outcome analytics | Funnel, patterns with intervals, skill demand | Funnel, patterns, skill gaps | Skill statistics | Outcome ledgers |
| Daily report | Email digest, Telegram, webhooks | Not stated | Telegram | Not stated |
| Local dashboard | Web dashboard (overview, queue, job detail, review and approval, insights) | Terminal dashboard | Local web dashboard | Not stated |
| Model required | No (optional, masked) | An AI CLI or evaluator | Yes | A coding agent |
| Runtimes | Claude Code plugin, AGENTS.md CLIs, Docker, plain CLI | Many AI CLIs, Docker | Python app, Docker | Agent skill plus CLI |

Where the others are ahead today: career-ops has a large community, an interactive terminal
dashboard, company research and outreach drafting, and READMEs in 18 languages; the
LinkedIn applier automates LinkedIn and Indeed directly and has a local web control panel;
JobAppAgent supports multi-host state through an optional cloud backend.

## Privacy

Your data lives in your workspace, never in this repository. `jobveyra init` writes a
`.gitignore` that excludes the whole workspace. No telemetry, no backend. Model calls are
off by default and masked when on. The engine never enters passwords, solves CAPTCHAs,
creates accounts, accepts legal attestations or sends email other than your own digest.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for module contracts. Tests run offline
against recorded fixtures for every source.

## License

MIT. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
