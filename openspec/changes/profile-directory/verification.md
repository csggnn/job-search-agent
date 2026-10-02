# Verification log

Results recorded while applying tasks.md. Environment: podman 4.9.3, podman-compose 1.0.6.

## 1.2 Key directory mount

- Directory exists, `.env` holds keys: `config.get_env("ORS_API_KEY")` is set inside the container.
- Directory exists without `.env`: the container starts. `config.get_env("ORS_API_KEY")` returns `None`.
- Directory missing: `podman-compose up -d` starts the container and creates
  `~/.config/job-search-agent/` as an empty directory. No `statfs` error.
- Edited `.env` (`CSG37_PROBE=yes` appended on the host): the next `podman-compose exec`
  reads `yes` without recreating the container.
- `echo X=1 >> /config/.env` inside the container: `sh: 1: cannot create /config/.env: Read-only file system`.
- Scenario "Keys are missing", with no `.env`:
  - `config.require_env("TAVILY_API_KEY")`: `RuntimeError: required environment variable 'TAVILY_API_KEY' is not set: add it to ~/.config/job-search-agent/.env`
  - `scripts/check_setup.py --default-profile` exits 1:
    ```
    profile: default (/workspace/profiles/default)
    === Setup ===
    OK: /workspace/profiles/default/job_preferences.md fills every section the pipeline reads
    MISSING: ANTHROPIC_API_KEY is not set in ~/.config/job-search-agent/.env
    MISSING: TAVILY_API_KEY is not set in ~/.config/job-search-agent/.env
    MISSING: GROQ_API_KEY is not set in ~/.config/job-search-agent/.env
    MISSING: ORS_API_KEY is not set in ~/.config/job-search-agent/.env
    ```

## 1.3 A key is missing from the template

`GROQ_API_KEY` removed from `.env.example`:
`FAIL: test_env_example_names_every_api_key`, `AssertionError: Lists differ: ['GROQ_API_KEY'] != []`,
message `.env.example does not name: GROQ_API_KEY`. File restored.

## 2.1 Ignore rules (`git check-ignore -v --no-index`)

| Path | Rule |
|---|---|
| `.env` | `.gitignore:.env` |
| `profiles/personal/` and every file under it | `profiles/personal/` |
| `profiles/default/evaluations.db` | `profiles/default/evaluations.db` |
| `profiles/default/compatibility_rubric.json` | `profiles/default/compatibility_rubric.json` |
| `profiles/default/search_queries.json` | `profiles/default/search_queries.json` |
| `profiles/default/evals/{cases.json,ads/,runs/}` | `profiles/default/evals/` |
| `profiles/default/resume.md`, `job_preferences.md`, `evals/*.py` | not ignored |

## 2.3

`grep -rn "DATA_DIR" jobsearch evals scripts tests`: no output, exit 1.

## 2.6 `--help`

`evaluate_job_post.py`, `discover_jobs.py`, `propose_jobs.py`, `evals/capture.py`,
`evals/draft.py`, `evals/run_evals.py`, `scripts/check_setup.py`,
`scripts/recompile_rubric.py`: each lists `--default-profile` and `--scratch`.

## 3.1 Offline check of the committed sample data

- `## Scoring Notes` removed from `profiles/default/job_preferences.md`:
  `FAIL: test_scoring_notes_present`, `## Scoring Notes missing or empty in /workspace/profiles/default/job_preferences.md`.
- Reordering the `## Location` entries in the file leaves the test passing: the test and the
  resolver read the same file. The scenario is exercised by patching
  `_resolve_target_locations` instead. Reversed, one entry omitted, and empty: each fails
  `test_target_locations_come_from_the_location_section` with
  `target locations differ from the ## Location entries`.

File restored after each step.

## 3.2

`DefaultDataTest` passes against `profiles/default/`. The sample home address
`Rue des Halles 4, 1000 Bruxelles, Belgium` geocodes through OpenRouteService to
`[4.350082, 50.850078]` (lon, lat).

## 3.3 Personal profile does not affect the check

Personal profile with preferences lacking `## Scoring Notes`: unit suite `Ran 190 tests ... OK`.
Personal profile deleted afterwards.

## 4.1 Personal preferences lack a section

`scripts/check_setup.py` with a personal profile lacking `## Home Address`, exit 1:
```
profile: personal (/workspace/profiles/personal)
=== Setup ===
MISSING: '## Home Address' is missing or empty in /workspace/profiles/personal/job_preferences.md
OK: every API key is set
```

