# Tasks

Each task names the spec scenarios it verifies. A scenario is verified by a test named after
it, or by a manual check whose result is recorded under the task. Section 9 collects every
scenario into the table the implementation PR description carries.

Unit tests run with `podman-compose exec job-search python3 -m unittest discover -s tests/unit`.

## 1. Keys

- [ ] 1.1 Commit `.env.example` holding the key names of the current `.env` template with no values. Remove `.env` from the index (`git rm --cached .env`). Scenario "Fresh clone" (personal-data-protection): verified in 8.2.
- [ ] 1.2 In `docker-compose.yml`, remove `env_file` and mount `${HOME}/.config/job-search-agent` read-only at `/config`. Make `config.py` call `load_dotenv("/config/.env")`, which does nothing when the file is absent. Verify that `podman-compose up -d` starts when the directory exists without `.env`, that it fails with `statfs ...: no such file or directory` when the directory is missing, that an edited `.env` applies to the next command without recreating the container, and that writing `/config/.env` from inside the container fails because the mount is read-only. Record the results. Scenario "Key directory is missing" (personal-data-protection): the recorded failure, and the README text from 7.1.
- [ ] 1.3 Add `config.API_KEYS` listing every key name the pipeline can read, including `ANTHROPIC_API_KEY` and `GROQ_API_KEY`. Requiredness stays in `config.require_env` and `check_setup.py`. Add `test_env_example_names_every_api_key`, which fails naming each missing entry. Scenario "A key is missing from the template": verify by removing one key from `.env.example`, running the suite and recording the failure message, then restoring it.
- [ ] 1.4 Make `scripts/check_setup.py` read key names from `config.API_KEYS` and take its keys through `config`.

## 2. Profile layout and resolution

- [ ] 2.1 `git mv data/resume.md data/job_preferences.md profiles/default/`. Replace the `data/` and `evals/` data rules in `.gitignore` with: `profiles/personal/`, the generated files and `evals/` of `profiles/default/`. Verify with `git check-ignore -v` on each path listed in the design's directory tree.
- [ ] 2.2 Implement profile resolution in `config.py` as a pure function of the checkout root and the `--default-profile` value. Resolve on first path use, not at import. Expose `profile_dir()`, `profile_name()`, `DEFAULT_PROFILE_DIR`, `evals_data_dir()` (`profile_dir()/evals`) and `use_default_profile()` for Python callers with no command line. Add `add_profile_argument(parser)`, which registers `--default-profile` and `--scratch`, and `apply_profile_args(args)`. Do not read `sys.argv` at import, so importing `jobsearch` does not depend on the importing process's arguments. Remove `DATA_DIR`. The error for a missing personal file names that file and `--default-profile`. Unit tests against temporary directories, one per scenario (profile-selection): `test_fresh_clone_runs_the_default_profile`, `test_fresh_clone_without_the_flag`, `test_personal_files_select_the_personal_profile`, `test_one_personal_file_is_missing`, `test_requesting_the_default_profile`.
- [ ] 2.3 Switch `storage.DB_PATH`, `rubric.RUBRIC_PATH` and `discovery.QUERIES_PATH` to paths computed from `config.profile_dir()` on use. Add `test_incomplete_personal_profile_writes_no_database`: with no personal files, and with only a personal resume, opening storage raises and creates no database file in either profile. Verify `grep -rn "DATA_DIR" jobsearch evals scripts tests` returns nothing.
- [ ] 2.4 In `evals/dataset.py`, give every function that reads or writes files (`load_cases`, `save_cases`, `backup_cases`, `save_ad`, `load_ad`, `case_post`, `has_ad`) the eval directory as its first argument, and add `cases_path(evals_dir)` for the path `draft.py` prints. Remove the path constants computed at import (`EVALS_DIR`, `CASES_PATH`, `BACKUP_PATH`, `ADS_DIR`, `RUNS_DIR`). Prefix internal names with an underscore (`_ad_filename`, `_ad_path`, `_well_typed`, and the backup and ads paths) and list the public names in `__all__`. In `capture.py`, `draft.py` and `run_evals.py`, read `config.evals_data_dir()` once after `config.apply_profile_args(args)` and pass it. `run_evals.py` builds its runs directory from the same value. Update the `save_ad` patch in `tests/unit/test_evals.py` to the new signature. Scenarios "Evals use the active profile's eval set and rubric" and "A profile without an eval set does not use another profile's": verified in 8.3.
- [ ] 2.5 Make `tests/e2e/test_e2e_pipeline.py` run `scripts/profile.sh reset-default` in setup, run the pipeline with `--default-profile`, and read the database path from `config.profile_dir()` after `config.use_default_profile()`. State in its docstring that it clears the checkout's default-profile state.
- [ ] 2.6 Call `config.add_profile_argument(parser)` and `config.apply_profile_args(args)` in every entry point before any profile path is used: `evaluate_job_post.py`, `discover_jobs.py`, `propose_jobs.py`, `evals/capture.py`, `evals/draft.py`, `evals/run_evals.py`, `scripts/check_setup.py`, `scripts/recompile_rubric.py`. Verify by running each entry point with `--help` and recording that both flags are listed.
- [ ] 2.7 Implement `--scratch` in `apply_profile_args`: copy the resolved profile directory to a temporary directory, point `profile_dir()` at it, and delete it at exit. Unit tests against temporary directories, one per scenario (profile-selection): `test_scratch_run_on_the_personal_profile`, `test_scratch_run_on_the_default_profile`, `test_a_scratch_copy_lasts_one_command`.

