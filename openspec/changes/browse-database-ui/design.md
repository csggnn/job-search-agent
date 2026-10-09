# Design

## Context

See proposal.md for motivation and specs/database-browser/spec.md for the required behavior.

### Database

- `evaluations` has one row per job, keyed by an integer `id`. `evaluation_criteria` rows
  belong to an evaluation through `evaluation_id`. Showing one job with its criteria needs
  both keys.
- The pipeline adds columns through `storage._MIGRATIONS`, and CSG-62 plans more. The schema
  a reader finds depends on the pipeline version that last opened the file.
- `combined_score` is computed by `ranking.rank_evaluations()` and is not stored. Showing it
  requires pipeline code.
- `commute_score` is in weighted minutes, lower is better. `NULL` means no office address
  was resolved. A fully remote job has `is_remote` 1 and `commute_score` 0. A commute
  threshold has to treat `NULL` and remote rows explicitly.

### Pipeline modules

- Every `storage` read function opens the database through `_get_connection()`, which
  creates the file, the tables and missing columns. No `storage` read path is read-only.
- Importing `jobsearch.storage` imports `jobsearch.config`, which loads the API keys from
  `/config/.env` at import time. Any import of either module loads the keys.
- CLAUDE.md requires every entry point to call `config.require_data()`. The
  `data-directory` spec requires it of pipeline and eval commands only. The two differ for an
  entry point that is neither.

### Container

- The pipeline container mounts the checkout read-write and the API key directory, and
  publishes no ports. A process in it can write the checkout and read the keys, and is not
  reachable from the host browser.
- Commands run through `podman-compose exec` in containers started by `podman-compose up -d`.
  `podman-compose` 1.0.6 has no `--profile` option, so `up -d` starts every service.

### Tests and CI

- Tests use stdlib `unittest` and no other runner.
- `.github/workflows/unit-tests.yml` builds the pipeline image with podman and runs
  `tests/unit` on every pull request. A test placed in `tests/unit` runs on every pull
  request with no new workflow, using only the pipeline image's packages.

## Goals / Non-Goals

**Goals:**
- Read-only holds by construction. A code path that writes the database or the checkout
  fails instead of writing.
- The UI shows personal data. It is reachable only from the host, not from other machines on
  the network.
- The UI imports no pipeline code. Its only coupling to the pipeline is the database
  schema. The UI does not load API keys.
- The pipeline's container image is unaffected by the UI.
- The UI's expectations of the database schema are stated in one place, and a pipeline
  schema change that breaks them fails a test.
- The UI test suite starts and stops everything it uses. It needs no running UI and no
  manual step.

**Non-Goals:**
- Authentication, multi-user access or a production web server.
- Pagination. The database holds tens of rows.

## Decisions

### Top-level `ui/` package

The UI lives in `ui/`, outside `jobsearch/`:

```
ui/
  __init__.py
  columns.py       the columns the UI reads; imports nothing
  browser.py       create_app(db_path); imports flask and the stdlib only
  browse_db.py     entry point
  templates/       base.html, list.html, detail.html
  Dockerfile
  requirements.txt
tests/ui/test_browser_ui.py      browser scenarios, run in the ui container
tests/unit/test_ui_contract.py   schema contract, run in the pipeline container
```

Removing the UI is removing `ui/`, `tests/ui/`, the contract test, the compose service and
the UI workflow.

### No pipeline imports

No module in `ui/` imports from `jobsearch`. The UI shows stored values only. The default
order is `compatibility_score` descending. A maximum-commute filter on the stored
`commute_score` covers the commute side of the choice that `combined_score` folds into one
number.

Alternative: import `ranking.rank_evaluations()` and show `combined_score`. Rejected because
it makes the UI depend on pipeline code for one derived value.

The entry point does not call `config.require_data()`. The UI reads neither the resume nor
the job preferences, makes no API call and writes nothing, which are the conditions that
check exists for. CLAUDE.md's rule is narrowed to pipeline and eval entry points. The
`data-directory` spec already scopes it that way.

### Database path on the command line

