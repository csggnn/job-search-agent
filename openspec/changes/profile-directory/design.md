# Design

## Context

See proposal.md for the problem. One fact shapes the decisions: every data path in
`jobsearch/` derives from `config.DATA_DIR`. `storage`, `rubric` and `discovery` join their
file names onto it. Outside `jobsearch/`, `evals/dataset.py` and
`tests/e2e/test_e2e_pipeline.py` hold their own data paths.

## Goals / Non-Goals

**Goals:**
- One Python choke point decides every profile path.
- Each checkout is self-contained: runs read and write only files inside that checkout.
- Default behavior follows from which files exist. No environment variable is required;
  `JOBSEARCH_PROFILE` is an optional override.

**Non-Goals:**
- More than two profiles, or a profile at an arbitrary path.
- Personal data outside the checkout.
- Re-scoring stale rows within one profile (CSG-48, second half).
- Committing a default eval set. `profiles/default/evals/` stays gitignored for the time being.

## Decisions

**Two profile directories**

```
<checkout>/
  .env                  keys, gitignored, shared by both profiles
  profiles/
    default/                 profile "default"
      resume.md             committed
      job_preferences.md    committed
      evaluations.db        generated, gitignored
      compatibility_rubric.json, search_queries.json   generated, gitignored
      evals/                cases.json, ads/, runs/, gitignored
    personal/              profile "personal", gitignored as a whole
      resume.md, job_preferences.md
      evaluations.db, compatibility_rubric.json, search_queries.json
      evals/                cases.json, ads/, runs/
  evals/                eval code only
```

Both profiles use the same file names under their own directory. Code reads one
`PROFILE_DIR` and never branches on the profile name after resolution.

Alternative considered: a profile directory in the home directory (`~/.job-search-agent`),
bind-mounted into the container. Rejected: it adds a directory outside the project, and
podman 4.9.3 refuses to start a container whose bind-mount source is missing
(`statfs ...: no such file or directory`), so a fresh clone would fail `podman-compose up`.

**Resolution in `config.py`, once, at import.**

```
JOBSEARCH_PROFILE == "default"                    -> profiles/default
JOBSEARCH_PROFILE == "personal"                   -> profiles/personal,  error unless complete
JOBSEARCH_PROFILE == "auto" or unset:                       
    profiles/personal has resume.md and job_preferences.md -> profiles/personal
    profiles/personal has neither                          -> profiles/default
    profiles/personal has one                              -> error naming the missing file
JOBSEARCH_PROFILE set to anything else            -> error

```

`config` exposes `PROFILE_DIR` and `PROFILE_NAME`. `DATA_DIR` is removed, and its three
users switch to `PROFILE_DIR`. `EVALS_DATA_DIR = PROFILE_DIR/evals`.

The error on a half-filled `profiles/personal/` is raised when a path is used, not at import. Unit tests do not use the personal profile so they are unaffected. 

Alternative considered: per-file fallback from `profiles/personal/` to `profiles/default/`. Rejected: a personal resume combined with sample preferences is a candidate nobody intends, and its evaluations would land in the personal database.

**Keys stay in `.env`, gitignored.**
`.env.example` is committed. The container sees `.env` through the checkout mount, and the
existing `load_dotenv()` in `config.py` reads it. `docker-compose.yml` drops `env_file`,
which loads the same file a second time at container creation. Without it, the container
starts when `.env` is absent, and an edited `.env` applies to the next command. CI sets
keys as environment variables, and `load_dotenv()` does nothing when `.env` is absent.

**A worktree starts with no keys and no personal data.**
`.env` and `profiles/personal/` are gitignored, so `git worktree add` does not create them.
Profile resolution then selects `profiles/default/`. Unit tests run without either file.
Copying the main checkout's `.env` enables sample runs. Copying `profiles/personal/` as
well selects the personal profile on a copy of the main checkout's data. From a worktree
at `.trees/<name>/`:

```
cp ../../.env .
cp -r ../../profiles/personal profiles/
```

The code does not detect worktrees. Writes in a worktree land in its copy and do not reach
the main checkout. Running the second command again refreshes the copy.

Without the first command, the worktree has no keys. Its container starts and the unit
suite passes. A command that calls an API fails because its key is not set. `load_dotenv()`
searches upward from inside the container, where `/workspace` is the worktree root, so it
does not find the main checkout's `.env`. The README developer section gives both commands.

Alternative considered: a git `post-checkout` hook that copies the data, which also runs
on `git worktree add`. Rejected: hooks are not installed by a clone and need
`git config core.hooksPath`, an extra setup step.

**Isolated runs on personal data use a worktree copy.**
Two outcomes in proposal.md drive this decision: a developer works on several branches at
once, in the main checkout or in git worktrees, and a developer can run on personal data
without changing the real data. Personal data is gitignored, so a worktree has it only
after a step brings it in. A copy is that step, and it also isolates the worktree's runs
from the real data. One mechanism serves both outcomes and needs no code.

A developer who tests changes against personal data creates a worktree and copies
`profiles/personal/` into it. In the main checkout, the personal profile is the real data.
The README developer section describes the workflow: create the worktree, run the two copy
commands, run the pipeline. It states that evaluations, rubric and query caches, eval runs
and input edits made in a worktree stay in its copy and do not reach the main checkout.

Alternatives considered:
- Every checkout mounts one shared folder of real personal data. Rejected: the problem of
  sharing the data moves to sharing the data folder's location across checkouts.
- Worktree code runs in the main checkout's container, which sees `.trees/`. Rejected: a
  branch that changes `Dockerfile` or `docker-compose.yml` runs in the old image, the run
  depends on the main checkout's current branch and image, and runs write to the real
  database.

