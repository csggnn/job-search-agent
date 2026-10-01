# Design

## Context

Before this change, a checkout holds one candidate's files:

```
<checkout>/
  .env                  tracked template; real keys hidden by skip-worktree
  data/
    resume.md           tracked sample; real content hidden by skip-worktree
    job_preferences.md  tracked sample; real content hidden by skip-worktree
    evaluations.db      gitignored
    compatibility_rubric.json, search_queries.json   gitignored
  evals/
    *.py                eval code
    cases.json, ads/, runs/   gitignored
```

This layout causes three problems:
- Real keys and personal data sit in tracked files. Git ignores their content only while
  the skip-worktree bit is set, and a fresh clone or worktree starts without it.
- The sample and the real candidate share one set of paths. Running the sample means
  overwriting the real `resume.md` and `job_preferences.md`, and both candidates'
  evaluations, rubric and queries end up in one database and one set of generated files.
- The eval set has one location for both candidates, mixed with the eval code.

proposal.md lists the full set of problems.

This change introduces profiles. 
A profile is the set of files associated to a candidate:
`resume.md`, `job_preferences.md`, the database, the generated rubric and search queries,
and the eval set.

## Goals / Non-Goals

**Goals:**

- A "default" profile and a "personal" profile exist and are self-contained: a run never reads or writes another profile's files.
- A run writes only inside its checkout. It reads keys from `~/.config/job-search-agent/.env`.
- The profile a run uses is visible: a run without `--default-profile` uses
  `profiles/personal/` of its checkout and fails when that profile is incomplete. A run with
  `--default-profile` uses `profiles/default/`.

**Non-Goals:**
- More than two profiles, or a profile at an arbitrary path.
- Re-scoring stale rows within one profile (CSG-48, second half).
- Committing a default eval set. `profiles/default/evals/` stays gitignored for the time being.

## Decisions

**Two profile directories**

