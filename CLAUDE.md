# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A job-search evaluation pipeline: given a job posting URL, it scrapes the ad, scores
the commute against `HOME_ADDRESS`, scores fit against a candidate's resume/
preferences via an LLM-drafted regex rubric, and caches the result in SQLite so the
same URL is never re-evaluated for free. The code is intentionally **candidate-
agnostic** — no resume/domain/role content may live in any `.py` file. All
personalization flows through `data/resume.md` and `data/job_preferences.md`.

**Whenever you change a file's behavior or logic, check whether `README.md` documents
that behavior and update it in the same change** — the README's pipeline diagrams,
cost tables, and Future Improvements list are meant to stay accurate, not aspirational.

## Commands

Host machine has no Python deps installed — everything runs inside the docker
compose container:

```
docker compose up -d
docker compose exec notebook python3 evaluate_job_post.py <job-url>          # evaluate one job
docker compose exec notebook python3 evaluate_job_post.py <job-url> --force  # bypass the cache
docker compose exec notebook python3 scripts/check_setup.py                  # verify API keys/provider wiring
```

There is no unit test suite or linter configured. The closest thing to tests is the
eval harness:

```
docker compose exec notebook python3 evals/run_evals.py                  # run all cases
docker compose exec notebook python3 evals/run_evals.py --verified-only  # only hand-verified ground truth
docker compose exec notebook python3 evals/add_case.py <url>             # add/refresh one case from a live run
docker compose exec notebook python3 evals/regenerate_cases.py           # bulk-rebuild every case (expensive: full pipeline re-run per URL, no cache)
```

`run_evals.py` reports pass/fail per pipeline **stage** (`days_on_office`, `address`,
`commute_score`, `compatibility_score`, `criteria_matched`, `criteria_unmatched`),
ranked worst-first, not just per case — that ranking is the signal for what to fix
next. Only cases with `"verified": true` in `evals/cases.json` are trustworthy ground
truth; anything from `add_case.py`/`regenerate_cases.py` is a draft
(`"verified": false`) meant to be hand-reviewed before being trusted.

Ad-hoc querying of saved evaluations has no dedicated script — use `sqlite3` directly
against `data/evaluations.db` (e.g. `ORDER BY compatibility_score DESC LIMIT 5`,
`WHERE is_remote = 1`). Marking a job reviewed/applied/discarded is a direct call to
`storage.update_review(url, ...)`, also with no CLI wrapper yet.

## Architecture

### Pipeline (`evaluate_job_post.py:evaluate_job`)

```
evaluate_job(url) -> cache hit (same normalized URL + unchanged rubric)?
  yes -> return saved row from storage.get_evaluation()
  no  -> scrape_post(url)            Tavily extract + 1 LLM call -> {job_title, company, location, description}
      -> commute_score(...)          commute.py; 1-3 LLM calls + ORS geocode/route, skipped once remote is detected
      -> compatibility_score(...)    regex rubric match (free) + 1 LLM call for the final 0-100 judgment
      -> summarize_evaluation(...)   1 LLM call: works_well / does_not_work
      -> storage.save_evaluation()   SQLite upsert, keyed by normalized URL
```

All LLM calls go through `llm.py`'s `_ask_json`/`_ask_json_with_tools` (aisuite,
model = `EXTRACTION_MODEL` in `llm.py`, currently Anthropic Haiku). `_ask_json_with_tools`
runs a bounded agentic loop (`max_iterations`) for the one place that needs it: rubric
drafting.

### The compatibility rubric: LLM-generated once, regex-applied many times

`compatibility_score()` never asks an LLM to read the full rubric-drafting process for
every job — it applies a **cached, pre-compiled rubric** via deterministic regex:

```
data/resume.md + data/job_preferences.md
        │ (sha256 of both files vs rubric's stored resume_hash/preferences_hash)
        ▼
load_or_compile_rubric()  -- cheap check on every evaluate_job() call
        │ mismatch
        ▼
compile_rubric() -> draft_rubric() (agentic: proposes criteria, calls test_regex tool
                     to validate each pattern before finalizing, up to 30 iterations)
                 -> reflect_on_rubric() (1-shot critique/revision pass)
        ▼
data/compatibility_rubric.json  {resume_hash, preferences_hash, criteria[], scoring_guidance}
        │
        ▼
evaluate_rubric(rubric, description)  -- pure regex, no LLM: each criterion gets
        matched (bool) and score (+weight / -weight if dealbreaker / 0)
```

`scoring_guidance` is the verbatim text of job_preferences.md's `## Scoring Notes`
section (extracted by `_extract_section()`), passed into the final LLM judgment
prompt unmodified — this is the mechanism that keeps domain-specific scoring logic
(e.g. "this role only counts if the company is in domain X") out of `.py` files
entirely and inside the user-owned preferences file instead.

**Two independent cache layers, don't conflate them:**
- `load_or_compile_rubric()` invalidates the *rubric* against `resume.md`/
  `job_preferences.md` file hashes (whole-file, so any edit — including
  `## Scoring Notes` — triggers a recompile).
- `storage.rubric_content_hash(rubric)` invalidates a *saved job evaluation* against
  the compiled rubric's `criteria` + `scoring_guidance`. This must stay in sync with
  everything `compatibility_score()` actually reads from the rubric — if a new field
  is ever added to the rubric and used in that prompt, it needs to be included in
  this hash too, or saved evaluations will silently go stale without being
  invalidated.

### Storage (`storage.py`)

SQLite, two tables: `evaluations` (one row per normalized URL) and
`evaluation_criteria` (one row per rubric criterion per evaluation, replaced wholesale
on every re-save). `normalize_url()` strips tracking params (`trk`, `utm_*`, etc.) and
trailing slashes so the same posting under different tracking links dedupes to one
row. Schema upgrades go through `_MIGRATIONS` (`PRAGMA table_info` + conditional
`ALTER TABLE ADD COLUMN`) — never destructive, existing rows survive. User-tracked
fields (`reviewed`, `application_status`, `status_reason`, `notes`) are preserved
across re-evaluation of the same URL; only pipeline-derived fields and
`evaluation_criteria` are overwritten.

### Personalization files are tracked but git-invisible once edited

`.env`, `data/resume.md`, and `data/job_preferences.md` are committed as generic
templates but have the **skip-worktree** git bit set. Editing them with real
keys/resume/preferences will not show up in `git status`/`git diff`, and won't get
picked up by `git add -A`. To change the template itself (not your personal content),
you must first run `git update-index --no-skip-worktree <file>`, commit, then
re-apply `git update-index --skip-worktree <file>`.

`data/compatibility_rubric.json`, `data/evaluations.db`, and `evals/cases.json` are
gitignored entirely (generated/personal, never tracked).

### Eval case shape (`evals/cases.json`)

Each case: `{name, url, verified, notes, expected: {...}}`. `expected` keys are
independent and optional — only the ones present are checked:
`days_on_office` / `commute_score` (ranges, tolerate LLM/routing variance — never
assert exact equality), `address_contains` (substring), `compatibility_score`
(range), `criteria_matched_contains` / `criteria_unmatched_contains` (lists of
substrings matched case-insensitively against rubric criterion *names*, so a rubric
rename doesn't silently break the case). `run_evals.py` batches its LLM/API calls per
case (one `commute_score()` call, one `compatibility_score()` call) rather than
calling pipeline functions multiple times per case.
