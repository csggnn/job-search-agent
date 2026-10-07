# Tasks

Each task names the spec scenarios it verifies. A scenario is verified by a test named after
it, or by a manual check whose result is recorded under the task. Section 7 reports the
deviations from the specs, the design and these tasks in the implementation PR description.

Unit tests run with `podman-compose exec job-search python3 -m unittest discover -s tests/unit`.

## 1. Keys

- [x] 1.1 Commit `.env.example` holding the key names of the current `.env` template with no values. Remove `.env` from the index (`git rm --cached .env`). Scenario "Fresh clone" (personal-data-protection): verified in 6.2.
  - Key migration, checked on 2026-10-07: `~/.config/job-search-agent/.env` holds a value for every key in `config.API_KEYS`, with mode 600. No checkout of the repository holds a `.env`.
- [x] 1.2 In `docker-compose.yml`, remove `env_file` and mount `${HOME}/.config/job-search-agent` read-only at `/config`. Make `config.py` call `load_dotenv("/config/.env")`, which does nothing when the file is absent. Verify that `podman-compose up -d` starts when the directory exists without `.env`, that it creates the directory empty and starts when the directory is missing, that an edited `.env` applies to the next command without recreating the container, and that writing `/config/.env` from inside the container fails because the mount is read-only. Record the results. Scenario "Key directory is missing" (personal-data-protection): the recorded start and `require_env` error.
  - Versions: podman-compose 1.0.6, podman 4.9.3.
  - Directory present, no `.env`: the container starts. `config.require_env("TAVILY_API_KEY")` raises `RuntimeError: required environment variable 'TAVILY_API_KEY' is not set: add it to ~/.config/job-search-agent/.env`.
  - Directory missing: podman-compose creates `~/.config/job-search-agent/` empty and the container starts. Commands then behave as with the directory present and no `.env`.
  - `.env` edited from `TAVILY_API_KEY=first` to `TAVILY_API_KEY=second`: the next command in the same container reads `second`.
  - Writing from inside the container: `echo X=1 >> /config/.env` fails with `cannot create /config/.env: Read-only file system`. `touch /config/new` fails with `Read-only file system`.
- [x] 1.3 Add `config.API_KEYS` listing every key name the pipeline can read, including `ANTHROPIC_API_KEY` and `GROQ_API_KEY`. Requiredness stays in `config.require_env` and `check_setup.py`. Add `test_env_example_names_every_api_key`, which fails and names each missing entry. Scenario "A key is missing from the template": verify by removing one key from `.env.example`, running the suite and recording the failure message, then restoring it.
  - Removing `GROQ_API_KEY` from `.env.example` fails `test_env_example_names_every_api_key` with `AssertionError: Lists differ: ['GROQ_API_KEY'] != []`.
- [x] 1.4 Make `scripts/check_setup.py` take its keys through `config`: import `jobsearch.config`, which loads `/config/.env`, and read the Tavily key with `config.require_env`.
- [x] 1.5 Make `scripts/check_setup.py` report each key in `config.API_KEYS` that is unset, naming `config.KEYS_FILE`.
  - With `TAVILY_API_KEY` and `GROQ_API_KEY` set empty: prints `MISSING: TAVILY_API_KEY is not set in ~/.config/job-search-agent/.env` and the same line for `GROQ_API_KEY`, exits 1, and makes no API call.
  - With every key set: prints `OK: every API key is set`, then runs the Tavily, Anthropic and Groq calls and exits 0.
- [x] 1.6 Document the keys. `README.md` setup: `mkdir -p ~/.config/job-search-agent`, `.env` created there from `.env.example`, `chmod 600`. `CLAUDE.md` and `docs/architecture.md`: keys in `~/.config/job-search-agent/.env`, the read-only `/config` mount, `config.API_KEYS` and the test that checks `.env.example` against it.

## 2. Data directory and template