## 3. Unit tests read the committed sample

- [ ] 3.1 Point `DefaultDataTest` at `config.DEFAULT_PROFILE_DIR`. Give the section helpers it calls (`config.home_address()` and the target-location resolution) an optional preferences-text argument, so the test does not read the active profile. Scenarios "Required section removed" and "Resolved locations differ from the Location entries" (default-profile-data): verify by removing `## Scoring Notes` from the sample and reordering its `## Location` entries, recording each failure, then restoring the file.
- [ ] 3.2 Scenarios "Home address resolves", "Target locations come from the Location section" and "Scoring guidance is present" (default-profile-data): verify the existing `DefaultDataTest` tests pass against `profiles/default/`, and that the sample home address geocodes through OpenRouteService from inside the container. Record the coordinate.
- [ ] 3.3 Scenario "Personal profile does not affect the check": create a personal profile whose preferences lack `## Scoring Notes`, run the unit suite, and record that `DefaultDataTest` passes. Delete the personal profile afterwards.

## 4. Setup verification

- [ ] 4.1 Make `scripts/check_setup.py` report, for the active profile, each of `## Location`, `## Home Address` and `## Scoring Notes` that is missing or empty, naming the file. Put the section check in a pure function with a unit test, `test_personal_preferences_lack_a_section`. Scenario "Personal preferences lack a section": also run `check_setup.py` against a personal profile without `## Home Address` and record the output.

## 5. Reset

- [ ] 5.1 Write `scripts/profile.sh` with `reset-default` as in the design. It resolves the checkout from its own location and uses only `rm`. `reset-default` removes `profiles/default/evaluations.db`, `compatibility_rubric.json` and `search_queries.json`, and runs on the host or in the container.
- [ ] 5.2 Add `tests/unit/test_profile_sh.py`, which copies the script into a temporary checkout-like tree and runs it with `bash`: `test_reset_the_default_profile` (profile-selection).

## 6. Worktrees

- [ ] 6.1 Scenario "New worktree without copied data" (profile-selection): create a worktree without copying, run the unit suite, and record that a run without `--default-profile` fails naming `--default-profile`.
- [ ] 6.2 Scenario "Worktree with copied personal data": from the worktree, run `cp -r ../../profiles/personal profiles/`, evaluate one URL there, and record that the run used the personal profile and that the main checkout's personal database row count and modification time are unchanged.
- [ ] 6.3 Scenario "A worktree uses the shared keys" (personal-data-protection): in a worktree with nothing copied, evaluate one URL with `--default-profile` and record that the API calls succeed.

## 7. Docs