## 6.1 New worktree without copied data

Evidence from this change's worktree (`.trees/csg-37-profile-directory`), which was created
with nothing copied and has no `profiles/personal/`. Unit suite: `Ran 190 tests ... OK`.
`evaluate_job_post.py <url>` and `propose_jobs.py 2 --no-discover` each exit 1 with:
```
error: the personal profile is incomplete, missing: /workspace/profiles/personal/resume.md, /workspace/profiles/personal/job_preferences.md. Create the missing file(s), or run with --default-profile to use the sample candidate in /workspace/profiles/default
```
`profiles/default/` held only `resume.md` and `job_preferences.md` afterwards: no database
was written.

## 6.3 A worktree uses the shared keys / 8.4 live e2e suite

Same worktree, no `.env` in the checkout, keys only in `~/.config/job-search-agent/.env`.
`python3 -m unittest discover -s tests/e2e -v`: `Ran 2 tests in 98.782s, OK (skipped=1)`
(discovery smoke is opt-in). The evaluation of `https://canonical.com/careers/6707824` with
`--default-profile` completed (Anthropic, Tavily calls), saved 13 criteria rows, and the
second run was served from cache.

## Run after a reset

After the e2e run, `scripts/profile.sh reset-default` left `profiles/default/` with
`resume.md` and `job_preferences.md` only, and `storage.get_evaluation(<url>)` on the default
profile returned `None`: the next evaluation is computed.

## 7.1 Restore over newer data

Test profile under the scratchpad. After the backup, `added-after-backup.txt` was added,
`resume.md` changed, and `profiles/.personal.restore/stale.txt` left behind. After the README
restore command, `diff -r <backup> profiles/personal` reported no difference and
`profiles/.personal.restore` was gone. With a missing source folder, `cp` failed and
`profiles/personal/` kept its files.

## 7.3

`grep -rn "skip-worktree\|data/resume\|data/job_preferences\|data/evaluations\|evals/cases\|evals/ads" --include=*.md --include=*.py . | grep -v openspec`:
no output.

## 8.1

Unit suite: `Ran 190 tests ... OK`.

## 8.3 (default profile part)

`evals/run_evals.py --criteria-only --default-profile`, exit 1:
`no cases to run in the default profile (/workspace/profiles/default/evals) - add one with: python evals/capture.py <url>`.

## 8.3 (personal profile part)

Main checkout after migration, `evals/run_evals.py --criteria-only`: `profile: personal
(/workspace/profiles/personal)`, `Scored 7/7 case(s)`, snapshot saved to
`/workspace/profiles/personal/evals/runs/2026-10-01T14-14-21Z.json`. Criteria accuracy 0.946,
precision 0.9, recall 0.818 over 56 labels.

The migration rebuilt the personal rubric: the plan does not copy
`compatibility_rubric.json`. 6 criteria of the new rubric carry names the cases do not
label, and 4 case labels name criteria the new rubric lacks. Each case reports both lists;
those labels are excluded from accuracy, as `dataset.py` specifies.

## 8.5 Automated review

`/code-review medium` on the uncommitted diff: no correctness findings. One cleanup: the
unused `config._default_profile_requested` was removed. Unit suite after the fix:
`Ran 190 tests ... OK`.

## 7.1 README on the pushed branch

Checked on GitHub, branch `feat/csg-37-profile-dir-implementation` at `92ef739`, by clicking
each link in Chrome:

| Scenario | Result |
|---|---|
| First mention of a committed file | `profiles/default/job_preferences.md` (Setup step 3) shows the full path and opens `blob/.../profiles/default/job_preferences.md`, which holds `Rue des Halles 4`. `profiles/default/resume.md` links to its file. |
| First mention of .env | Setup step 1 shows `~/.config/job-search-agent/.env` and opens `blob/.../.env.example`, which names `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `GROQ_API_KEY`, `ORS_API_KEY`. |
| First mention of a personal file | `profiles/personal/job_preferences.md` (Default usage) shows the full path and opens `README.md#your-personal-profile`; the "Your personal profile" heading lands at the top of the view. |
| README setup | No step runs `git update-index` (`grep -c update-index README.md`: 0). |
| User looks for how to protect personal data | "Your personal profile" gives the backup and restore commands, the `git clean -x` warning and the warning about copying during a run. |
| Developer looks for a safe test setup | "Developer notes" describes `--scratch` (a scratch copy lasts one command), `scripts/profile.sh reset-default`, the worktree copy command `cp -r ../../profiles/personal profiles/`, and that worktree changes do not reach the main checkout. |

