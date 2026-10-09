# Proposal

## Why

Saved evaluations in `data/evaluations.db` can be inspected only with `sqlite3` queries.
There is no view that lists the jobs in score order with their links, or shows one job's
scores, criteria and notes together. This is the browsing half of CSG-9.

## What Changes

- A command starts a local web UI. The user opens it in the host browser.
- The UI is a component separate from the pipeline. It does not require the resume, the job
  preferences or API keys, and it can be removed without changing the pipeline.
- The UI is read-only. It does not change, create or migrate the evaluations database.
- The UI shows only what the database stores. It computes no score.
- A list page shows every saved evaluation, by default in descending compatibility score.
  Each row shows title, company, compatibility score, commute, reviewed state, application
  status, evaluation date and a link to the original ad. A remote job shows its commute as
  remote.
- The list can be filtered by application status, by reviewed state and by a maximum
  commute, and sorted by any column. Each filtered and sorted view has its own URL.
- A detail page shows one evaluation: its scores, commute, status, notes and rationale, the
  per-criterion scores and rationale, and a link to the original ad.
- The UI keeps working when the database gains columns, such as the ad text CSG-62 plans to
  store, or lacks columns it expects. It hides a missing field and names it in a warning.
- An automated UI test suite runs the browsing scenarios in a browser against fixed test
  data. It reads no user data.
- Continuous integration runs the UI test suite on pull requests that change the UI, and
  fails any pull request whose schema change breaks a column the UI reads.
- The documentation gives the command that starts the UI and the command that runs the UI
  tests.

## Capabilities

### New Capabilities
- `database-browser`: read-only web UI listing, filtering, sorting and showing saved
  evaluations.

### Modified Capabilities

## Impact

- New UI component with its own entry point and UI test suite.
- New dependencies for the web server and the browser tests. The pipeline's dependencies do
  not change.
- The CI configuration runs the UI tests.
- `README.md`, `docs/architecture.md` and `CLAUDE.md` describe the UI and its tests.
- The pipeline, the eval tools and the database schema do not change.
