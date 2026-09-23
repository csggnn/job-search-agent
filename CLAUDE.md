# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

Descriptive architecture lives in [docs/architecture.md](docs/architecture.md) and
[docs/evals.md](docs/evals.md). This file holds the rules and invariants that constrain
changes.

## What this is

A job-search evaluation pipeline: given a job posting URL, it scrapes the ad, scores the
commute against the home address in `data/job_preferences.md`, scores fit against a
candidate's resume and preferences via an LLM-drafted regex rubric, and caches the result
in SQLite so the same URL is never re-evaluated for free.

## Rules

**The code is candidate-agnostic.** No resume, domain or role content may live in any
`.py` file. All personalization flows through `data/resume.md` and
`data/job_preferences.md`. `scoring_guidance` (the verbatim `## Scoring Notes` section) is
the mechanism that keeps domain-specific scoring logic out of code.

**The database is for usage; `evals/` is for eval.** `data/evaluations.db` records real
evaluations and grows on its own. The eval set is curated by hand and stays small enough to
hold verified ground truth. Eval code may import only the pure helpers from
`jobsearch.storage` (`normalize_url`, `rubric_content_hash`), never `get_*`, `save_*` or
`list_*`, which open the database. Nothing under `evals/` may read or write
`data/evaluations.db`, and the eval set must never be populated by sweeping it.

**Stored ads are data, not code.** `evals/ads/` holds verbatim scraped job-ad text. It must
never be inlined into a `.py` file.

**Keep the docs current.** When you change a file's behavior or logic, check whether
`README.md`, `docs/architecture.md` or `docs/evals.md` documents that behavior and update it
in the same change. The pipeline diagrams, cost tables and metric descriptions are meant to
stay accurate, not aspirational.

**Do not cite line numbers** in documentation or issues. Name the file and the function.

## Invariants

**Pre-selection makes one LLM call regardless of L.** `select_batch` must never be chunked.

**Every dropped ad is reported with the stage that dropped it**, whether listing or
evaluating.

**`jobsearch/preselection.py` opens no database and reads no files.** Rubric, resume,
preferences and `known_job_openings` are passed in. This is what keeps stage 1
unit-testable offline.

**`storage.rubric_content_hash(rubric)` must stay in sync with everything
`compatibility_score()` reads from the rubric.** If a new field is added to the rubric and
used in that prompt, it must be included in this hash, or saved evaluations will silently
go stale without being invalidated. Do not conflate this with the rubric cache, which
invalidates against `resume.md` and `job_preferences.md` file hashes.

**Eval ground truth is one value per step, never a `[lo, hi]` range.** The accepted margin
belongs to the harness (`--tolerance-*`), not the case data. `dataset.py`'s
`EXPECTED_TYPES` and `validate_expected` enforce this.

**Eval `criteria` labels use exact rubric criterion names.** Unknown names sort to
`stale_label` or `unlabeled` and are excluded from accuracy rather than scored.

**Every caller of the rubric composes the same `match_text()`** (title, location,
description). `evals/draft.py` must match `evals/run_evals.py` here, or drafted labels
disagree with the scored ones.

**Callers that must not trigger a live agentic recompile** use `load_rubric()` plus
`rubric_is_stale()` directly, not `load_or_compile_rubric()`. `evals/run_evals.py` resolves
one rubric per run; a mid-run recompile would score different cases against different
rubrics.

**Schema upgrades go through `_MIGRATIONS`** (`PRAGMA table_info` plus conditional
`ALTER TABLE ADD COLUMN`). Never destructive; existing rows survive. User-tracked fields
(`reviewed`, `application_status`, `status_reason`, `notes`) are preserved across
re-evaluation of the same URL.

**`combined_score` is computed by `ranking.rank_evaluations()` and never persisted.** It is
derived from `compatibility_score` and `commute_score` on every rank, so the modifier
constants can change with no cache to invalidate. Do not add a stored column for it.

**`ranking.propose()` excludes `application_status` `applied` and `discarded`**, and every
input row appears exactly once across `proposed` and `excluded`.

## Commands

The host machine has no Python deps installed. Everything runs inside the podman compose
container.

```
podman-compose up -d
podman-compose exec job-search python3 evaluate_job_post.py <job-url>
podman-compose exec job-search python3 evaluate_job_post.py <job-url> --force
podman-compose exec job-search python3 discover_jobs.py [--evaluate] [--limit N] [--no-preselect]
podman-compose exec job-search python3 scripts/check_setup.py
```

Tests use stdlib `unittest`; no linter is configured.

```
podman-compose exec job-search python3 -m unittest discover -s tests/unit   # offline
podman-compose exec job-search python3 -m unittest discover -s tests/e2e    # needs keys
```

Evals:

```
podman-compose exec job-search python3 evals/capture.py <url>
podman-compose exec job-search python3 evals/capture.py --list-cases
podman-compose exec job-search python3 evals/capture.py --re-extract --all
podman-compose exec job-search python3 evals/draft.py --all
podman-compose exec job-search python3 evals/run_evals.py --criteria-only
podman-compose exec job-search python3 evals/run_evals.py --no-commute
podman-compose exec job-search python3 evals/run_evals.py --verified-only
podman-compose exec job-search python3 evals/run_evals.py --compare
```

Ad-hoc querying of saved evaluations has no dedicated script; use `sqlite3` directly
against `data/evaluations.db`. Marking a job reviewed, applied or discarded is a direct
call to `storage.update_review(url, ...)`, also with no CLI wrapper yet.

## Git-invisible files

`.env` is committed as a template. `data/resume.md` and `data/job_preferences.md` are
committed as a fictional sample candidate. The **skip-worktree** bit is local to each
checkout's index: a fresh clone and each new worktree start without it. Set it with
`git update-index --skip-worktree .env data/resume.md data/job_preferences.md` before
editing them. With the bit set, edits with real keys, resume or preferences will not show
up in `git status` or `git diff`, and will not be picked up by `git add -A`.
To change the committed version, run `git update-index --no-skip-worktree <file>`, commit,
then re-apply `git update-index --skip-worktree <file>`.

The sample candidate must keep every section the code parses (`## Location`,
`## Home Address`, `## Scoring Notes`) filled in, with a geocodable home address and no
placeholder text. `DefaultDataTest` in `tests/unit/test_units.py` checks this against the
active files.

`data/compatibility_rubric.json`, `data/search_queries.json`, `data/evaluations.db`,
`evals/cases.json`, `evals/ads/` and `evals/runs/` are gitignored entirely.

## Issue tracking

Issues are filed in Linear (team Csggnn) and mirrored to GitHub. Do not create GitHub
issues directly.
