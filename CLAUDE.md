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
`Cost & caching` tiers, and Future Improvements list are meant to stay accurate, not
aspirational.

**The database is for usage; `evals/` is for eval.** `data/evaluations.db` records real
evaluations and grows on its own; the eval set is curated by hand and stays small
enough to hold verified ground truth. Eval code may import only the pure helpers from
`jobsearch.storage` (`normalize_url`, `rubric_content_hash`) — never `get_*`/`save_*`/
`list_*`, which open the database. Nothing under `evals/` may read or write
`data/evaluations.db`, and the eval set must never be populated by sweeping it.

## Commands

Host machine has no Python deps installed — everything runs inside the podman
compose container:

```
podman-compose up -d
podman-compose exec job-search python3 evaluate_job_post.py <job-url>          # evaluate one job
podman-compose exec job-search python3 evaluate_job_post.py <job-url> --force  # bypass the cache
podman-compose exec job-search python3 scripts/check_setup.py                  # verify API keys/provider wiring
```

Tests use stdlib `unittest` (no linter configured). Offline unit tests live in
`tests/unit/` (no LLM/network/env); the live end-to-end smoke test lives in `tests/e2e/`
(needs API keys; set `TARGET_URL` in `tests/e2e/test_e2e_pipeline.py`). Separate
subdirectories so the offline suite can run without credentials:

```
podman-compose exec job-search python3 -m unittest discover -s tests/unit   # offline unit tests
podman-compose exec job-search python3 -m unittest discover -s tests/e2e    # live end-to-end smoke test
```

Beyond those, the eval harness replays a hand-curated set of saved postings:

```
podman-compose exec job-search python3 evals/capture.py <url>              # save a posting as a replayable ad
podman-compose exec job-search python3 evals/capture.py --list-candidates  # review the eval set before picking cases
podman-compose exec job-search python3 evals/capture.py --re-extract --all # rebuild extracted fields from saved text
podman-compose exec job-search python3 evals/draft.py --all                # pre-fill ground truth for a human to correct
podman-compose exec job-search python3 evals/run_evals.py --criteria-only  # rubric regexes only: free, no network, ~1s
podman-compose exec job-search python3 evals/run_evals.py --no-commute     # + days_on_office + compatibility (2 LLM calls/case)
podman-compose exec job-search python3 evals/run_evals.py --verified-only  # full pipeline, hand-verified cases only
podman-compose exec job-search python3 evals/run_evals.py --compare        # diff against the previous run snapshot
```

`run_evals.py` reports pass-rate **and** a continuous metric per step: mean absolute error
for `compatibility_score`/`commute_score`, exact-match for `days_on_office`, and
accuracy/precision/recall for criteria. The continuous metrics are the point — a tolerance
band is passed by two runs that are nowhere near each other, so pass/fail alone can't show
whether a change helped. Each run is snapshotted to `evals/runs/` with the rubric hash and
both model ids so `--compare` can attribute a change afterwards.

Only cases with `"verified": true` in `evals/cases.json` are ground truth; anything
`draft.py` pre-filled is `"verified": false` — it records what the pipeline currently says,
which is the thing under test, so trusting it would be circular.

Tolerances are harness policy, not per-case data: `--tolerance-score` (default 10, on a
0-100 judgment) and `--tolerance-commute` (default 5 weighted minutes, deliberately tight
because the commute accept/reject boundary is only a few minutes wide).

Ad-hoc querying of saved evaluations has no dedicated script — use `sqlite3` directly
against `data/evaluations.db` (e.g. `ORDER BY compatibility_score DESC LIMIT 5`,
`WHERE is_remote = 1`). Marking a job reviewed/applied/discarded is a direct call to
`storage.update_review(url, ...)`, also with no CLI wrapper yet.

## Architecture

The code is a `jobsearch/` package with two thin root CLI entrypoints
(`evaluate_job_post.py`, `discover_jobs.py`) that only parse arguments and delegate in.
Modules, by concern:

- `jobsearch/config.py` — filesystem paths, personalization-file access (`read_resume`,
  `read_job_preferences`, `file_hash`, `extract_section`), the `FULLY_REMOTE` sentinel,
  and **lazy** env access (`require_env`/`home_address`) so modules import without a
  populated `.env`.
- `jobsearch/llm.py` — aisuite wrapper. `jobsearch/storage.py` — SQLite persistence.
- `jobsearch/scrape.py` — content acquisition (`fetch_page_text`, `extract_post`,
  `validate_post`, `scrape_post`, `ScrapeError`). Fetch and extract are separate so a
  posting's raw page text can be saved once and re-extracted later without re-fetching;
  `scrape_post` composes them for the live path.
- `jobsearch/rubric.py` — the compatibility rubric: draft/reflect/cache + regex application.
- `jobsearch/commute.py` — commute scoring.
- `jobsearch/evaluation.py` — score a job against the rubric + `evaluate_job` orchestrator.
- `jobsearch/discovery.py` — candidate discovery.