`python3 -m ui.browse_db --db PATH [--host HOST] [--port 8000]` takes the database path as
a required argument. The documented command passes `data/evaluations.db`. No UI module names
`data/`. `--host` defaults to `$UI_HOST`, else `127.0.0.1`, so a launch outside the container
listens on loopback only. The `ui` compose service sets `UI_HOST=0.0.0.0`, which the
published port needs.

Alternative: `storage.DB_PATH`. Rejected because importing `storage` imports `config`, which
loads the API keys.

### Explicit column list, intersected with the actual schema

`ui/columns.py` holds two tuples, `EVALUATION_COLUMNS` and `CRITERION_COLUMNS`: the columns
the UI selects and shows, each with its display label. It also names each table's mandatory
column: `id` for `evaluations`, `evaluation_id` for `evaluation_criteria`.

On each request, `ui/browser.py` reads `PRAGMA table_info` for both tables and intersects the
result with the expected columns. The `SELECT` names only present columns, never `*`.
Columns added to the tables later are never read, so they cannot affect rendering. A table
that does not exist, or that lacks its mandatory column, is treated as absent. Reading the
schema per request means a migration made while the UI runs shows on the next page load.

Only the two keys are mandatory. Making `id` optional would leave the list without detail
links and the detail route without a lookup key. Making `evaluation_id` optional would leave
criteria rows with no evaluation to belong to. Every other column has no dependent beyond
its own field, its filter or its sort.

The expected columns minus the present ones form the warning list. A base template renders
it as one banner on every page. A missing database file produces no list and no banner.

### Templates loop over present columns

The list and detail templates iterate over the present columns and render each with its
label. Three columns have a formatter: `job_title` (detail link, with "(untitled)" for a
missing or empty value), `url` (ad link in a new tab) and `commute_score` (remote when
`is_remote` is 1, unknown when `NULL`). A missing column is absent from the loop and needs no
condition in the template. The filters are the only template parts with a presence check:
status, reviewed and maximum commute each render only when their column is present.

Alternative: hand-written markup per field, each wrapped in a presence check. Rejected
because it spreads one condition per field across both templates.

### Read-only connection

The connection is `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)`. SQLite rejects
every write and does not create a missing file. When the file does not exist, the UI does
not connect and renders the empty state.

Alternative: a `read_only` flag on `storage._get_connection()`. Rejected because it changes
the pipeline's storage module and imports `config`.

### Flask with Jinja templates, server-rendered

`create_app(db_path)` is the module's only public name. It returns a Flask app with two
routes, `/` and `/job/<int:id>`. `save_evaluation` updates rows in place, so a job keeps its
`id` across re-evaluations and a `/job/<id>` URL keeps pointing at it. Pages are plain HTML
with no JavaScript. Sorting and
filtering are links and a GET form, so every view is a URL. Jinja escapes every value,
including scraped ad content.

Alternative: stdlib `http.server`. It needs no dependency but requires hand-written path
matching, query parsing, response headers and an `html.escape` call per value. Flask's route
decorators, `request.args`, `abort` and template autoescaping cover the same ground with
less code to read.

### Filtering and sorting in SQL

The list route builds one `SELECT` from the query parameters. `status`, `reviewed` and
`max_commute` become `WHERE` clauses with bound parameters. `max_commute` is
`commute_score <= ? OR commute_score IS NULL`, which keeps unknown commutes. Remote rows have
`commute_score` 0 and pass. `ORDER BY` is built from constants only: the present shown
column equal to `sort`, and the SQL keyword mapped from `dir`. No request text enters the
SQL. A value outside the allowed set, or a
`max_commute` that is not a number, is ignored. A filter whose column is absent is ignored.
When `compatibility_score` is absent, the default order is the order SQLite returns.

Alternative: read all rows and filter and sort in Python. Rejected because sorting rows with
a `NULL` commute needs a custom key, which SQL's `ORDER BY` handles.

### Separate `ui` image and compose service

