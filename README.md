# job-search-agent

A personal job-search pipeline: given a job posting URL, it scrapes the ad, scores the
commute against your home address, scores how well the role matches your resume and
stated preferences, and saves the result so you never pay to re-evaluate the same job
twice. The code itself carries no personal data — everything specific to *you*
(resume, preferences, scoring rules) lives in two editable Markdown files, so the same
tool works for any candidate/role.

## How it works

```
                              evaluate_job(url)
                                     │
                     ┌───────────────┴───────────────┐
                     │ already saved for this URL,    │
                     │ and rubric unchanged since?     │
                     └───────────────┬───────────────┘
                     yes ◄───────────┴───────────► no
                      │                             │
                      │                             ▼
                      │                     scrape_post(url)
                      │                (Tavily fetch + 1 LLM call to
                      │                 extract title/company/location/description)
                      │                             │
                      │                             ▼
                      │                     commute_score(...)
                      │                (1-3 LLM calls to locate the office +
                      │                 ORS geocoding/routing, skipped if remote)
                      │                             │
                      │                             ▼
                      │                     compatibility_score(...)
                      │                (rubric regex match: free, deterministic +
                      │                 1 LLM call for the final 0-100 judgment)
                      │                             │
                      │                             ▼
                      │                     summarize_evaluation(...)
                      │                       (1 LLM call: works well / doesn't)
                      │                             │
                      │                             ▼
                      │                     storage.save_evaluation()
                      │                        (SQLite upsert, instant)
                      └───────────────┬─────────────┘
                                      ▼
                          printed evaluation + saved row
```

The **compatibility rubric** (the set of criteria a job is scored against) is itself
LLM-generated, but only once per resume/preferences version — not per job:

```
data/resume.md  ──┐
                   ├──► compile_rubric() ──► data/compatibility_rubric.json ──► regex-matched
data/job_preferences.md ─┘   (draft + reflect,        (cached, gitignored)      against every
                               ~agentic LLM loop)                                job description
```

`compile_rubric()` only re-runs when `resume.md` or `job_preferences.md` actually
change (content-hash check) — every regular `evaluate_job()` call reuses the cached
rubric and just regex-matches against it, which costs nothing.

### Discovery: `discover_jobs.py`

`discover_jobs.py` finds new candidate job URLs instead of requiring you to paste one
in: it asks an LLM to derive search query phrases from `resume.md` + `job_preferences.md`
(cached in `data/search_queries.json`, invalidated the same way the rubric is), runs
each query against Indeed + LinkedIn via the [JobSpy](https://github.com/speedyapply/JobSpy)
library, dedupes against URLs already in `evaluations.db`, and either lists the new
candidates or (with `--evaluate`) runs them through `evaluate_job()`.

**Fallback when a discovered URL can't be scraped.** Some job boards (LinkedIn, Ashby,
and other JS-rendered/login-walled pages) reliably fail Tavily extraction —
`scrape_post()` raises `ScrapeError` in that case. `discover_jobs.py` catches it and
searches the web with the candidate's known company + title (still Tavily: 1 search +
up to 3 extracts + 1 LLM call to disambiguate) for a page that contains that exact
posting's own full description, published by that exact company — explicitly
excluding third-party re-poster domains (Indeed, Glassdoor, jobleads, bebee, ...),
since those tend to carry a thin/stale copy that scores worse than no evaluation at
all. If a genuine match is found (typically the company's own careers page or their
ATS, e.g. Greenhouse/Ashby-hosted-on-their-own-domain), `evaluate_job()` runs against
that URL instead. If nothing on the company's own site matches — same-title postings
at unrelated companies and generic "here are our open roles" listing pages are both
deliberately rejected — the candidate is skipped rather than evaluated against
low-quality content.

## Setup