```
~/.config/job-search-agent/
  .env                  keys, shared by every checkout and both profiles
<checkout>/
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

Both profiles use the same file names under their own directory. Code reads one profile
directory and never branches on the profile name after resolution.

**A run uses the personal profile unless `--default-profile` is given.**
A run with `--default-profile` uses `profiles/default/`. Without it, a run uses
`profiles/personal/` and fails when `resume.md` or `job_preferences.md` is missing there,
naming the missing file and `--default-profile`. Every entry point accepts the flag. Python
callers with no command line use the personal profile unless they select the default
profile first.

Alternative considered: a configuration file that selects the profile. Rejected: the
profile would depend on a file outside the command and outside the checkout.

Alternative considered: selecting the default profile when `profiles/personal/` is empty.
Rejected: a run on personal data that is missing would silently run on the sample.

Alternative considered: per-file fallback from `profiles/personal/` to `profiles/default/`.
Rejected: a personal resume combined with sample preferences is a candidate nobody intends,
and its evaluations would land in the personal database.

**`--scratch` runs on a temporary copy of the profile.**
With `--scratch`, a run copies the selected profile directory to a temporary directory and
uses the copy. The copy is deleted when the command exits. All writes (database, rubric and
query caches, eval runs) land in the copy. It combines with `--default-profile`. A scratch
copy lasts one command: a second command does not see the first one's writes.

Alternative considered: opening the database read-only and skipping cache writes.
Rejected: every write site would need a branch, and `evaluate_job` reads back the row it
saves.

**Keys live in `~/.config/job-search-agent/.env`, mounted read-only.**
Every checkout and worktree reads the same `.env`. The container mounts the directory
read-only, so the code cannot change keys. CI sets keys as environment variables. podman
4.9.3 refuses to start a container whose bind-mount source is missing, so the setup step
that creates `.env` also creates the directory.

Alternative considered: `.env` gitignored in the checkout. Rejected: `git clean -x` deletes
it, copying or archiving the checkout includes it, and each worktree needs its own copy.

**A worktree starts with no personal data.**
`profiles/personal/` is gitignored, so `git worktree add` does not create it. A run without
`--default-profile` fails. Copying the main checkout's `profiles/personal/` makes the
worktree run on that copy. Writes in a worktree land in its copy and do not reach the main
checkout.

Alternative considered: a git `post-checkout` hook that copies the data, which also runs
on `git worktree add`. Rejected: hooks are not installed by a clone and need
`git config core.hooksPath`, an extra setup step.

**`.env.example` is checked against one list of key names.**
The Anthropic and Groq SDKs read their keys from the environment, so no call in the repo
names them. `config.API_KEYS` lists every key name. A unit test fails when `.env.example`
lacks one, and `check_setup.py` reads the same list. The list does not state which keys are
required: that is checked where a key is used.

Alternative considered: scanning the code for `require_env` calls. Rejected: it misses the
keys the SDKs read themselves.

**The personal profile is backed up with documented folder copies.**
The personal profile is one directory, so the README gives a `cp -r` command for backup and
a restore command that copies into the checkout first and replaces `profiles/personal/`
only when the copy succeeds. The database is copied as a file, which is consistent when no
pipeline command writes during the copy. The host has no guaranteed `sqlite3` binary for an
online backup. Keys are not backed up: nothing in a checkout or a git operation deletes
`~/.config/job-search-agent/.env`.

Alternative considered: `backup` and `restore` commands in a script, with a marker file
that identifies a backup folder. Rejected: the script and its tests add maintenance for
behavior that two shell commands provide. `cp -r` into an existing folder nests the copy
and does not overwrite it.

**`scripts/profile.sh reset-default` clears the default profile's generated state.**
It removes the default profile's database, rubric and search queries, and keeps its inputs
and eval set. It runs on the host or in the container. The e2e test and the README use the
same command, so both clear the same files.

Reset applies to the default profile only. A reset of personal data would delete
evaluations and user-tracked fields that cannot be regenerated.

## Risks / Trade-offs

- [`git clean -x` in the main checkout deletes `profiles/personal/`] → The README gives
  the backup command. README and CLAUDE.md name the risk.
- [A developer runs without `--default-profile` or `--scratch` in a checkout that holds the
  real personal profile, and test results land in it] → Test runs use `--scratch` or a
  worktree with a copy. The README developer section states it.
- [Running the e2e tests clears the checkout's default-profile state] → The default
  profile's state is regenerated from committed inputs. The e2e test docstring states it.
- [A worktree's copy goes stale as the main checkout gains rows] → Copying
  `profiles/personal/` again replaces it.
- [Edits to `profiles/personal/` made in a worktree do not reach the main checkout] → This
  is the intended isolation. Promoting an input change means editing the main checkout's
  `profiles/personal/`.
- [Copying the database while a pipeline command writes produces a torn copy] → Documented.
  Commands are started by hand.
- [`~/.config/job-search-agent/` is missing, and `podman-compose up` fails with
  `statfs ...: no such file or directory`] → The `.env` setup step creates it. The README
  names the error and its fix.

During migration only. These apply to branches created before this change, checked out in
the main checkout, until they are merged or rebased onto `master`:

- [The branch's `.gitignore` does not list `profiles/personal/`, so it shows as untracked
  and `git add -A` stages it] → The migration adds it to `.git/info/exclude`, which
  applies on every branch.
- [The branch tracks `.env` and its code reads `<checkout>/.env`, which holds only the
  template] → API calls fail on that branch. Merge or rebase such branches onto `master`
  before running them.

## Migration Plan

The merge removes `.env` from the index. Git deletes a file from the working tree when an
incoming commit removes it, so the keys move to `~/.config/job-search-agent/` first.

In the main checkout, before pulling the change:

```
mkdir -p ~/.config/job-search-agent profiles/personal/evals
cp .env ~/.config/job-search-agent/.env
chmod 600 ~/.config/job-search-agent/.env
cp data/resume.md data/job_preferences.md data/evaluations.db profiles/personal/
mv evals/cases.json evals/ads evals/runs profiles/personal/evals/
git update-index --no-skip-worktree .env data/resume.md data/job_preferences.md
git checkout -- .env data/resume.md data/job_preferences.md
```

Then pull `master`, and:

```
printf 'profiles/personal/\n' >> .git/info/exclude
rm -rf data
```

After the merge, `data/` holds only generated files: the sample files are tracked under
`profiles/default/`. The rubric and query caches are rebuilt on the first personal run.

In each existing worktree: clear the skip-worktree bits, discard the worktree's copies with
`git checkout -- .env data/resume.md data/job_preferences.md`, merge `master`, remove
`data/`, and copy `profiles/personal/` from the main checkout if the worktree runs on
personal data. Evaluations saved in a worktree's `data/evaluations.db` are discarded.

Rollback: revert the merge, copy `profiles/personal/` files back to `data/`, copy
`~/.config/job-search-agent/.env` back to `.env`, and set the skip-worktree bits again.

## Open Questions

- Should `.git/info/exclude` entries be written by `scripts/profile.sh` instead of by hand?
  This changes only the migration and README steps.
