# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

Descriptive architecture lives in [docs/architecture.md](docs/architecture.md) and
[docs/evals.md](docs/evals.md). This file holds the rules and invariants that constrain
changes.

## What this is

A job-search evaluation pipeline: given a job posting URL, it scrapes the ad, scores the
commute against the home address in the active profile's `job_preferences.md`, scores fit
against a candidate's resume and preferences via an LLM-drafted regex rubric, and caches the result
in SQLite so the same URL is never re-evaluated for free.

## Rules

**The code is candidate-agnostic.** No resume, domain or role content may live in any
`.py` file. All personalization flows through the active profile's `resume.md` and
`job_preferences.md`. `scoring_guidance` (the verbatim `## Scoring Notes` section) is
the mechanism that keeps domain-specific scoring logic out of code.

**The database is for usage; the eval set is for eval.** A profile's `evaluations.db`
records real evaluations and grows on its own. The eval set is the profile's `evals/`
directory (`cases.json`, `ads/`, `runs/`); `evals/` at the checkout root holds eval code
only. The eval set is curated by hand and stays small enough to
hold verified ground truth. Eval code may import only the pure helpers from
`jobsearch.storage` (`normalize_url`, `rubric_content_hash`), never `get_*`, `save_*` or
`list_*`, which open the database. Nothing under `evals/` may read or write a
profile's `evaluations.db`, and the eval set must never be populated by sweeping it.

**Stored ads are data, not code.** The `ads/` directory of a profile's eval set holds verbatim
scraped job-ad text. It must
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

**Profile paths are resolved on use, never at import.** Every path to profile data comes
from `config.profile_dir()` or a function built on it. Every entry point calls
`config.add_profile_argument(parser)` and `config.apply_profile_args(args)` before any
profile path is used. Code never branches on the profile name.

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
scripts/profile.sh reset-default   # host or container
```

Every entry point runs on `profiles/personal/` unless given `--default-profile`, which
selects `profiles/default/`. `--scratch` runs on a temporary copy of the selected profile,
deleted at exit. Test runs in a checkout holding real personal data use `--scratch`.

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
against a profile's `evaluations.db`. Marking a job reviewed, applied or discarded is a direct
call to `storage.update_review(url, ...)`, also with no CLI wrapper yet.

## Profiles and keys

API keys live in `~/.config/job-search-agent/.env`, outside every checkout. The container
mounts that directory read-only at `/config`, and `config.py` loads `/config/.env`.
`.env.example` names every key in `config.API_KEYS`; a unit test enforces it.

```
profiles/
  default/    committed sample candidate: resume.md, job_preferences.md
              generated evaluations.db, compatibility_rubric.json, search_queries.json
              and evals/ are gitignored
  personal/   the user's candidate, same file names, gitignored as a whole
```

No personal file is tracked, so no git index flag is needed. `git clean -x` deletes
`profiles/personal/`. Do not run it in a checkout holding real personal data. A new
worktree has no personal profile; `cp -r ../../profiles/personal profiles/` copies the main
checkout's.

The sample candidate must keep every section the code parses (`## Location`,
`## Home Address`, `## Scoring Notes`) filled in, with a geocodable home address and no
placeholder text. `DefaultDataTest` in `tests/unit/test_units.py` checks
`profiles/default/` whichever profile is active.

`profiles/personal/`, the generated files and `evals/` of `profiles/default/`, and `.env`
are gitignored.

## Issue tracking

Issues are filed in Linear (team Csggnn) and mirrored to GitHub. Do not create GitHub
issues directly.