1. Clone the repo, then fill in `.env` (already present as an empty template — see
   [Personalization files](#personalization-files-env-resumemd-job_preferencesmd)
   below for why editing it won't show up in `git status`):
   ```
   ANTHROPIC_API_KEY=   # LLM calls (aisuite -> Anthropic)
   TAVILY_API_KEY=      # web search/extraction (scraping job ads + office addresses)
   GROQ_API_KEY=        # only used by scripts/check_setup.py, not the main pipeline
   HOME_ADDRESS=        # your address, commute times are computed from here
   ORS_API_KEY=         # OpenRouteService, for geocoding + driving-time routing
   ```
2. Edit `data/resume.md` and `data/job_preferences.md` with your own resume and
   preferences (see format below).
3. Run everything inside the provided container (the host machine isn't expected to
   have the Python dependencies installed):
   ```
   docker compose up -d
   docker compose exec notebook python3 evaluate_job_post.py <job-url>
   ```
4. Sanity-check your API keys are wired up correctly:
   ```
   docker compose exec notebook python3 scripts/check_setup.py
   ```

## Use cases & common interactions

| I want to...                                          | Run this                                                          |
|--------------------------------------------------------|---------------------------------------------------------------------|
| Evaluate a job posting                                 | `python evaluate_job_post.py <url>`                                 |
| Find new candidate jobs (lists URLs, doesn't score)     | `python discover_jobs.py`                                           |
| Find and score new candidate jobs                       | `python discover_jobs.py --evaluate` (add `--limit N` to cap how many get scored) |
| Force a fresh evaluation (ignore the saved cache)       | `python evaluate_job_post.py <url> --force`                         |
| See the 5 highest-scoring saved jobs                    | `sqlite3 data/evaluations.db "SELECT job_title, company, compatibility_score FROM evaluations ORDER BY compatibility_score DESC LIMIT 5;"` |
| See everything saved for one job                        | `sqlite3 data/evaluations.db "SELECT * FROM evaluations WHERE url = '<url>';"` |
| Filter saved jobs (e.g. remote, score > 75)             | `sqlite3 data/evaluations.db "SELECT job_title, company FROM evaluations WHERE is_remote = 1 AND compatibility_score > 75;"` |
| Mark a job reviewed / applied / discarded, add a note   | Python: `import storage; storage.update_review(url, reviewed=True, application_status="applied", notes="phone screen scheduled")` |
| Add/refresh one eval ground-truth case from a real job  | `python evals/add_case.py <url>`                                    |
| Rebuild the *entire* eval suite from live pipeline runs | `python evals/regenerate_cases.py` — see [cost warning](#what-eats-tokens-and-what-doesnt) below, this is expensive |
| Check pipeline accuracy against hand-verified ground truth | `python evals/run_evals.py --verified-only`                      |

There is currently no CLI for the "browse saved jobs" and "mark reviewed/applied" rows
above — they're plain SQL / a Python call. See
[Future Improvements](#future-improvements).

## Project layout

```
evaluate_job_post.py         entry point: scrape -> commute -> compatibility -> summary -> save
discover_jobs.py             derive search queries from resume/preferences, search Indeed +
                              LinkedIn (JobSpy), surface/evaluate new candidate job URLs
commute.py                   office-address lookup + commute-time scoring (OpenRouteService)
llm.py                       thin aisuite wrapper: one-shot JSON calls + an agentic tool-call loop
storage.py                   SQLite persistence, URL normalization, cache-hash helpers
data/
  resume.md                  user-provided
  job_preferences.md         user-provided
  compatibility_rubric.json  generated, gitignored
  search_queries.json        generated, gitignored (discover_jobs.py's cached query set)
  evaluations.db             generated, gitignored
evals/
  cases.json                 generated (from real runs), gitignored, hand-edited afterward
  add_case.py                add/update one eval case from a saved evaluation
  regenerate_cases.py        bulk-rebuild every case from live pipeline runs
  run_evals.py               pipeline-health checker: which step regressed, not just pass/fail
scripts/
  check_setup.py             smoke-test API keys / provider wiring
docs/plan.md                 original course-assignment scope note (historical, not living docs)
```

## Artifacts: what you provide vs. what gets generated

| File                              | Who writes it              | Tracked in git? | Notes |
|------------------------------------|-----------------------------|------------------|-------|
| `.env`                             | you                          | yes, as an empty template | real values are local-only, see below |
| `data/resume.md`                   | you                          | yes, as a generic template | your real content is local-only, see below |
| `data/job_preferences.md`          | you                          | yes, as a generic template | free-text `## Scoring Notes` section is passed to the LLM verbatim |
| `data/compatibility_rubric.json`   | `compile_rubric()`           | no (gitignored) | regenerated automatically when resume/preferences change |
| `data/evaluations.db`              | `storage.save_evaluation()`  | no (gitignored) | one row per job URL + per-criterion breakdown |
| `evals/cases.json`                 | `evals/add_case.py` / `regenerate_cases.py`, then you by hand | no (gitignored) | `"verified": false` until a human reviews the expected values |
| `evals/cases.json.bak`             | `evals/regenerate_cases.py`  | no | last pre-regeneration snapshot, single backup, not a history |

### Personalization files: `.env`, `resume.md`, `job_preferences.md`

These three files are tracked in git (so `git clone` gives you a ready-to-fill
template) but have the **skip-worktree** bit set. That means once you edit them with
your real keys/resume/preferences, `git status` and `git diff` will not show those
edits, and a `git add -A`/`git commit -a` won't pick them up — your personal data and
API keys can't accidentally get committed. If you ever need to change the *template*
itself (e.g. add a new required env var for everyone), you have to explicitly
re-enable tracking first:
```
git update-index --no-skip-worktree .env
# edit, commit the template change
git update-index --skip-worktree .env
```

## What eats tokens, and what doesn't

**Free (no LLM/API cost):**
- Reusing a saved evaluation — `evaluate_job(url)` without `--force`, when the URL was
  already evaluated and the rubric hasn't changed, is a pure SQLite read.
- `evaluate_rubric()` — matching a job description against the rubric is plain regex,
  no LLM involved. Only the final 0-100 synthesis step is an LLM call.
- Geocoding/routing (OpenRouteService) — a paid-tier-free external API, not an LLM.

**One job's worth of API calls (rubric already cached, cache miss on the job itself):**

| Step | Calls |
|---|---|
| `scrape_post` | 1 Tavily extract + 1 LLM call |
| `commute_score` | 1 LLM call to get on-site days/week. If that's 0 (remote), stop here. Otherwise, 1 more LLM call to classify the location. If it's not already a full street address, 1 Tavily search + up to 3 Tavily extracts + 1 more LLM call to resolve it. |
| `compatibility_score` | 1 LLM call (rubric matching itself is free regex) |
| `summarize_evaluation` | 1 LLM call |

So a single fresh evaluation costs **4 LLM calls for a remote job, up to 6 for an
on-site/hybrid one whose office address needs a web search**, plus 0-2 Tavily search
operations. Job description length affects input token count, not call count.

**The expensive one: `compile_rubric()`.** This runs `draft_rubric()`, an *agentic*
loop where the LLM proposes criteria and calls a `test_regex` tool to validate each
pattern — up to 30 round trips — followed by a `reflect_on_rubric()` critique pass.
It only runs when `resume.md` or `job_preferences.md` content changes, but when it
does, it dwarfs the cost of evaluating any number of jobs against the cached result.

**Bulk operations multiply this per-job cost.** `evals/regenerate_cases.py` calls
`evaluate_job(url, force=True)` for every case URL, which skips the cache
unconditionally — N jobs × 4-6 LLM calls, every time it's run, even if only one job's
data actually needed refreshing. See the first item in
[Future Improvements](#future-improvements).

**`discover_jobs.py --evaluate` adds a per-candidate cost on top of the above.** Query
derivation is 1 LLM call, cached until resume/preferences change. Each JobSpy search
itself is free (no Tavily/LLM involved). Any candidate whose URL can't be scraped adds
1 Tavily search + up to 3 Tavily extracts + 1 LLM call for the company-site fallback
lookup — before the normal per-job evaluation cost above even starts (and that only
happens if the fallback finds a genuine match; otherwise the candidate is skipped for
free).

## Evals

`evals/run_evals.py` runs the real pipeline against `evals/cases.json` and checks
results against hand-set ranges/substrings per pipeline stage (`days_on_office`,
`address`, `commute_score`, `compatibility_score`, `criteria_matched`,
`criteria_unmatched`), then ranks stages worst-first so you know what to fix next —
not just which cases pass. Only cases with `"verified": true` are trustworthy ground
truth; anything auto-drafted by `add_case.py`/`regenerate_cases.py` should be reviewed
by hand before you rely on it (`--verified-only` filters to just those).

---

## Future Improvements

Items below require touching code, not just documentation or configuration.

1. **The evaluation cache still can't be refreshed at a finer grain than "one whole
   job."** `evaluate_job(url, force=True)` always re-scrapes, re-computes commute,
   *and* re-judges compatibility together — there's no way to refresh just the
   commute score (e.g. after a `HOME_ADDRESS` change) or just the compatibility
   judgment (e.g. after a rubric tweak) using the job description already sitting in
   `evaluations.db`. This is the general form of the "re-run everything when
   something small changes" problem: fixing it well means splitting the cache into
   independent layers — a scrape-freshness check (re-scrape only if never
   scraped/stale), the rubric-freshness check that already exists via
   `rubric_content_hash` (re-run just `compatibility_score` +
   `summarize_evaluation` off the stored description), and a new home-address/
   commute-config check (re-run just `commute_score`) — so a single-dimension
   change only pays for what it actually invalidates, instead of every saved job
   paying for a full re-scrape + re-judgment.

2. **No CLI for the two most natural "browse my results" use cases.** Filtering saved
   evaluations (by score, remote status, matched criteria) and updating
   `reviewed`/`application_status`/`notes` (`storage.update_review`,
   `storage.py:233`) are both only reachable via raw `sqlite3` or a Python REPL today
   — despite being, per the project's own original goal, the main reason to have a
   database at all ("select all remote jobs, all jobs > 75, all C++..."). A small
   `query.py`/`review.py` script wrapping common filters and `update_review` would
   remove the need to hand-write SQL for routine use.

3. **`evals/regenerate_cases.py` has no partial/incremental mode.** It always
   force-reruns every known URL (`evals/regenerate_cases.py:60-82`). A `--only-stale`
   mode (only re-run cases whose saved `rubric_hash` no longer matches the current
   rubric) would make routine rubric tweaks cheap to validate instead of an
   all-or-nothing, full-token-cost operation every time.