## 8.2 Fresh-clone run

`git clone --branch feat/csg-37-profile-dir-implementation` (at `92ef739`) into a new folder;
the clone holds `.env.example` and no `.env`. README setup followed in order, except
`cp .env.example ~/.config/job-search-agent/.env`, skipped because it would overwrite the
existing key file; the existing `~/.config/job-search-agent/.env` stands in for it.

- Step 2, `check_setup.py --default-profile`: profile and keys OK, Tavily, Anthropic and
  Groq calls answered.
- Step 3, `propose_jobs.py 3 --default-profile`: exit 0, 9 ads evaluated, both shortlists
  hold 3 jobs. Scenario "Fresh clone proposes jobs": partial. No shortlisted job has a
  resolved commute. Commute routing worked for 1 of the 9 ads (BDO, Zaventem, 25.1 min);
  the other 8 postings, mostly recruiter ads, gave no office address.
- Step 4: `profiles/personal/` created from the sample files; `check_setup.py` reports the
  personal profile complete.
- Step 5, `propose_jobs.py 3`: exit 0, `profile: personal`, 9 ads evaluated, both shortlists
  hold 3 jobs. The default `evaluations.db` sha256 is unchanged.
- Scenario "Switching from the sample to a personal profile": the personal database started
  empty; 7 of its 9 URLs were also in the default database and were evaluated again.
- Scenario "Returning to the default profile": `propose_jobs.py 3 --default-profile
  --no-discover` ranks 9 evaluations, the default database's rows only.
- Scenario "After setup and a personal run": `git status --short` and `git add -A --dry-run`
  print nothing.
- Scenario "Switching branches after a personal run": `git switch master` and back succeed;
  the personal files' sha256 and the key file are unchanged.
- Scenario "Merging after a personal run": `git merge origin/master` reports "Already up to
  date", so no merge content was exercised.
- Scenario "Cleaning a checkout keeps the keys": `git clean -x -f -d` removed
  `profiles/personal/`; `~/.config/job-search-agent/.env` sha256 unchanged.

The clone and its container were removed afterwards.

## 10.1 Migration in the main checkout

The design's Migration Plan was run in the main checkout, switching to a local branch at
`origin/feat/csg-37-profile-dir-implementation` in place of pulling `master`. No
pre-migration shortlist was taken; the check reads the migrated database directly.

`propose_jobs.py 10 --no-discover`: `profile: personal (/workspace/profiles/personal)`,
`10 job(s) proposed out of 94 evaluated`. The 94 rows are the pre-migration evaluations plus
those added by the first personal run after migration. The shortlist holds jobs evaluated
before the migration, with their commute scores.

The personal `compatibility_rubric.json` and `search_queries.json` were rebuilt on the first
personal run, because the plan copies neither file. Both are LLM output sampled at the default
temperature: two `compile_queries()` calls on the default profile shared 4 of 12 distinct
queries.

## 6.2 Worktree with copied personal data

Worktree `.trees/csg-37-migration-test` at `2ec4181`, with the main checkout's
`profiles/personal/` copied in. `evaluate_job_post.py https://canonical.com/careers/6707824`
ran there; `propose_jobs.py 3 --no-discover` in the worktree then reports
`profile: personal (/workspace/profiles/personal)` and `95 evaluated`.

| `profiles/personal/evaluations.db` | Modified | Rows |
|---|---|---|
| main checkout | 16:10:29, unchanged since before the copy | 94 |
| worktree copy | 16:36:15 | 95 |

`propose_jobs.py 3 --no-discover` in the main checkout reports `94 evaluated`.

## 10.2 Existing worktrees

State of every checkout listed by `git worktree list` after the migration. The worktrees
`csg-15-markdown-wrap-width` and `csg-50-sdd-pr-review-templates` were removed.

| Checkout | Skip-worktree bits | `data/` | `.env` | `profiles/personal/` |
|---|---|---|---|---|
| main checkout | 0 | absent | absent | present |
| `.trees/csg-37-migration-test` | 0 | absent | absent | present |
| `.trees/csg-37-profile-directory` | 0 | absent | absent | absent |