- [x] 2.1 `git mv data/resume.md data/job_preferences.md data.example/`. Replace the `data/` and `evals/` data rules in `.gitignore` with `/data/`. Verify with `git check-ignore -v` on each path listed under `data/` in the design's directory tree, and that no file under `data.example/` is ignored.
  - `git check-ignore -v` matches `.gitignore:6:/data/` for `data/resume.md`, `data/job_preferences.md`, `data/evaluations.db`, `data/compatibility_rubric.json`, `data/search_queries.json`, `data/evals/cases.json`, `data/evals/cases.json.bak`, `data/evals/ads/x.txt` and `data/evals/runs/x.json`. It matches no file under `data.example/` (exit 1), and does not match `tests/fixtures/data/x`.
- [x] 2.2 In `config.py`, add `SAMPLE_DIR` (`data.example/`) and `EVALS_DATA_DIR` (`DATA_DIR/evals`).
- [x] 2.3 In `evals/dataset.py`, derive `CASES_PATH`, `BACKUP_PATH`, `ADS_DIR` and `RUNS_DIR` from `config.EVALS_DATA_DIR`. Update the docstrings in `evals/__init__.py` and `evals/draft.py` that name the eval data paths.

## 3. Missing user data

- [x] 3.1 Add `config.require_data()`, which raises when `RESUME_PATH` or `JOB_PREFERENCES_PATH` is missing. The error names each missing file. Without `data/`, it gives `cp -r data.example data`. With `data/` present, it directs the user to restore the file or to remove `data/` and create it again from the template, and gives no command that copies template files into `data/`. Unit tests against temporary directories: `test_fresh_clone` (data-directory), which checks that both files are named with the command, and `test_one_file_is_missing`, which checks that only the missing file is named, with the restore-or-recreate guidance.
- [x] 3.2 Call `config.require_data()` after argument parsing and before any other work in `evaluate_job_post.py`, `discover_jobs.py`, `propose_jobs.py`, `scripts/recompile_rubric.py`, `evals/capture.py`, `evals/draft.py` and `evals/run_evals.py`. Add `test_one_file_is_missing_makes_no_api_call`: with `data/` holding only a resume, `evaluate_job_post.py`'s entry point raises, and patched `scrape_post` and `load_or_compile_rubric` are not called. Scenario "Fresh clone" (data-directory): verified in 6.2.
- [x] 3.3 Make `scripts/check_setup.py` report a missing resume or job preferences, naming each with the guidance of 3.1, and each of `## Location`, `## Home Address` and `## Scoring Notes` that is missing or empty in `data/job_preferences.md`, naming the file. It continues with the key checks in both cases, and exits 1 before any API call. Put the data check in a pure function with unit tests `test_preferences_lack_a_section` and `test_no_user_data` (data-directory). Also run `check_setup.py` without `data/` and with a `data/job_preferences.md` lacking `## Home Address`, and record both outputs.
  - The pure function is `config.empty_preferences_sections()`. `test_no_user_data` checks `config.missing_data_message()` against temporary paths.
  - Without `data/`: prints `missing user data: /workspace/data/resume.md, /workspace/data/job_preferences.md. In the checkout root, create data/ from the template: cp -r data.example data`, then `OK: every API key is set`, and exits 1 with no API call.
  - With `data/job_preferences.md` lacking `## Home Address`: prints `## Home Address is missing or empty in /workspace/data/job_preferences.md` and `OK: every API key is set`, and exits 1 with no API call.
- [x] 3.4 In `tests/e2e/test_e2e_pipeline.py`, fail in setup with `cp -r data.example data` when `data/resume.md` or `data/job_preferences.md` is missing, and state in the docstring that the test writes to the checkout's `data/` and belongs in a checkout holding the example data.

## 4. Unit tests read the template

