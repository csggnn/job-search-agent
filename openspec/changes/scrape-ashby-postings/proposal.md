# Proposal

## Why

`evaluate_job_post.py` fails on Ashby posting URLs (`jobs.ashbyhq.com/<board>/<job-id>`)
with `ScrapeError: could not extract content`. Ashby posting pages render their content in
the browser, and the page fetch returns no text. Ashby publishes every posting of a board as
JSON without authentication, so the posting content is available from another source. This
is CSG-66.

## What Changes

- `evaluate_job_post.py <ashby-posting-url>` produces an evaluation with no manual step.
- The title, location and description of an Ashby posting are taken verbatim from Ashby's
  published posting data. Scraping the same posting twice gives the same post.
- The description of an Ashby posting states the posting's remote policy and its additional
  locations, when Ashby publishes them.
- A closed Ashby posting, an unknown board or an unreachable posting data source fails with
  a scrape error that names the URL.
- Scraping a URL that is not an Ashby posting URL behaves as before.
- `docs/architecture.md` lists Ashby next to LinkedIn as a job board with a dedicated fetch
  path.

## Capabilities

### New Capabilities
- `posting-acquisition`: obtaining the title, company, location and description of a job
  posting from its URL, for job boards whose posting pages do not serve the posting content.

### Modified Capabilities

## Impact

- `jobsearch/scrape.py` and its unit tests.
- `evaluate_job_post.py` and `evaluation.evaluate_job()` gain Ashby support through
  `scrape_post()` with no change of their own.
- The pipeline accesses Ashby's public posting data over HTTPS.
- `docs/architecture.md` and `docs/structurizr/workspace.dsl` describe the new access.
- No new dependency.
