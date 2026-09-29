# Tasks

Each task names the spec scenarios it verifies. A scenario is verified by a test named after
it, or by a manual check whose result is recorded under the task. Section 9 collects every
scenario into the table the implementation PR description carries.

Unit tests run with `podman-compose exec job-search python3 -m unittest discover -s tests/unit`.

## 1. Keys

- [ ] 1.1 Commit `.env.example` holding the key names of the current `.env` template with no values. Remove `.env` from the index (`git rm --cached .env`) and add it to `.gitignore`. Scenario "Fresh clone" (personal-data-protection): verified in 8.2.
- [ ] 1.2 Remove `env_file` from `docker-compose.yml`. Verify `podman-compose up -d` starts in a checkout without `.env`, and that an edited `.env` applies to the next command without recreating the container. Record the result.
- [ ] 1.3 Add `config.API_KEYS` listing every key name the pipeline can read, including `ANTHROPIC_API_KEY` and `GROQ_API_KEY`. Add `test_env_example_names_every_api_key`, which fails naming each missing entry. Scenario "A key is missing from the template": verify by removing one key from `.env.example`, running the suite and recording the failure message, then restoring it.
- [ ] 1.4 Make `scripts/check_setup.py` read key names from `config.API_KEYS` and take its keys through `config`.

## 2. Profile layout and resolution

- [ ] 2.1 `git mv data/resume.md data/job_preferences.md profiles/default/`. Replace the `data/` and `evals/` data rules in `.gitignore` with: `profiles/personal/`, the generated files and `evals/` of `profiles/default/`. Verify with `git check-ignore -v` on each path listed in the design's directory tree.
- [ ] 2.2 Implement profile resolution in `config.py` as a pure function of the checkout root and the `JOBSEARCH_PROFILE` value, following the design's table. Expose `PROFILE_DIR`, `PROFILE_NAME`, `DEFAULT_PROFILE_DIR` and `EVALS_DATA_DIR`. Raise the half-filled error on first path use, not at import. Remove `DATA_DIR`. Unit tests against temporary directories, one per scenario (profile-selection): `test_fresh_clone_runs_the_default_profile`, `test_personal_files_select_the_personal_profile`, `test_one_personal_file_is_missing`, `test_forcing_the_default_profile`, `test_forcing_an_incomplete_personal_profile`, `test_unknown_profile_name`.
- [ ] 2.3 Switch `storage.DB_PATH`, `rubric.RUBRIC_PATH` and `discovery.QUERIES_PATH` to `config.PROFILE_DIR`. Add `test_one_personal_file_is_missing_writes_no_database`: with a half-filled personal profile, opening storage raises and creates no database file in either profile. Verify `grep -rn "DATA_DIR" jobsearch evals scripts tests` returns nothing.
- [ ] 2.4 Set `evals/dataset.py` `EVALS_DIR` to `config.EVALS_DATA_DIR`. Scenarios "Evals use the active profile's eval set and rubric" and "A profile without an eval set does not use another profile's": verified in 8.3.
- [ ] 2.5 Make `tests/e2e/test_e2e_pipeline.py` read the database path from `config.PROFILE_DIR`.

## 3. Unit tests read the committed sample

- [ ] 3.1 Point `DefaultDataTest` at `config.DEFAULT_PROFILE_DIR`. Give the section helpers it calls (`config.home_address()` and the target-location resolution) an optional preferences-text argument, so the test does not read the active profile. Scenarios "Required section removed" and "Resolved locations differ from the Location entries" (default-profile-data): verify by removing `## Scoring Notes` from the sample and reordering its `## Location` entries, recording each failure, then restoring the file.
- [ ] 3.2 Scenarios "Home address resolves", "Target locations come from the Location section" and "Scoring guidance is present" (default-profile-data): verify the existing `DefaultDataTest` tests pass against `profiles/default/`, and that the sample home address geocodes through OpenRouteService from inside the container. Record the coordinate.
- [ ] 3.3 Scenario "Personal profile does not affect the check": create a personal profile whose preferences lack `## Scoring Notes`, run the unit suite, and record that `DefaultDataTest` passes. Delete the personal profile afterwards.

## 4. Setup verification

- [ ] 4.1 When the personal profile is active, make `scripts/check_setup.py` report each of `## Location`, `## Home Address` and `## Scoring Notes` that is missing or empty, naming the file. Put the section check in a pure function with a unit test, `test_personal_preferences_lack_a_section`. Scenario "Personal preferences lack a section": also run `check_setup.py` against a personal profile without `## Home Address` and record the output.

## 5. Backup and restore

