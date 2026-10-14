# Tasks

## 1. System diagram

- [x] 1.1 Update `docs/structurizr/workspace.dsl`: `boards` description "Indeed, LinkedIn,
  Ashby", and `engine -> boards` "Searches postings; fetches Ashby postings" with technology
  "JobSpy, HTTPS". Re-render `containers.png` with `scripts/export_diagram.sh`. Done in the
  design pull request.

## 2. Test fixture

- [ ] 2.1 Create a fixture file under `tests/unit/` holding a board response from
  `https://api.ashbyhq.com/posting-api/job-board/alan`, trimmed to the posting
  `7cb7ef50-e248-4967-ace5-d2a0d97f395e` and one posting with null `workplaceType` and
  `isRemote`. Give one of them at least one secondary location. Verify the file parses as
  JSON and no `.py` file inlines its text.

## 3. Ashby path

- [ ] 3.1 Add Ashby posting URL recognition to `jobsearch/scrape.py`, with unit tests for
  hit cases (plain, query string, trailing slash, uppercase host) and miss cases (board
  root, application path, non-UUID job segment, other host). Verify the tests pass.
- [ ] 3.2 Add the board fetch, the job lookup and the job-to-post mapping, and route Ashby
  posting URLs to them in `scrape_post()`. Add unit tests against the fixture: the mapped
  post for each fixture posting, the remote policy lines and their absence, a job id not on
  the board, a 404, a request exception, a non-JSON body, a body with no `jobs` list, and a
  non-Ashby URL still going through `fetch_page_text()` and `extract_post()`. Verify the
  tests pass with no network access and no API key.

## 4. Documentation

- [ ] 4.1 Update `docs/architecture.md`: the `scrape.py` row of the module table, and
  "Scraping a URL" with the Ashby path, its failure cases and the fact that
  `evals/capture.py` does not use it. Verify the section lists Ashby next to LinkedIn.
- [ ] 4.2 Check `README.md` for statements about supported URLs and update any that the
  change makes inaccurate. Verify no statement contradicts the spec.

## 5. Checks

- [ ] 5.1 Run `podman-compose exec job-search python3 -m unittest discover -s tests/unit`,
  `scripts/ruff.sh check .` and `scripts/ruff.sh format --check .`. Verify all pass.
- [ ] 5.2 In the container, call `scrape_post()` on
  `https://jobs.ashbyhq.com/alan/7cb7ef50-e248-4967-ace5-d2a0d97f395e?source=xgA7zbmLWw`
  twice. Verify both calls return the same post, with company `alan`. If the posting is
  closed, verify the call raises `ScrapeError` naming the URL.