- [x] 4.1 Point `DefaultDataTest` at `config.SAMPLE_DIR`. Give the section helpers it calls (`config.home_address()` and the target-location resolution) an optional preferences-text argument, so the test does not read `data/`. Compare the resolved target locations with the `## Location` entries in any order. Scenario "Required section removed" (default-profile-data): verify by removing `## Scoring Notes` from the template, recording the failure, then restoring the file. Scenarios "Resolved locations differ from the Location entries" and "Resolved locations in another order" (default-profile-data): verify by patching `_resolve_target_locations` to return an empty list, the entries with one omitted, the entries with one added, and the entries reversed, and recording each result.
  - `## Scoring Notes` removed from the template: `test_scoring_notes_present` fails with `## Scoring Notes missing or empty in /workspace/data.example/job_preferences.md`.
  - Empty, one entry omitted and one entry added: each fails `test_target_locations_come_from_the_location_section` with `target locations differ from the ## Location entries`. Entries reversed: the test passes.
- [x] 4.2 Scenarios "Home address resolves", "Target locations come from the Location section" and "Scoring guidance is present" (default-profile-data): verify the `DefaultDataTest` tests pass against `data.example/`, and that the template home address geocodes through OpenRouteService from inside the container. Record the coordinate.
  - The four `DefaultDataTest` tests pass against `data.example/`. `Rue des Halles 4, 1000 Bruxelles, Belgium` geocodes through OpenRouteService from inside the container to `[4.350082, 50.850078]` (lon, lat).
- [x] 4.3 Scenarios "User data does not affect the check" and "Checkout without user data" (default-profile-data): run the unit suite once with a `data/job_preferences.md` lacking `## Scoring Notes` and once without `data/`, and record that `DefaultDataTest` passes both times.
  - With `data/job_preferences.md` lacking `## Scoring Notes`: 182 tests pass, the four `DefaultDataTest` tests among them.
  - Without `data/`: 182 tests pass, the four `DefaultDataTest` tests among them.

## 5. Docs

- [x] 5.1 Rewrite the `README.md` setup: create `data/` with `cp -r data.example data`, run the example data, then add personal data by removing `data/`, creating it again from `data.example/` and replacing the resume and job preferences. No step runs `git update-index`. Add that `data/` is ignored by git and holds data that cannot be regenerated, that deleting the checkout or running `git clean -x` in it deletes `data/`, and that backing it up beforehand is the user's responsibility, done by copying it while no pipeline command runs. Add a developer section on separate checkouts (a clone or a worktree): create the example data in a second checkout, copy `data/` from one checkout to another, and state that changes to one checkout's `data/` do not reach another. Scenarios "README setup" (personal-data-protection), "Developer sets up a checkout for the example data", "Developer moves personal data to another checkout" and "Developer wipes a checkout" (data-directory): verify by reading the rendered README on the pushed branch, and record the result per scenario.
  - Read on `feat/csg-37-profile-directory` as rendered by GitHub, on 2026-10-07.
  - "README setup" (personal-data-protection): no step runs `git update-index`. The README holds no `update-index` command.
  - "Developer sets up a checkout for the example data" (data-directory): "Separate checkouts for development" creates a second checkout with `git worktree add`, creates its `data/` with `cp -r data.example data`, and states that runs in the second checkout leave the first checkout's `data/` unchanged.
  - "Developer moves personal data to another checkout" (data-directory): the same section gives `rm -rf <other-checkout>/data` and `cp -r <personal-checkout>/data <other-checkout>/data`.
  - "Developer wipes a checkout" (data-directory): "Your data" states that deleting the checkout or running `git clean -x` deletes `data/`, that backing it up is the user's responsibility, and gives `cp -r data ~/job-search-data-backup`.
- [x] 5.2 Update `CLAUDE.md`: replace "Git-invisible files" with the `data/` and `data.example/` layout and the separate-checkouts practice, and update the paths in the evals rules (`evals/ads/` becomes `data/evals/ads/`).
- [x] 5.3 Update `docs/architecture.md`, `docs/evals.md` and `docs/roadmap.md`, and the docstring in `jobsearch/preselection.py`. Verify `grep -rnP "(?<!data/)evals/(cases|ads|runs)|skip-worktree" --include=*.md --include=*.py . | grep -v openspec` returns nothing.
  - The grep returns nothing.

