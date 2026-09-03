# Architecture

The code is a `jobsearch/` package with two root CLI entrypoints, `evaluate_job_post.py`
and `discover_jobs.py`, that parse arguments and delegate into it.

## Modules

| Module | Concern |
|--------|---------|
| `jobsearch/config.py` | Filesystem paths, personalization-file access (`read_resume`, `read_job_preferences`, `file_hash`, `extract_section`), the `FULLY_REMOTE` sentinel, and lazy env access (`require_env`, `home_address`) so modules import without a populated `.env`. |
| `jobsearch/llm.py` | aisuite wrapper: one-shot JSON calls and a bounded agentic tool-call loop. |
| `jobsearch/storage.py` | SQLite persistence, URL normalization, cache-hash helpers. |
| `jobsearch/scrape.py` | Content acquisition: `fetch_page_text`, `extract_post`, `validate_post`, `scrape_post`, `ScrapeError`. |
| `jobsearch/commute.py` | Office-address lookup and commute-time scoring via OpenRouteService. |
| `jobsearch/rubric.py` | The compatibility rubric: draft, reflect, cache, and regex application. |
| `jobsearch/evaluation.py` | Score a job against the rubric and commute; the `evaluate_job` orchestrator. |
| `jobsearch/discovery.py` | Derive queries, search Indeed and LinkedIn, surface or evaluate new URLs. |
| `jobsearch/preselection.py` | Cut the discovered job ads to the N worth evaluating. |

Fetch and extract are separate in `scrape.py` so a posting's raw page text can be saved
once and re-extracted later without re-fetching. `scrape_post` composes them for the live
path.

## Evaluating one posting

`jobsearch/evaluation.py:evaluate_job`:

```
evaluate_job(url)
  │
  ├─ URL already evaluated and rubric unchanged?  ──►  return the saved evaluation
  │
  └─ otherwise run the pipeline, then save the result:
       scrape_post              Tavily fetch, then extract title / company / location / description
       commute_score            geocode + route the office via OpenRouteService; skipped when remote
       compatibility_score      regex-match the cached rubric, then judge an overall 0-100 score
       summarize_evaluation     one-line "works well / doesn't work" summary
       storage.save_evaluation  upsert into SQLite, keyed by the normalized URL
```

## LLM calls

All LLM calls go through `jobsearch/llm.py`'s `ask_json` and `ask_json_with_tools`
(aisuite). Both take a `model=` argument defaulting to `EXTRACTION_MODEL` (Anthropic
Haiku), which every pipeline stage uses except rubric compilation. `jobsearch/rubric.py`'s
draft and reflect calls pass `RUBRIC_MODEL` (Anthropic Sonnet): regex and criteria quality
justify a stronger model there, while the per-job hot path stays cheap.

`ask_json_with_tools` runs a bounded agentic loop (`max_iterations`) for the one caller
that needs it, rubric drafting.

Both functions disable Anthropic extended thinking (`_provider_kwargs`). aisuite's
response converter reads `content[0].text` and cannot parse a leading `ThinkingBlock`.

### Switching provider

The pipeline is configured for Anthropic models, but every call goes through aisuite, so
switching provider is a matter of changing the `provider:model` strings
(`EXTRACTION_MODEL`, `RUBRIC_MODEL`) in `jobsearch/llm.py` and setting that provider's key
in `.env`. `_provider_kwargs` is Anthropic-specific and would need its own branch for a
provider whose response converter has a similar quirk.

## Commands

| Entrypoint | Purpose |
|------------|---------|
| `discover_jobs.py` | Find, pre-select and optionally score new postings. `--help` lists every flag. |
| `evaluate_job_post.py <url>` | Score one posting directly, the manual path into the same pipeline. `--force` re-scrapes and re-scores, ignoring the cache. |
| `scripts/recompile_rubric.py` | Force-rebuild the compatibility rubric, bypassing the file-hash cache. `--if-changed` respects it instead. |

Every flag has its own help string; the three commands above are the definitive list,
kept here only as pointers so it never needs to be transcribed and re-synced by hand. Test
and eval commands are in [evals.md](evals.md).

### Scoring one posting directly

The manual, single-URL path into the pipeline `discover_jobs.py` otherwise drives. Useful
to check one link, or to re-run a specific posting. Re-running the same URL is a database
read with no API calls, unless `--force` is passed:

