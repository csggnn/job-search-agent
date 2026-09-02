# job-search-agent

**job-search-agent** is an agentic AI tool which streamlines job search. It takes over
query crafting, searching multiple engines, ad-by-ad validation, evaluation and ranking,
so that you can focus on the ads most promising for your own skills, preferences and commute.

Personal project, started as an agentic-coding exercise (`docs/plan.md`).

## How it's commonly used

- The candidate describes their profile and preferences in two Markdown files.
- The candidate asks for the five job ads that best fit **them**.

No candidate data lives in code. Resume, preferences and scoring rules are the two Markdown
files, so the same tool works for any candidate and role.

## Key features

- Drafts search queries from your CV and preferences, and runs them across multiple job platforms and engines.
- Pre-filters, dedupes and pre-ranks results before anything expensive runs.
- Scores each ad against your preferences, including real driving time weighted by days on
  site.
- Keeps every evaluation in a database, so no posting is scored twice.

## How you use it

Describe yourself once, in `data/resume.md` and `data/job_preferences.md`. Then ask for the
jobs worth your time.

> **Work in progress.** Combined compatibility-and-commute ranking is unfinished and there
> is no shortlist command yet. For now, ask your harness to run
> `discover_jobs.py --evaluate --limit 20` and report the five highest-scoring.

Underneath, that run looks like this:

```
$ python discover_jobs.py --evaluate --limit 20

12 new job ad(s):

- Senior Backend Engineer at Acme Robotics (Zurich, Switzerland)
  https://example-ats.com/acme/senior-backend-engineer
  matched: backend engineer zurich
...

Evaluating Position: Senior Backend Engineer at Acme Robotics
Commute score: 41.5 min (2 days/week, Bahnhofstrasse 1, 8001 Zurich, Switzerland)
Compatibility score: 78/100
Works well: Backend-heavy role in robotics; Python and distributed systems match.
Does not work: Requires on-call rotation; team language is German.
Reviewed: no
Application status: new
```

Without `--evaluate` it lists what it found and stops, so you can see the pre-selection
before paying for it.

A single posting can also be scored directly, the manual way into the same pipeline.
Re-running a URL is a database read with no API calls:

```
$ python evaluate_job_post.py <url>
$ python evaluate_job_post.py <url>          # (cached from 2026-08-30T14:02:11)
$ python evaluate_job_post.py <url> --force  # re-scrape and re-score
```

## What you need

Five credentials and a container runtime. The host machine is not expected to have the
Python dependencies installed; everything runs inside the provided container.

| Variable | Used for | Notes |
|----------|----------|-------|
| `ANTHROPIC_API_KEY` | All LLM calls, via aisuite | Paid |
| `TAVILY_API_KEY` | Web search and extraction (job ads, office addresses) | Free tier available |
| `ORS_API_KEY` | OpenRouteService geocoding and driving-time routing | Free |
| `HOME_ADDRESS` | The address commute times are computed from | Not a key |
| `GROQ_API_KEY` | Only `scripts/check_setup.py`, not the main pipeline | Free tier available |

## Setup

1. Clone the repo and fill in `.env`, which is present as a template. See
   [Personalization files](#personalization-files) for why edits to it do not show up in
   `git status`.
2. Edit `data/resume.md` and `data/job_preferences.md`. Each file documents its own format.
3. Start the container and evaluate a posting:
   ```
   podman-compose up -d
   podman-compose exec job-search python3 evaluate_job_post.py <job-url>
   ```
4. Sanity-check that the API keys are wired up:
   ```
   podman-compose exec job-search python3 scripts/check_setup.py
   ```

All commands below are shown bare. Prefix each with
`podman-compose exec job-search python3` to run it.

## Commands

### Evaluating and discovering

| Task | Command |
|------|---------|
| Evaluate a posting | `evaluate_job_post.py <url>` |
| Force a fresh evaluation, ignoring the cache | `evaluate_job_post.py <url> --force` |
| List new job ads, pre-selected, no scoring | `discover_jobs.py` |
| List new job ads without pre-selecting, no LLM call | `discover_jobs.py --no-preselect` |
| Find and score new job ads | `discover_jobs.py --evaluate` |
| Set how many ads are pre-selected and scored | `discover_jobs.py --limit N` (default 10) |
| Set how many results each query returns | `discover_jobs.py --max-results N` |
| Skip fetching LinkedIn descriptions | `discover_jobs.py --no-linkedin-descriptions` |
| Ignore the cached search queries and recompile them | `discover_jobs.py --force` |
| Print intermediate search details | `discover_jobs.py --debug` |
| Force-recompile the rubric, bypassing the file-hash cache | `scripts/recompile_rubric.py` (`--if-changed` to respect it) |

### Reading the results

Browsing saved jobs and marking them reviewed or applied have no CLI wrapper yet. See
[docs/roadmap.md](docs/roadmap.md).

| Task | Command |
|------|---------|
| List the top-scoring saved jobs | `sqlite3 data/evaluations.db "SELECT job_title, company, compatibility_score FROM evaluations ORDER BY compatibility_score DESC LIMIT 5;"` |
| Show everything saved for one job | `sqlite3 data/evaluations.db "SELECT * FROM evaluations WHERE url = '<url>';"` |
| Filter saved jobs | `sqlite3 data/evaluations.db "SELECT job_title, company FROM evaluations WHERE is_remote = 1 AND compatibility_score > 75;"` |
| Mark a job reviewed, applied or discarded | `storage.update_review(url, reviewed=True, application_status="applied", notes="...")` |

### Tests and evals

| Task | Command |
|------|---------|
| Offline unit tests | `-m unittest discover -s tests/unit` |
| Live end-to-end smoke test, needs keys | `-m unittest discover -s tests/e2e` |
| Save a posting as a replayable eval ad | `evals/capture.py <url>` |
| Review the eval set before picking cases | `evals/capture.py --list-cases` |
| Pre-fill a case's ground truth | `evals/draft.py <url\|NAME>` (`--all` for every incomplete case) |
| Check the rubric's regexes, free, no network | `evals/run_evals.py --criteria-only` |
| Check accuracy against verified ground truth | `evals/run_evals.py --verified-only` |
| See whether a change helped | `evals/run_evals.py --compare` |

## Layout

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

Per-module descriptions are in [docs/architecture.md](docs/architecture.md).

### Data and generated files

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

### Personalization files

`.env`, `data/resume.md` and `data/job_preferences.md` are committed as generic templates
but have the **skip-worktree** bit set. Once edited with real keys, resume or preferences,
those edits do not appear in `git status` or `git diff` and are not picked up by
`git add -A`, so personal data and API keys cannot be committed by accident.

Changing the template itself requires re-enabling tracking first:

```
git update-index --no-skip-worktree .env
# edit, commit the template change
git update-index --skip-worktree .env
```

## Documentation

| Document | Answers |
|----------|---------|
| [docs/architecture.md](docs/architecture.md) | How the pipeline, rubric, discovery, pre-selection and caching work |
| [docs/evals.md](docs/evals.md) | How the tests and eval harness work, and what the metrics mean |
| [docs/roadmap.md](docs/roadmap.md) | Known limitations that need code changes |

## License

MIT. See [LICENSE](LICENSE).