## 6. Acceptance

- [x] 6.1 Run the full unit suite. Verify all tests pass.
  - 185 tests pass, after the order-independent location comparison of 4.1 and the review fixes of 6.5.
- [x] 6.2 Fresh-clone run: clone the branch into a new folder and follow the README.
  - Scenarios "Fresh clone" (personal-data-protection) and "Fresh clone" (data-directory): record that `.env.example` exists, `.env` does not, and `propose_jobs.py` before `data/` exists fails naming both files and `cp -r data.example data`, and creates no `data/`.
  - Scenario "Fresh clone proposes jobs": create `data/` from the template, run `propose_jobs.py 2` and record the summary.
  - Scenario "Switching from the sample to a personal profile": follow the README step that adds personal data with a second fictional candidate, run `propose_jobs.py 2`, and record that no example job appears.
  - Scenario "After setup and a run": capture one eval case, run `evals/run_evals.py --criteria-only`, and record `git status --short` and `git add -A --dry-run`.
  - Scenarios "Switching branches after a run" and "Merging after a run": create a branch with one commit, switch to it, switch back, merge it, and record that no step conflicts and `~/.config/job-search-agent/.env` and the files in `data/` are unchanged (checksums).
  - Results, on 2026-10-07, in a clone of `feat/csg-37-profile-directory` at `2e556e7`, with the existing `~/.config/job-search-agent/.env` (step 1 leaves it unchanged):
    - "Fresh clone" (personal-data-protection): the clone holds `.env.example` and no `.env`.
    - "Fresh clone" (data-directory): `propose_jobs.py 2` before `data/` exists fails with `RuntimeError: missing user data: /workspace/data/resume.md, /workspace/data/job_preferences.md. Create data/ from the template, in the checkout root: cp -r data.example data`. No `data/` is created.
    - "Fresh clone proposes jobs": `70 discovered -> 70 complete -> 54 fresh -> 53 distinct openings -> 53 not yet evaluated -> 6 selected (1 LLM call)`. Both shortlists propose 2 jobs out of 6 evaluated: Senior Front-End Engineer at Vivid Resourcing (commute unknown) and Senior Product Design Engineer at Jobgether (no commute, remote). Of the 6 evaluated jobs, Koda Tech routes to 10.4 min.
    - "Switching from the sample to a personal profile": with a second fictional candidate (data engineer, Ghent), `propose_jobs.py 2` reports `2 job(s) proposed out of 6 evaluated` in both shortlists. None of the 6 URLs evaluated for the example user appears in the run output.
    - "After setup and a run": after `evals/capture.py`, `evals/draft.py --all` and `evals/run_evals.py --criteria-only`, `data/` holds `evals/cases.json`, `evals/ads/` and `evals/runs/`. `git status --short` and `git add -A --dry-run` print nothing.
    - "Switching branches after a run" and "Merging after a run": a branch with one commit, a switch to it, a switch back, a second switch to it, a switch back and a `--no-ff` merge all complete with no conflict. One sha256 over `~/.config/job-search-agent/.env` and every file in `data/` is `76833c4aa49c175f` before and after each step.