`backup` before a test and `restore` after also isolates a test in any checkout. `restore`
discards real runs made between the two commands.

**Unit tests read the committed sample.**
`DefaultDataTest` reads `profiles/default/` whichever profile is active. `config` exposes
`DEFAULT_PROFILE_DIR`, and the section helpers the test calls accept the preferences text,
so the test does not go through the active profile. `scripts/check_setup.py` checks the
personal profile's sections when the personal profile is active.

**`config.API_KEYS` names every API key the pipeline can read.**
The Anthropic and Groq SDKs read `ANTHROPIC_API_KEY` and `GROQ_API_KEY` from the environment
themselves, so no call in the repo names them. `config.API_KEYS` lists all key names in one
place. A unit test checks that `.env.example` names each entry, and fails naming the entries
it lacks. `check_setup.py` reads the same list.

The list names keys. It does not state which are required. Requiredness is checked where a
key is used (`config.require_env`) and by `check_setup.py`. A later rule such as "at least
one LLM key" changes only those checks: the list, the template and the test stay as they are.

Alternative considered: scanning the code for `require_env` calls. Rejected: it misses the
keys the SDKs read themselves.

**`scripts/profile.sh`, a bash script run on the host.**
It runs on the host because the backup folder is outside the container's mount. It needs
only `cp` and `rm`.

- `backup <folder>`: copies the current checkout's `profiles/personal/` and `.env` into
  `<folder>`. `<folder>` must not exist or must already be a backup, identified by a
  `.job-search-agent-backup` marker file. Existing backup contents are replaced.
- `restore <folder>`: requires the marker. It copies the backup's `profiles/personal/` and
  `.env` to staging paths inside the checkout (`profiles/.personal.restore`,
  `.env.restore`). When both copies succeed, it removes the current files and renames the
  staged ones into place. On a failed copy it removes the staged paths and leaves the current
  files as they were. After a restore both equal the backup.

The marker stops `backup` from overwriting an unrelated directory and `restore` from
reading one. Default-profile state is outside backup scope: it is regenerated from
committed inputs.

**The database is copied as a file.**
The rollback journal keeps a committed database in one file. The copy is consistent when
no pipeline command writes during it. The docs state this. The host has no guaranteed
`sqlite3` binary for an online backup.

**Evals follow the profile through `evals/dataset.py`.**
`EVALS_DIR` becomes `config.EVALS_DATA_DIR`. `capture.py`, `draft.py` and `run_evals.py`
need no path changes. `run_evals.py` then scores each profile's cases against that
profile's rubric. With the eval set left in `evals/`, running evals under
`JOBSEARCH_PROFILE=default` would score personal labels against the sample rubric, and
every label would sort to `stale_label`.

**The e2e test goes through `config`.**
It reads `config.PROFILE_DIR` for the database and `config` for keys, and runs its
subprocess with the same environment. In a worktree it writes to the worktree's copy.

## Risks / Trade-offs

- [`git clean -x` in the main checkout deletes `profiles/personal/` and `.env`] → `backup`
  exists for this. README and CLAUDE.md name the risk.
- [A worktree's copy goes stale as the main checkout gains rows] → Copying
  `profiles/personal/` again replaces it.
- [Edits to `profiles/personal/` made in a worktree do not reach the main checkout] → This
  is the intended isolation. Promoting an input change means editing the main checkout's
  `profiles/personal/`.
- [Copying the database while a pipeline command writes produces a torn copy] → Documented.
  Commands are started by hand.
- [A developer forgets to copy `.env` into a new worktree] → API calls fail because the
  key is not set. The README developer section gives the copy commands.

During migration only. These apply to branches created before this change, checked out in
the main checkout, until they are merged or rebased onto `master`:

- [The branch's `.gitignore` does not list `profiles/personal/` and `.env`, so both show as
  untracked and `git add -A` stages them] → The migration adds both to
  `.git/info/exclude`, which applies on every branch.
- [The branch tracks `.env`. Checking it out refuses to overwrite the untracked `.env`, and
  a forced checkout replaces the keys with the template] → Merge or rebase such branches
  onto `master` before checking them out.

## Migration Plan

The merge removes `.env` from the index. Git deletes a file from the working tree when an
incoming commit removes it, so the keys are copied aside first.

In the main checkout, in one shell session, before pulling the change:

```
mkdir -p profiles/personal/evals
keys_dir=$(mktemp -d)
cp .env "$keys_dir/.env"
cp data/resume.md data/job_preferences.md data/evaluations.db profiles/personal/
mv evals/cases.json evals/ads evals/runs profiles/personal/evals/
git update-index --no-skip-worktree .env data/resume.md data/job_preferences.md
git checkout -- .env data/resume.md data/job_preferences.md
```

Then pull `master`, and:

```
mv "$keys_dir/.env" .env
rmdir "$keys_dir"
printf 'profiles/personal/\n.env\n' >> .git/info/exclude
rm -rf data
```

`mktemp -d` creates a directory readable only by its owner, so the keys are not exposed to
other users while the pull runs. After the merge, `data/` holds only generated files: the sample files are tracked under
`profiles/default/`. The rubric and query caches are rebuilt on the first personal run.

In each existing worktree: clear the skip-worktree bits, merge `master`, then run the two
copy commands.

Rollback: revert the merge, copy `profiles/personal/` files back to `data/`, and set the
skip-worktree bits again.

## Open Questions

- Should `.git/info/exclude` entries be written by `scripts/profile.sh` instead of by hand?
  This changes only the migration and README steps.