- [ ] 5.1 Write `scripts/profile.sh` with `backup <folder>` and `restore <folder>` as in the design. It resolves the checkout from its own location and uses only `cp` and `rm`.
- [ ] 5.2 Add `tests/unit/test_profile_sh.py`. Each test copies the script into a temporary checkout-like tree and runs it with `bash`. One test per scenario (personal-profile-backup): `test_backup_to_a_new_folder`, `test_target_folder_holds_other_files`, `test_target_folder_holds_an_earlier_backup`, `test_restore_after_data_loss`, `test_restore_over_newer_data`, `test_folder_is_not_a_backup`.

## 6. Worktrees

- [ ] 6.1 In `~/.claude/commands/start-task.md` (outside the repo), replace the skip-worktree section with the design's two copy commands.
- [ ] 6.2 Scenarios "New worktree without copied data" (profile-selection) and "A new worktree holds no keys or personal data" (personal-data-protection): create a worktree without copying, list its `.env` and `profiles/personal/`, run the unit suite, and record the active profile.
- [ ] 6.3 Scenario "Worktree with copied personal data": copy `.env` and `profiles/personal/` into a worktree, evaluate one URL there, and record that the run used the personal profile and that the main checkout's personal database row count and modification time are unchanged.

## 7. Docs

- [ ] 7.1 Rewrite the `README.md` setup: `.env` created from `.env.example`, the sample run first, then the personal profile with no cleanup step, no `git update-index`. Add a section on the personal profile covering its files, backup, restore, the `git clean -x` warning and the warning about backing up during a running command. Add a developer section on worktrees covering the two copy commands and the statement that changes to a worktree's data stay in its copy. Apply the first-mention link rule. Scenarios "README setup", "First mention of a committed file", "First mention of .env", "First mention of a personal file", "Developer looks for a safe test setup", "User looks for how to protect personal data": verify on the pushed branch on GitHub by clicking each first-mention link, and record the result per scenario.
- [ ] 7.2 Update `CLAUDE.md`: replace "Git-invisible files" with the profile layout and the untracked `.env`, name the `git clean -x` risk, and update the paths in the evals rules (`data/evaluations.db`, `evals/ads/`).
- [ ] 7.3 Update `docs/architecture.md`, `docs/evals.md` and `docs/roadmap.md`, and the docstrings in `evals/__init__.py`, `evals/draft.py`, `jobsearch/preselection.py` and `tests/e2e/test_e2e_pipeline.py`. Verify `grep -rn "skip-worktree\|data/resume\|data/job_preferences\|data/evaluations\|evals/cases\|evals/ads" --include=*.md --include=*.py . | grep -v openspec` returns nothing.

## 8. Acceptance

- [ ] 8.1 Run the full unit suite. Verify all tests pass.
- [ ] 8.2 Fresh-clone run: clone the branch into a new folder and follow the README.
  - Scenarios "Fresh clone" (personal-data-protection) and "Fresh clone runs the default profile": record that `.env.example` exists, `.env` does not, and the first run uses the default profile.
  - Scenario "Fresh clone proposes jobs": run `propose_jobs.py 2` and record the summary.
  - Scenario "Personal files select the personal profile" and "Switching from the sample to a personal profile": add a second fictional profile as the personal profile, run `propose_jobs.py 2`, and record that no sample job appears.
  - Scenario "Personal run leaves the default profile unchanged": record the row counts of both databases.
  - Scenario "Returning to the default profile": run `propose_jobs.py` with `JOBSEARCH_PROFILE=default` and record that only sample jobs appear.
  - Scenario "After setup and a personal run": record `git status --short` and `git add -A --dry-run`.
  - Scenarios "Switching branches after a personal run" and "Merging after a personal run": create a branch with one commit, switch to it, switch back, merge it, and record that no step conflicts and `.env` and the personal files are unchanged (checksums).
- [ ] 8.3 Evals: in the main checkout after migration, run `evals/run_evals.py --criteria-only` on the personal profile and record that it scores the personal cases. Run it with `JOBSEARCH_PROFILE=default` and record the "no cases to run" exit.
- [ ] 8.4 Run the live e2e suite with keys available. Verify it passes.
- [ ] 8.5 Run an automated review of the diff (`/code-review`) and resolve or record each finding.

## 9. Scenario coverage

- [ ] 9.1 Write the implementation PR description as a table with one row per scenario in the four delta specs: scenario, verifying test or task, result. Verify every scenario has a row and no row is empty.

## 10. Migration (after merge, main checkout)

- [ ] 10.1 Run the design's Migration Plan in the main checkout. Verify `propose_jobs.py` uses the personal profile and its shortlist matches one taken before migration.
- [ ] 10.2 In each existing worktree: clear the skip-worktree bits, merge `master`, run the two copy commands. Rebase open branches onto `master`.
