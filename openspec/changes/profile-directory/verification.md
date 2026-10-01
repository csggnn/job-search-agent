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
The personal-profile part runs after the migration (10.1).

## 8.5 Automated review

`/code-review medium` on the uncommitted diff: no correctness findings. One cleanup: the
unused `config._default_profile_requested` was removed. Unit suite after the fix:
`Ran 190 tests ... OK`.