The main checkout and `.trees/csg-37-migration-test` are on local branches at `2ec4181`.
`.trees/csg-37-profile-directory` held an empty `data/` directory, removed with `rmdir`.

## 8.6 After the explicit-directory change

The active profile moved from module state in `config.py` to an argument: entry points call
`config.profile_from_args(args)` and pass `profile.directory` down. Checks re-run on the
changed code, in this worktree with a copy of the main checkout's `profiles/personal/`:

- Unit suite: `Ran 194 tests ... OK`.
- `grep -rn "DATA_DIR\|profile_dir()\|use_default_profile\|apply_profile_args\|_profile = \|global " jobsearch evals scripts tests *.py`: no output.
- `--help` of the 8 entry points lists `--default-profile` and `--scratch`.
- Live e2e suite: `Ran 2 tests in 97.509s, OK (skipped=1)`; full run then cache hit, 14
  criteria saved.
- `check_setup.py` and `check_setup.py --default-profile`: profile and keys OK, Tavily,
  Anthropic and Groq calls answered.
- `evals/run_evals.py --criteria-only`: `profile: personal`, `Scored 7/7 case(s)`, accuracy
  0.946, precision 0.9, recall 0.818, the same as the run in 8.3.
  `--default-profile`: exit 1, `no cases to run in the default profile`.
- `discover_jobs.py --default-profile --scratch`: `66 discovered -> ... -> 10 selected (1 LLM
  call)`, exit 0.
- `evaluate_job_post.py <url> --default-profile --scratch`, run twice (Serco, Space
  Applications Services): both evaluations complete; the office address was not found in
  either run. `profiles/default/` file sha256 unchanged after each run; no
  `/tmp/job-search-scratch-*` directory remains.
- `commute.commute_route(config.DEFAULT_PROFILE_DIR, <Space Applications office address>)`:
  21.4 min, 12.4 km from `Rue des Halles 4, 1000 Bruxelles, Belgium`.
- `/code-review medium`: one finding. The home address was read before commute scoring
  knew a route was needed, so a profile without `## Home Address` failed every evaluation,
  including remote jobs, and aborted `run_evals.py` and `draft.py` runs. Fixed: commute
  scoring takes the profile directory and `commute_route()` reads the address. Covered by
  `CommuteHomeAddressTest` in `tests/unit/test_profiles.py`.

### After the `Profile` class

Functions take a `config.Profile`, which derives every path inside the profile; the rubric
and query caches use `Profile.input_hashes` and `Profile.is_stale`. Re-run:

- Unit suite: `Ran 195 tests ... OK`.
- `--help` of the 8 entry points lists `--default-profile` and `--scratch`.
- `check_setup.py` and `check_setup.py --default-profile`: profile and keys OK.
- `evals/run_evals.py --criteria-only`: `Scored 7/7 case(s)`, accuracy 0.946, precision
  0.9, recall 0.818. `--default-profile`: `no cases to run in the default profile`.
- `propose_jobs.py 3 --no-discover`: `profile: personal`, `94 evaluated`.
- `commute.commute_route(<default Profile>, <Space Applications office address>)`: 21.4
  min, 12.4 km.
- `Profile.is_stale` on the default rubric compiled before the change: `False`; existing
  caches stay valid.
- Live e2e suite: `Ran 2 tests in 95.502s, OK (skipped=1)`; full run then cache hit, 12
  criteria saved.

### Personal profile by default in Python

Public `jobsearch` functions take `profile=None` last; `None` resolves the personal profile.
`Profile.is_stale` is renamed `Profile.inputs_changed_since`.

- Unit suite: `Ran 196 tests ... OK`.
- `storage.list_evaluations()` with no argument: 94 evaluations, the personal database.
  `storage.list_evaluations(profile=config.resolve_profile(default_profile=True))`: 1.
- `propose_jobs.py 3 --no-discover`: `profile: personal`, `94 evaluated`.

### Required `profile` argument

Public `jobsearch` functions take a required `profile` argument.

- Unit suite: `Ran 194 tests ... OK`.
- `storage.list_evaluations()` with no argument: `TypeError: list_evaluations() missing 1
  required positional argument: 'profile'`.
- `propose_jobs.py 3 --no-discover --default-profile --scratch`: `profile: default (scratch
  copy of /workspace/profiles/default)`, `0 job(s) proposed out of 0 evaluated`.
