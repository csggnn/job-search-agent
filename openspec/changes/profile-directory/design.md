# Design

## Context

The checkout holds one user's data:

```
<checkout>/
  .env                  tracked template; real keys hidden by skip-worktree
  data/
    resume.md           tracked template; real content hidden by skip-worktree
    job_preferences.md  tracked template; real content hidden by skip-worktree
    evaluations.db      gitignored
    compatibility_rubric.json, search_queries.json   gitignored
  evals/
    *.py                eval code
    cases.json, ads/, runs/   gitignored
```

Each part of this layout constrains the design:
- `.env` is a tracked template holding key names with no values. The user is instructed to
  set skip-worktree on it before adding real keys. Each checkout holds its own copy of the
  keys.
- `resume.md` and `job_preferences.md` are tracked templates holding the example data. The
  user is instructed to set skip-worktree on them before editing. Removing them from the
  index deletes the user's edited copy in each checkout that pulls the removal.
- The skip-worktree bit is stored in each checkout's index. A clone or a new worktree
  starts without it.
- The eval set sits beside the eval code in `evals/`, while all other user data is in
  `data/`.
- A checkout has one `data/`, so it holds either the example data or personal data at a
  time.

## Goals / Non-Goals

**Goals:**

Outcomes: see proposal.md, What Changes.

- Migration preserves every existing user file, database row and eval case.
- The user-data check runs before any API call or write.
- Working on another user's data needs no code change and no new command argument.
- One setting determines every user data path.
- Pipeline code cannot modify API keys.
- The documented key list cannot drift from the keys the code reads.

**Non-Goals:**

- More than one user's data in a checkout.
- Committing an example eval set.
- Re-scoring stale rows (CSG-48, second half).

## Decisions

**User data lives in `data/`, gitignored as a whole.**

```
~/.config/job-search-agent/
  .env                  keys, shared by every checkout
<checkout>/
  data.example/         example user's data, committed
    resume.md
    job_preferences.md
  data/                 user data, gitignored as a whole
    resume.md, job_preferences.md
    evaluations.db, compatibility_rubric.json, search_queries.json
    evals/              cases.json, ads/, runs/
  evals/                eval code
```

`.gitignore` lists `/data/`, which matches the root `data/` only. Copying `data/` copies all
of a user's data.

Alternative considered: two data directories in one checkout, one per user, selected by a
command-line flag. Rejected: every entry point registers the flag, path resolution waits
until the flag is parsed, and every eval dataset function takes the eval directory as an
argument. Separate checkouts separate users with no code.

Alternative considered: user data in `~/.config/job-search-agent/`, next to the keys.
Rejected: every checkout of the machine shares it, so a checkout running the example data
writes the personal data.

**Every user data path derives from `config.DATA_DIR`.**
`config.EVALS_DATA_DIR` is `DATA_DIR/evals`. `evals/dataset.py` derives `CASES_PATH`,
`BACKUP_PATH`, `ADS_DIR` and `RUNS_DIR` from it. No other module names the directory.
A later change that makes the data directory configurable sets `config.DATA_DIR`.

**The example data is a committed template in `data.example/`.**
The name follows `.env.example`. No pipeline command reads it. A user creates `data/` with
`cp -r data.example data`. `DefaultDataTest` reads the template through
`config.SAMPLE_DIR`, so the unit suite checks the committed files whatever `data/` holds.

Alternative considered: reading `data.example/` when `data/` has no resume. Rejected: a run
whose personal data is missing would run on the example data without notice.

**Each entry point checks user data before any API call or write.**
`config.require_data()` raises when `RESUME_PATH` or `JOB_PREFERENCES_PATH` is missing. The
error names each missing file and the `cp -r data.example data` command. `evaluate_job_post.py`,
`discover_jobs.py`, `propose_jobs.py`, `scripts/recompile_rubric.py`, `evals/capture.py`,
`evals/draft.py` and `evals/run_evals.py` call it after parsing arguments and before any
other work. `scripts/check_setup.py` reports missing data instead of raising, continues
with its key checks, and exits before any API call when either check fails.

Alternative considered: calling the check in `storage` and in the resume and preferences
readers. Rejected: each command reaches those reads by a different path, so the guarantee
that no API call precedes the check depends on every call order staying as it is.