### Pipeline (`jobsearch/evaluation.py:evaluate_job`)

```
evaluate_job(url) -> cache hit (same normalized URL + unchanged rubric)?
  yes -> return saved row from storage.get_evaluation()
  no  -> scrape_post(url)            Tavily extract + 1 LLM call -> {job_title, company, location, description}
      -> commute_score(...)          jobsearch/commute.py; 1-3 LLM calls + ORS geocode/route, skipped once remote is detected
      -> compatibility_score(...)    regex rubric match (free) + 1 LLM call for the final 0-100 judgment
      -> summarize_evaluation(...)   1 LLM call: works_well / does_not_work
      -> storage.save_evaluation()   SQLite upsert, keyed by normalized URL
```

All LLM calls go through `jobsearch/llm.py`'s `ask_json`/`ask_json_with_tools` (aisuite).
Both take a `model=` argument defaulting to `EXTRACTION_MODEL` (currently Anthropic Haiku),
which every pipeline stage uses **except** rubric compilation: `jobsearch/rubric.py`'s
draft + reflect calls pass `RUBRIC_MODEL` (currently Anthropic Sonnet), since regex/criteria
quality there justifies a stronger, pricier model while the per-job hot path stays cheap.
`ask_json_with_tools` runs a bounded agentic loop (`max_iterations`) for the one place that
needs it: rubric drafting. Both functions disable Anthropic extended-thinking
(`_provider_kwargs`) because aisuite's response converter can't parse a leading
`ThinkingBlock` (it reads `content[0].text`).

### The compatibility rubric: LLM-generated once, regex-applied many times

`compatibility_score()` (in `jobsearch/evaluation.py`) never asks an LLM to read the
full rubric-drafting process for every job — it applies a **cached, pre-compiled
rubric** (built, cached, and regex-applied by `jobsearch/rubric.py`):

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
section (extracted by `config.extract_section()`), passed into the final LLM judgment
prompt unmodified — this is the mechanism that keeps domain-specific scoring logic
(e.g. "this role only counts if the company is in domain X") out of `.py` files
entirely and inside the user-owned preferences file instead.

`load_or_compile_rubric()` is composed from `load_rubric()` (returns the cached rubric or
`None`, never compiles) and `rubric_is_stale(rubric)`. Callers that must not trigger a live
agentic recompile use those two directly — `evals/run_evals.py` resolves one rubric per run
and warns when it's stale, because a mid-run recompile would score different cases against
different rubrics. `compatibility_score(..., rubric=)` takes that pinned rubric; it defaults
to the cached one when omitted.

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

### Storage (`jobsearch/storage.py`)

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

`data/compatibility_rubric.json`, `data/evaluations.db`, `evals/cases.json`,
`evals/ads/`, and `evals/runs/` are gitignored entirely (generated/personal, never
tracked). Stored ads hold verbatim scraped job-ad text — that content is data under `evals/`
and must never be inlined into a `.py` file, per the candidate-agnostic rule above.

### Eval case shape (`evals/cases.json`)

Each case: `{name, url, ad, verified, notes, expected: {...}}`.

`ad` names a file in `evals/ads/` and is what the case replays against — the `url`
is provenance, not an input, so a posting being taken down can't break a case. `ad:
null` means capture failed; the case is kept, reported, and skipped. The ad is recorded
explicitly rather than derived from `name` so renaming a case can't orphan its inputs.

`expected` keys are independent and optional — only the ones present are checked:
`compatibility_score` (int 0-100), `days_on_office` (int, exact), `commute_score` (weighted
minutes), `address_contains` (a short distinctive substring, or the `FULLY_REMOTE` sentinel,
which is compared by equality), and `criteria` (exact criterion name → bool).

**Ground truth is one value per step, never a `[lo, hi]` range.** A range is passed by two
runs that are nowhere near each other, which hides the change an eval exists to detect; the
accepted margin belongs to the harness (`--tolerance-*`), not the case. `dataset.py`'s
`EXPECTED_TYPES`/`validate_expected` enforce this — a leftover range is rejected with the
command to re-draft rather than silently scored.

**`criteria` uses exact names, and unknown names are never scored.** Each label sorts into
correct / wrong / `stale_label` (a name the rubric no longer has) / `unlabeled` (a rubric
name with no label); only correct and wrong reach accuracy. A rubric rename therefore
surfaces as reported work rather than a silent pass or fail. (The previous
`criteria_matched_contains`/`criteria_unmatched_contains` lists asserted the *absence* of a
substring, so a renamed criterion passed vacuously — this shape exists specifically to make
that impossible.)

`run_evals.py` batches per case: at most one `commute_score()` call and one
`compatibility_score()` call, with the criteria pass being free regex over the stored ad.