- [ ] 7.1 Rewrite the `README.md` setup: `mkdir -p ~/.config/job-search-agent`, `.env` created there from `.env.example`, the `statfs ...: no such file or directory` error and its fix, the sample run first with `--default-profile`, then the personal profile with no cleanup step, no `git update-index`. Add a section on the personal profile covering its files, the backup command (`cp -r profiles/personal <folder>`), the restore command (`cp -r <folder> profiles/.personal.restore && rm -rf profiles/personal && mv profiles/.personal.restore profiles/personal`), the `git clean -x` warning and the warning about copying during a running command. Scenario "Restore over newer data" (personal-data-protection): add a file to a test personal profile that the backup lacks, run the restore command, and record that `diff -r` against the backup reports no difference. Add a developer section covering `--scratch` and the statement that a scratch copy lasts one command, `reset-default`, the worktree copy command (`cp -r ../../profiles/personal profiles/`), the statement that changes to a worktree's data stay in its copy, and the statement that a run without `--default-profile` or `--scratch` in a checkout with the real personal profile writes to it. Apply the first-mention link rule. Scenarios "README setup", "First mention of a committed file", "First mention of .env", "First mention of a personal file", "Developer looks for a safe test setup", "User looks for how to protect personal data": verify on the pushed branch on GitHub by clicking each first-mention link, and record the result per scenario.
- [ ] 7.2 Update `CLAUDE.md`: replace "Git-invisible files" with the profile layout and keys in `~/.config/job-search-agent/.env`, add `--default-profile`, `--scratch` and `scripts/profile.sh reset-default` to the Commands section, name the `git clean -x` risk, and update the paths in the evals rules (`data/evaluations.db`, `evals/ads/`).
- [ ] 7.3 Update `docs/architecture.md`, `docs/evals.md` and `docs/roadmap.md`, and the docstrings in `evals/__init__.py`, `evals/draft.py`, `jobsearch/preselection.py` and `tests/e2e/test_e2e_pipeline.py`. Verify `grep -rn "skip-worktree\|data/resume\|data/job_preferences\|data/evaluations\|evals/cases\|evals/ads" --include=*.md --include=*.py . | grep -v openspec` returns nothing.

## 8. Acceptance

- [ ] 8.1 Run the full unit suite. Verify all tests pass.
- [ ] 8.2 Fresh-clone run: clone the branch into a new folder and follow the README.
  - Scenarios "Fresh clone" (personal-data-protection) and "Fresh clone runs the default profile": record that `.env.example` exists, `.env` does not, and the first run uses the default profile.
  - Scenario "Fresh clone proposes jobs": run `propose_jobs.py --default-profile 2` and record the summary.
  - Scenario "Personal files select the personal profile" and "Switching from the sample to a personal profile": add a second fictional profile as the personal profile, run `propose_jobs.py 2`, and record that no sample job appears.
  - Scenario "Personal run leaves the default profile unchanged": record the row counts of both databases.
  - Scenario "Returning to the default profile": run `propose_jobs.py --default-profile` and record that only sample jobs appear.
  - Scenario "After setup and a personal run": record `git status --short` and `git add -A --dry-run`.
  - Scenario "Cleaning a checkout keeps the keys": record the checksum of `~/.config/job-search-agent/.env`, run `git clean -x -f -d` in the clone, and record that the checksum is unchanged.
  - Scenarios "Switching branches after a personal run" and "Merging after a personal run": create a branch with one commit, switch to it, switch back, merge it, and record that no step conflicts and `~/.config/job-search-agent/.env` and the personal files are unchanged (checksums).
- [ ] 8.3 Evals: in the main checkout after migration, run `evals/run_evals.py --criteria-only` on the personal profile and record that it scores the personal cases. Run it with `--default-profile` and record the "no cases to run" exit.
- [ ] 8.4 Run the live e2e suite with keys available. Verify it passes.
  - Scenario "Run after a reset": evaluate one URL with `--default-profile`, run `scripts/profile.sh reset-default`, evaluate it again with `--default-profile`, and record that the second output has no `(cached from ...)` suffix.
- [ ] 8.5 Run an automated review of the diff (`/code-review`) and resolve or record each finding.

## 9. Scenario coverage

- [ ] 9.1 Write the implementation PR description as a table with one row per scenario in the three delta specs: scenario, verifying test or task, result. Verify every scenario has a row and no row is empty.

## 10. Migration (after merge, main checkout)

- [ ] 10.1 Run the design's Migration Plan in the main checkout. Verify `propose_jobs.py` uses the personal profile and its shortlist matches one taken before migration.
- [ ] 10.2 In each existing worktree: clear the skip-worktree bits, run `git checkout -- .env data/resume.md data/job_preferences.md` (the worktree's copies duplicate the main checkout's data), merge `master`, run `rm -rf data`, then `cp -r ../../profiles/personal profiles/` if the worktree runs on personal data. Rebase open branches onto `master`.