- [x] 6.3 Separate checkouts.
  - Scenario "A worktree uses the shared keys": from the clone of 6.2, create a worktree, create its `data/` from the template and copy nothing else into it, evaluate one URL, and record that the API calls succeed.
  - Scenario "Copying the directory transfers the user data": evaluate a URL in the clone, replace the worktree's `data/` with a copy of the clone's `data/`, evaluate the same URL in the worktree, and record the `(cached from ...)` suffix. Run `evals/run_evals.py --criteria-only` in both and record that they score the same cases.
  - Scenario "Cleaning a checkout keeps the keys": record the checksum of `~/.config/job-search-agent/.env`, run `git clean -x -f -d` in the clone as the last step, and record that the checksum is unchanged.
  - Results, on 2026-10-07:
    - "A worktree uses the shared keys": a worktree of the 6.2 clone holds no `.env`. With `data/` created from the template, `evaluate_job_post.py` scrapes, compiles the rubric and routes the commute (26.2 min) with no error.
    - "Copying the directory transfers the user data": after the worktree's `data/` is replaced with a copy of the clone's, evaluating the same URL prints `(cached from 2026-10-07T10:55:36.395378+00:00)` in both checkouts. After drafting ground truth in the clone and copying `data/` again, `evals/run_evals.py --criteria-only` scores the same case, `darwind-data-engineer`, in both, with criteria accuracy 1.0 on 11 labels.
    - "Cleaning a checkout keeps the keys": `git clean -x -f -d` in the clone removes `data/`. The sha256 of `~/.config/job-search-agent/.env` is `527085e8c3f61696` before and after.
- [x] 6.4 Run the live e2e suite in a checkout holding the example data, with keys available. Verify it passes.
  - In this worktree with `data/` created from the template, on 2026-10-07: `Ran 2 tests in 91.659s`, `OK (skipped=1)`. The full-pipeline test passes against `https://canonical.com/careers/6707824`. The discovery smoke test is skipped: it runs only with `RUN_DISCOVERY_SMOKE = True`.
- [x] 6.5 Run an automated review of the diff (`/code-review`) and resolve or record each finding.
  - Review of `master...HEAD` on 2026-10-07, 10 findings:
    - Fixed: the preferences section check accepted a `(fill in ...)` placeholder and rejected a section starting with a `###` subheading (tests `test_preferences_section_holds_the_placeholder`, `test_section_starting_with_a_subheading_has_content`). `.gitignore` matched `data/` at any depth; it lists `/data/`. `check_setup.py` made API calls with incomplete data; it exits 1 before them. The e2e setup checked the resume only; it checks both files.
    - No change, covered by the Migration Plan (8.1, 8.2): existing `evals/cases.json`, `evals/ads/` and `evals/runs/` are no longer ignored; checkouts with skip-worktree edits need the bits cleared before pulling.
    - No change, required by the spec: `evals/capture.py --list-cases` and `evals/run_evals.py --compare` call `require_data()` although they read no resume or preferences.
    - No change, outside this change: the OpenSpec note in `CLAUDE.md` comes from `master`.
    - Fixed after a spec change: `cp -r data.example data` creates `data/data.example/` when `data/` exists, so it did not restore a single missing file. With `data/` present, the guidance directs the user to restore the file or to remove `data/` and create it again from the template. No message copies template files into an existing `data/` (`test_one_file_is_missing`). With `data/` holding only a resume, `check_setup.py` prints `missing user data: /workspace/data/job_preferences.md. In the checkout root, restore the missing file, or remove data/ and create it again from the template: cp -r data.example data`.

## 7. Deviations

- [ ] 7.1 Write a table of deviations into the implementation PR description: each spec scenario, design decision or task verification that could not be met as written, had to be changed, or was met only with a qualification. Columns: item, expected, observed, resolution. Verify that each change made during implementation to the delta specs, `design.md` or this file's task text has a row.

## 8. Migration (after merge)

- [ ] 8.1 Run the design's Migration Plan in each checkout that holds personal data. Verify `propose_jobs.py` returns a shortlist matching one taken before migration, and that `evals/run_evals.py --criteria-only` scores the personal cases.
- [ ] 8.2 In each other checkout: clear the skip-worktree bits, run `git checkout -- data/resume.md data/job_preferences.md`, merge `master`, run `rm -rf data`, then create `data/` from `data.example/` or from a copy of another checkout's `data/`. Rebase open branches onto `master`.