`ui/Dockerfile` builds from `python:3.11-slim`, installs `ui/requirements.txt` (pinned
`flask` and `playwright`) and runs `playwright install --with-deps chromium` into a shared
`PLAYWRIGHT_BROWSERS_PATH`. It sets `PYTHONDONTWRITEBYTECODE=1` and runs as a non-root
`ui` user. The pipeline's `Dockerfile` and `requirements.txt` are
unchanged.

`docker-compose.yml` adds a `ui` service:

- builds `ui/Dockerfile` with the checkout as context
- mounts the checkout read-only at `/workspace`
- does not mount the API key directory
- publishes `127.0.0.1:8000:8000`
- sets `UI_HOST=0.0.0.0`
- runs `sleep infinity`, like `job-search`

`podman-compose up -d` starts both containers. The UI is started on demand with
`podman-compose exec ui python3 -m ui.browse_db --db data/evaluations.db`, and the tests with
`podman-compose exec ui python3 -m unittest discover -s tests/ui`. Binding the host side to
`127.0.0.1` keeps the UI off the network. The read-only mount makes every write to the
checkout fail.

Alternative: run the UI in the `job-search` container. Rejected because Flask, Playwright
and Chromium would enter the pipeline image, and the UI would see the API keys.

Alternative: a compose profile so `up -d` leaves the UI container stopped. Rejected because
`podman-compose` 1.0.6 has no `--profile` option.

### UI tests: `unittest` with the Playwright sync API

`tests/ui/test_browser_ui.py` builds each test database from `ui.columns`: one
`CREATE TABLE` per tuple, then fixed rows. Schema variants cover the tolerance scenarios: an
extra text column, missing optional columns, no `evaluation_criteria` table and no
`evaluations.id`. Each test class serves `create_app(temp_db_path)` with
`werkzeug.serving.make_server` on a free port in a background thread and drives it with
headless Chromium through `playwright.sync_api`. The read-only scenario compares a hash of
the database file before and after browsing. The tests write only under a temporary
directory.

`tests/unit/test_ui_contract.py` runs `storage._SCHEMA` against an in-memory database and
checks that every column in `ui.columns` exists in it. It imports `ui.columns`, which
imports nothing, so it runs in the pipeline container without Flask.

Alternative: build the test databases from `storage._SCHEMA`. Rejected because the UI tests
would then import `storage`, `config` and `python-dotenv`, which the `ui` image does not
install.

Alternative: `pytest` with `pytest-playwright`. Rejected to keep one test runner.

### CI: a path-filtered UI workflow

`.github/workflows/ui-tests.yml` runs on pull requests that change `ui/**`, `tests/ui/**` or
`docker-compose.yml`. It builds `ui/Dockerfile` with podman and runs
`python3 -m unittest discover -s tests/ui` in it, with the checkout mounted read-only and no
secrets. It follows `unit-tests.yml`, including `persist-credentials: false`.

The contract test lives in `tests/unit`, so the existing `unit-tests.yml` runs it on every
pull request. A pipeline schema change outside the path filter is still checked.

Alternative: run the UI tests on every pull request. Rejected because the Chromium image
build adds minutes to pull requests that cannot affect the UI beyond what the contract test
checks.

## Risks / Trade-offs

- [The path filter skips the UI suite when a pull request changes a pipeline module the UI
  relies on] → The UI imports no pipeline code. Its only coupling, the schema, is checked by
  the contract test on every pull request.
- [A column the pipeline drops makes a field vanish at runtime] → The banner names it on
  every page, and the contract test fails during development.
- [Chromium and its system libraries make the `ui` image several hundred MB] → The pipeline
  image is unaffected. The browser is needed only by the UI tests.
- [The pipeline may write the database while the UI reads it, and a read can hit
  `SQLITE_BUSY`] → The pipeline's writes are short transactions. A reload retries.
- [A pipeline crash mid-write leaves a hot journal that a read-only connection cannot roll
  back, so the UI fails to open the database] → The next pipeline open rolls it back.
- [`podman-compose up -d` also starts the idle `ui` container and binds port 8000] → The
  container runs `sleep infinity` and holds no keys. `podman-compose stop ui` frees the
  port.
- [The Flask development server is single-threaded and not hardened] → It serves one local
  user on `127.0.0.1`.