**Separate checkouts hold separate users' data.**
Each checkout has its own `data/`. A checkout created by `git clone` or `git worktree add`
starts without `data/`, and a run there fails until data is created. The README describes
one checkout per user: copy `data.example/` for the example user, or copy another
checkout's `data/` to work on that user's data. Writes in a checkout stay in its `data/`.

The README setup runs the example data first. Its step that adds personal data starts by
removing `data/` and creating it again from `data.example/`, so the personal database holds
no example evaluations. The README suggests a second checkout for later work on the example
data.

Alternative considered: a git `post-checkout` hook that creates `data/`. Rejected: a clone
does not install hooks, and enabling them needs `git config core.hooksPath`, an extra
setup step.

**The README notes that `data/` is not generated.**
One README sentence states that `data/` is ignored by git, holds data that cannot be
regenerated, and is backed up by copying it while no pipeline command runs.

**Keys live in `~/.config/job-search-agent/.env`, mounted read-only.**
Every checkout reads the same `.env`. The container mounts the directory read-only, so the
code cannot change keys. CI sets keys as environment variables. podman-compose 1.0.6
creates a missing bind-mount source as an empty directory, so the container starts without
`~/.config/job-search-agent/`.

Alternative considered: `.env` gitignored in the checkout. Rejected: `git clean -x` deletes
it, copying or archiving the checkout includes it, and each checkout needs its own copy.

**`.env.example` is checked against one list of key names.**
The Anthropic and Groq SDKs read their keys from the environment, so no call in the repo
names them. `config.API_KEYS` lists every key name. A unit test fails when `.env.example`
lacks one, and `check_setup.py` reads the same list. The list does not state which keys are
required: that is checked where a key is used.

Alternative considered: scanning the code for `require_env` calls. Rejected: it misses the
keys the SDKs read themselves.

## Risks / Trade-offs

- [Gitignored files are often treated as regenerable, and `data/` is not] → The README
  note on `data/`.
- [A run on the example data in the checkout that holds personal data writes its
  evaluations into the personal database] → The README describes one checkout per user. No
  code detects it.
- [The e2e tests write to the checkout's `data/`] → The e2e test docstring states it and
  directs the run to a checkout holding the example data.
- [A copied `data/` goes stale as the source checkout gains rows] → Copying again replaces
  it.
- [Copying the database while a pipeline command writes produces a torn copy] → The README
  note on `data/`. Commands are started by hand.
- [`~/.config/job-search-agent/` is missing] → podman-compose creates it empty. A command
  that reads a key fails in `config.require_env()`, and the error names the key and
  the file.

During migration only. These apply to branches created before this change until they are
merged or rebased onto `master`:

- [The branch's `.gitignore` does not list `data/evals/`, so it shows as untracked and
  `git add -A` stages it] → The migration adds `data/` to `.git/info/exclude`, which applies
  on every branch.
- [The branch tracks `data/resume.md` and `data/job_preferences.md`, so checking it out
  stops on the untracked user files] → Merge or rebase such branches onto `master` before
  checking them out, or check them out in another checkout.

## Migration Plan

The merge removes `data/resume.md` and `data/job_preferences.md` from the index. Git deletes
a file from the working tree when an incoming commit removes it, so the personal files are
copied aside first.

In each checkout that holds personal data, before pulling the change:

```
cp -r data ~/job-search-data-backup
git update-index --no-skip-worktree data/resume.md data/job_preferences.md
git checkout -- data/resume.md data/job_preferences.md
```

Then pull `master`, and:

```
printf 'data/\n' >> .git/info/exclude
cp ~/job-search-data-backup/resume.md ~/job-search-data-backup/job_preferences.md data/
mkdir -p data/evals
mv evals/cases.json* evals/ads evals/runs data/evals/
```

The database, rubric and search queries stay at their paths.

In each other checkout: clear the skip-worktree bits, run
`git checkout -- data/resume.md data/job_preferences.md`, merge `master`, remove `data/`, and
create it from `data.example/` or from a copy of another checkout's `data/`.

Rollback: copy `data/resume.md` and `data/job_preferences.md` aside, revert the merge, set
the skip-worktree bits, copy the two files back to `data/`, and move `cases.json*`, `ads/`
and `runs/` from `data/evals/` back to `evals/`.