```
$ python evaluate_job_post.py https://example-ats.com/acme/senior-backend-engineer

Evaluating Position: Senior Backend Engineer at Acme Robotics
Commute score: 41.5 min (2 days/week, Bahnhofstrasse 1, 8001 Zurich, Switzerland)
Compatibility score: 78/100
Works well: Backend-heavy role in robotics; Python and distributed systems match.
Does not work: Requires on-call rotation; team language is German.
Reviewed: no
Application status: new
```

### Listing without scoring

`discover_jobs.py` without `--evaluate` runs the same discovery and pre-selection, prints
the same `format_preselection()` report, and stops before spending anything on evaluation:

```
$ python discover_jobs.py --limit 3

3 job ad(s) selected for evaluation:

- Senior Backend Engineer at Acme Robotics (Zurich, Switzerland)
  https://example-ats.com/acme/senior-backend-engineer
  prescore 6: role match, python, hybrid
  why: strong skills match, hybrid schedule fits stated preferences
...

18 discovered -> 16 fresh -> 14 distinct openings -> 11 not yet evaluated -> 3 selected (1 LLM call)

Run with --evaluate to score these (costs LLM/Tavily-extract/ORS calls per url).
```

`--no-preselect` skips pre-selection entirely (see [Pre-selection](#pre-selection)) and
prints the raw discovered list instead, in discovery order.

## The compatibility rubric

Compatibility is scored against a rubric, a set of weighted criteria, generated by an LLM
once per resume/preferences version rather than per job:

```
data/resume.md + data/job_preferences.md
        │  sha256 of both files vs the rubric's stored resume_hash / preferences_hash
        ▼
load_or_compile_rubric()   cheap check on every evaluate_job() call
        │  mismatch
        ▼
compile_rubric()  ->  draft_rubric()       agentic: proposes criteria, calls the
                                           test_regex tool to validate each pattern
                  ->  reflect_on_rubric()  one-shot critique and revision pass
        ▼
data/compatibility_rubric.json
    {resume_hash, preferences_hash, criteria[], scoring_guidance}
        │
        ▼
evaluate_rubric(rubric, match_text(job_title, location, description))
    pure regex, no LLM: each criterion gets matched (bool) and score
    (its signed weight in [-5, 5] if matched, 0 if not)
```

### Patterns match title, location and description

Patterns match against `match_text()`, which joins title, location and description, not the
description alone. A criterion's evidence is spread across all three: a role is stated in
the title, a city in the location. Matching the description alone reported those criteria
as unmatched regardless of pattern quality (measured: recall 0.68 to 0.86 on the eval set).

Every caller composes the same text. `evals/draft.py` must match `evals/run_evals.py` here
or drafted labels disagree with the scored ones. The drafting prompt in `rubric.py`
describes these three fields to the agent, so patterns are written for the phrasings each
field uses.

### Scoring guidance

`scoring_guidance` is the verbatim text of `job_preferences.md`'s `## Scoring Notes`
section, extracted by `config.extract_section()` and passed into the final LLM judgment
prompt unmodified. This keeps domain-specific scoring logic (for example, "this role only
counts if the company is in domain X") out of `.py` files and inside the user-owned
preferences file.

### Pinning a rubric

`load_or_compile_rubric()` is composed from `load_rubric()` (returns the cached rubric or
`None`, never compiles) and `rubric_is_stale(rubric)`. Callers that must not trigger a live
agentic recompile use those two directly. `evals/run_evals.py` resolves one rubric per run
and warns when it is stale, because a mid-run recompile would score different cases against
different rubrics. `compatibility_score(..., rubric=)` takes that pinned rubric and
defaults to the cached one when omitted.

## Discovery

`discover_jobs.py` finds new job ad URLs instead of requiring one to be pasted in:

- derives search phrases from `resume.md`, `job_preferences.md` and `HOME_ADDRESS`, cached
  in `data/search_queries.json` and invalidated when any of the three changes;
- runs each phrase against Indeed and LinkedIn via
  [JobSpy](https://github.com/speedyapply/JobSpy);
- dedupes results against URLs already in `evaluations.db`;
- pre-selects the N job ads worth evaluating out of the L discovered;
- lists the result, or with `--evaluate` runs the selected N through `evaluate_job()`.

`discovery.discover_jobs()` owns the seams between the stages. It resolves the rubric once
before discovery, because `evaluate_job` loads the rubric per job and an unpinned recompile
mid-run would prescore against one rubric and score against another. It supplies
`known_job_openings` from `storage.list_evaluated_job_openings()`, prints
`format_preselection()`, and tries a job ad's `alternates` before paying for
`find_company_posting_url()`.

### Fallback when a URL cannot be scraped

Some boards (LinkedIn, Ashby, and other JS-rendered or login-walled pages) reliably fail
Tavily extraction, and `scrape_post()` raises `ScrapeError`. Discovery first retries the
duplicate-collapse `alternates`, other urls this run already found for the same job
opening. It then searches the web for the same posting's full description published by the
same company, excluding third-party re-poster domains (Indeed, Glassdoor, jobleads) whose
copies tend to be thin or stale. If a match is found, typically the company's own careers
page or ATS, `evaluate_job()` runs against that URL instead. Otherwise the job ad is
skipped.

## Pre-selection

`jobsearch/preselection.py` sits between discovery and evaluation. Discovery returns
roughly 100 job ads (4-10 query phrases multiplied by `--max-results`), and evaluating one
costs a Tavily extract, 3-5 LLM calls and up to 3 routing calls. Pre-selection is the cut
between the two, made on the data JobSpy already returned:

```
DISCOVERY  ──►  PRE-SELECTION  ──►  EVALUATION
    L               N (10)             N
```

```
preselect(job_ads, n, rubric, resume, preferences, known_job_openings)
  │
  ├─ stage 1: deterministic, free, no LLM, any L
  │    drop_stale             date_posted older than MAX_AGE_DAYS; a missing date is kept
  │    collapse_duplicates    one job opening = one normalized (company, title); the
  │                           surviving url is the one likeliest to scrape (own careers
  │                           page > source board > re-poster), the rest become its
  │                           "alternates"
  │    drop_already_evaluated the same job opening already has a saved evaluation
  │    prescore_job_ads       regex-apply the rubric to the untruncated ad; an annotation
  │                           for stage 2, never a filter
  │
  └─ stage 2: one LLM call, whatever L is
       every survivor is presented with an integer id, its fields, its prescore and an
       excerpt of its description; the reply names the N ids to evaluate, with a reason each

  => {"selected", "dropped", "stats"}; every input ad is in exactly one of the first two
```

### Invariants

**The LLM call count does not grow with L.** `select_batch` is one call and must never be
chunked.

**Every dropped ad is reported with the stage that dropped it**, whether the run is listing
or evaluating.

A reply naming out-of-range or repeated ids is policed the way `_validate_queries` polices
a query reply. A reply naming too few ids is backfilled by descending prescore, so the
stage returns up to N: exactly N once at least N ads survive stage 1, fewer only when stage
1 leaves fewer than N candidates to choose from.

The module opens no database and reads no files. Rubric, resume, preferences and
`known_job_openings` are passed in, which is what keeps stage 1 unit-testable offline in
`tests/unit/test_preselection.py`.

`AGGREGATOR_DOMAINS` lives in `preselection.py` rather than `discovery.py` because this
module ranks those domains when picking a collapse's survivor.

### What pre-selection deliberately does not filter

Location and work mode are not pre-selection filters. Remoteness reaches the score later
through the commute step, on a posting whose office and in-office days have been read from
the full ad rather than from JobSpy's `is_remote` flag.

`--no-preselect` skips the stage and its one LLM call, evaluating the first `--limit` job
ads in discovery order. That is the path the pipeline took before pre-selection existed, so
the two are comparable on one job ad set.

## Storage

SQLite, two tables:

- `evaluations`, one row per normalized URL
- `evaluation_criteria`, one row per rubric criterion per evaluation, replaced wholesale on
  every re-save

`normalize_url()` strips tracking params (`trk`, `utm_*`) and trailing slashes, so the same
posting under different tracking links dedupes to one row.

Schema upgrades go through `_MIGRATIONS` (`PRAGMA table_info` plus conditional `ALTER TABLE
ADD COLUMN`). They are never destructive; existing rows survive.

User-tracked fields (`reviewed`, `application_status`, `status_reason`, `notes`) are
preserved across re-evaluation of the same URL. Only pipeline-derived fields and
`evaluation_criteria` are overwritten.

### Querying the database

No CLI wrapper yet (see [roadmap.md](roadmap.md)), so this is raw SQL and one Python call:

| Task | Command |
|------|---------|
| List the top-scoring saved jobs | `sqlite3 data/evaluations.db "SELECT job_title, company, compatibility_score FROM evaluations ORDER BY compatibility_score DESC LIMIT 5;"` |
| Show everything saved for one job | `sqlite3 data/evaluations.db "SELECT * FROM evaluations WHERE url = '<url>';"` |
| Filter saved jobs | `sqlite3 data/evaluations.db "SELECT job_title, company FROM evaluations WHERE is_remote = 1 AND compatibility_score > 75;"` |
| Mark a job reviewed, applied or discarded | `storage.update_review(url, reviewed=True, application_status="applied", notes="...")` |

## Files on disk

```
evaluate_job_post.py    CLI entrypoint: evaluate one posting by URL
discover_jobs.py        CLI entrypoint: find, pre-select and optionally score new postings
jobsearch/              the package: scrape, commute, rubric, evaluation, discovery,
                        pre-selection, storage, LLM wrapper, config
evals/                  the eval harness and its hand-curated case set
tests/                  unit/ (offline) and e2e/ (live, needs keys)
scripts/                check_setup.py, recompile_rubric.py
data/                   personalization files and generated caches
docs/                   architecture, evals, roadmap
```

| File | Written by | In git | Notes |
|------|-----------|--------|-------|
| `.env` | user | template only | real values are local-only |
| `data/resume.md` | user | template only | real content is local-only |
| `data/job_preferences.md` | user | template only | `## Scoring Notes` is passed to the LLM verbatim |
| `data/compatibility_rubric.json` | `compile_rubric()` | no | regenerated when resume or preferences change |
| `data/search_queries.json` | `jobsearch/discovery.py` | no | cached search phrases |
| `data/evaluations.db` | `storage.save_evaluation()` | no | one row per URL plus per-criterion breakdown; real usage only, never eval runs |
| `evals/cases.json` | `capture.py` / `draft.py`, then hand-edited | no | ground truth; `"verified": false` until reviewed |
| `evals/ads/*.json` | `capture.py` | no | a posting's raw page text plus extracted fields, so a case outlives the posting |
| `evals/runs/*.json` | `run_evals.py` | no | one snapshot per run: metrics, rubric hash, model ids |

## Personalization files stay out of git

`.env`, `data/resume.md` and `data/job_preferences.md` are committed as generic templates
but have the **skip-worktree** bit set. Once edited with real keys, resume or preferences,
those edits do not appear in `git status` or `git diff` and are not picked up by
`git add -A`, so personal data and API keys cannot be committed by accident.

Changing a template itself requires re-enabling tracking first, for whichever of the three
files (`.env`, `data/resume.md`, `data/job_preferences.md`) is being changed:

```
git update-index --no-skip-worktree <file>
# edit, commit the template change
git update-index --skip-worktree <file>
```

## Cost and caching

Two independent cache layers. They invalidate against different things and should not be
conflated:

- **Rubric cache.** `load_or_compile_rubric()` invalidates the rubric against `resume.md`
  and `job_preferences.md` file hashes. The hash is whole-file, so any edit, including one
  to `## Scoring Notes`, triggers a recompile. `compile_rubric()` runs an agentic drafting
  loop plus a reflection pass and is the most expensive operation in the codebase.
- **Evaluation cache.** `storage.rubric_content_hash(rubric)` invalidates a saved job
  evaluation against the compiled rubric's `criteria` and `scoring_guidance`. A saved
  evaluation is reused when the same normalized URL is requested and that hash is
  unchanged, which is a pure SQLite read with no API cost. `--force` bypasses it.

`rubric_content_hash` must stay in sync with everything `compatibility_score()` reads from
the rubric. If a field is added to the rubric and used in that prompt, it has to be
included in the hash, or saved evaluations go stale without being invalidated.

Geocoding and routing use OpenRouteService, a free external API, not an LLM.

### Cost per discovery run

| Stage | Cost |
|-------|------|
| Search queries | 1 LLM call, cached until `resume.md`, `job_preferences.md` or `HOME_ADDRESS` change |
| JobSpy search | No API spend. `--no-linkedin-descriptions` drops one HTTP request per LinkedIn result, at the price of pre-selecting those ads on their title alone |
| Pre-selection stage 1 | Free: dates, url domains and regex, no LLM |
| Pre-selection stage 2 | Exactly 1 LLM call, whatever L is. `--no-preselect` skips it |
| Evaluation | Per selected job ad: 1 Tavily extract, 3-5 LLM calls, up to 3 routing calls |

Listing job ads without `--evaluate` costs one LLM call where it previously cost none.
`--no-preselect` is the zero-call listing.

Eval-run costs are in [evals.md](evals.md).
