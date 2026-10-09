# Tasks

## 1. Container and package skeleton

- [x] 1.1 Create `ui/__init__.py`, `ui/requirements.txt` (`flask`, `playwright`) and
  `ui/Dockerfile` (`python:3.11-slim`, `WORKDIR /workspace`, `PYTHONDONTWRITEBYTECODE=1`,
  install requirements,
  `playwright install --with-deps chromium`, `CMD ["sleep", "infinity"]`). Verify the
  pipeline's `Dockerfile` and `requirements.txt` are unchanged.
- [x] 1.2 Add the `ui` service to `docker-compose.yml`: build `ui/Dockerfile` with context
  `.`, mount `.:/workspace:ro`, no `/config` mount, publish `127.0.0.1:8000:8000`. Verify
  `podman-compose build ui && podman-compose up -d` succeeds,
  `podman-compose exec ui python3 -c "import flask, playwright.sync_api"` exits 0,
  `podman port` shows the port bound to `127.0.0.1` only, and
  `podman-compose exec ui touch /workspace/x` fails.

## 2. Schema contract

- [x] 2.1 Create `ui/columns.py` with `EVALUATION_COLUMNS` and `CRITERION_COLUMNS`, covering
  every field the spec shows plus `id`, `url`, `is_remote` and `evaluation_id`, each with its
  display label, and the mandatory column of each table (`id`, `evaluation_id`). Verify it
  imports nothing.
- [x] 2.2 Create `tests/unit/test_ui_contract.py`: run `storage._SCHEMA` in an in-memory
  database and assert every column in `ui.columns` exists. Verify it passes with
  `podman-compose exec job-search python3 -m unittest discover -s tests/unit`, and fails
  when a column name in `ui/columns.py` is changed to one not in the schema.

## 3. UI test suite from the scenarios

- [x] 3.1 Create `tests/ui/test_browser_ui.py` with the fixtures: a temporary database built
  from `ui.columns` with fixed rows (statuses `new`, `applied` and `discarded`, reviewed and
  not reviewed, one remote job, one unknown commute, commutes on both sides of a threshold,
  one job without a title, criteria rows), schema variants (an extra text column; no
  `notes` and no `commute_score`; no `evaluation_criteria` table; no `evaluations.id`), a
  `create_app` server on a free port in a background thread, and a headless Chromium page.
  No `__init__.py` in `tests/ui`. Verify the fixtures start and stop cleanly.
- [x] 3.2 Write one test per scenario in `specs/database-browser/spec.md` that runs against
  the UI: default order, unknown commute, remote job, ad link opens a new tab, job without a
  title, filter by status, maximum commute, combined filters, sort by column ascending and
  descending, URL reproduces the view, unknown sort value, detail page content, missing
  evaluation, extra column, optional column missing, criteria table missing, mandatory
  column missing, database unchanged and no database yet. Verify the suite runs and fails
  only because the UI does not exist yet.

## 4. UI implementation

- [x] 4.1 Create `ui/browser.py` with `create_app(db_path)`: a read-only connection
  (`mode=ro`, no connection when the file is missing), the per-request `PRAGMA table_info`
  intersection with `ui.columns`, tables treated as absent without their mandatory column,
  and no import from `jobsearch`. Add `ui/templates/base.html` with the missing-schema
  banner. Verify the database-unchanged, no-database, extra-column, mandatory-column and
  criteria-table tests pass.
- [x] 4.2 Implement the list route and `ui/templates/list.html`: one `SELECT` over the
  present columns with `status`, `reviewed` and `max_commute` filters as bound parameters,
  `sort` and `dir` limited to the present shown columns, default order compatibility score
  descending, row count, a loop over present columns with the `job_title`, `url` and
  `commute_score` formatters, and filters rendered only when their column is present. Verify
  the list, filter, sort, job-without-title and optional-column tests pass.
- [x] 4.3 Implement the detail route and `ui/templates/detail.html`: a loop over present
  columns, the criteria table when `evaluation_criteria` is present, and a 404 for an
  unknown id. Verify the detail and missing-evaluation tests pass.
- [x] 4.4 Create `ui/browse_db.py`: required `--db`, `--host` (default `$UI_HOST`, else
  `127.0.0.1`), `--port` (default 8000), no `config` import. Verify that
  `podman-compose exec ui python3 -m unittest discover -s tests/ui` passes in full, and that
  `python3 -m ui.browse_db --db <path>` serves the list for a database in a directory that
  holds no resume or job preferences.

## 5. Documentation

- [x] 5.1 Update `README.md` with the commands that start the UI and run its tests, and the
  URL to open. Verify each command runs as written.
- [x] 5.2 Update `docs/architecture.md`: describe the `ui/` component, its lack of pipeline
  imports, its schema contract, its container and its CI workflow, and add the UI to
  "Querying the database". Verify the section names each of these.
- [x] 5.3 Update `CLAUDE.md`: narrow the `config.require_data()` rule to pipeline and eval
  entry points, add the UI and `tests/ui` commands to Commands, add one line stating that UI
  changes can be checked in a browser through the Playwright MCP when it is registered, and
  replace the statement that ad-hoc querying has no dedicated tool. Verify each command runs
  as written.

## 6. Continuous integration

- [x] 6.1 Create `.github/workflows/ui-tests.yml`: on pull requests changing `ui/**`,
  `tests/ui/**` or `docker-compose.yml`, build `ui/Dockerfile` with podman and run
  `python3 -m unittest discover -s tests/ui` with the checkout mounted read-only and
  `persist-credentials: false`. Verify the workflow runs on this change's pull request and
  passes, and that `unit-tests.yml` runs the contract test.

## 7. End-to-end check

- [x] 7.1 With the user's `data/` in place, start the UI, open `http://localhost:8000` in a
  host browser and through the Playwright MCP, and open a detail page. Verify the list shows
  every saved evaluation and `data/evaluations.db` is byte-identical before and after.
- [x] 7.2 Run `podman-compose exec job-search python3 -m unittest discover -s tests/unit`.
  Verify every unit test passes, including the contract test.
