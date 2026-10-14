# Design

## Context

See proposal.md for motivation and specs/posting-acquisition/spec.md for the required
behavior.

### Containers and relationships

The change is inside the job search engine. In `docs/structurizr/workspace.dsl`:

- `engine -> tavily` "Posting extract (manual URL), office-address search" is the current
  path for a manual URL.
- `engine -> boards` "Searches postings" (JobSpy) is the engine's only access to job boards.
  `boards` is described as "Indeed, LinkedIn".
- `evals -> tavily` "Posting extract (capture)" is the eval harness's path for a URL.

### Scrape module

- `scrape_post(url)` is `extract_post(fetch_page_text(url))`. `fetch_page_text()` fetches
  through Tavily, mapping a LinkedIn URL with `public_posting_url()` first. `extract_post()`
  asks the extraction model for the four `POST_FIELDS` and passes the result to
  `validate_post()`.
- `evaluation.evaluate_job()` calls `scrape_post()` when no post is passed in.
  `evaluate_job_post.py` reaches scraping only through it.
- `evals/capture.py` calls `fetch_page_text()` and `extract_post()` separately, because it
  stores the raw page text as the eval ad.
- Callers handle `ScrapeError` as "this posting cannot be scraped". Other exceptions
  propagate as failures.

### Ashby posting API

- `GET https://api.ashbyhq.com/posting-api/job-board/<board>` returns
  `{"jobs": [...], "apiVersion": ...}` with every published posting of the board. It needs
  no authentication. An unknown board returns HTTP 404.
- The API serves boards, not single postings. A board can hold more than 100 postings.
- Each job holds `id` (the UUID in the posting URL), `title`, `location`,
  `secondaryLocations` (a list of objects with a `location` text), `workplaceType`
  (`Hybrid`, `OnSite`, `Remote` or null), `isRemote` (true, false or null),
  `descriptionPlain` and `descriptionHtml`.
- Python's default urllib User-Agent receives HTTP 403.

### Tests

- Unit tests use stdlib `unittest`, run offline in the pipeline container, and hold no
  API keys. `PublicPostingUrlTest` and `ValidatePostTest` in `tests/unit/test_units.py`
  cover the scrape module.
- CLAUDE.md: scraped ad text is data and is never inlined into a `.py` file.

## Goals / Non-Goals

**Goals:**
- The unit tests for the Ashby path run offline, with no network access and no API key.
- Scraping a URL that is not an Ashby posting URL makes the same calls as before.
- Every failure to obtain an Ashby posting surfaces to callers as `ScrapeError`, so their
  existing handling applies.

**Non-Goals:**
- Capturing Ashby postings into the eval set through `evals/capture.py`.
- Discovering Ashby postings by listing boards.
- Compensation, department, team and the HTML description.

## Decisions

### Ashby postings bypass page fetch and extraction in `scrape_post()`

`scrape_post(url)` checks whether `url` is an Ashby posting URL. If so, it builds the post
from the posting API. Otherwise it runs `extract_post(fetch_page_text(url))` as before. All
new code lives in `jobsearch/scrape.py`. The internal structure of the Ashby path is left to
the implementation.

`fetch_page_text()` and `extract_post()` are unchanged, so `evals/capture.py` keeps its
behavior and fails on an Ashby URL as before.

Alternative: make `fetch_page_text()` return the posting text from the API and keep LLM
extraction. Rejected because the post would still pass through the extraction model, which
abridges the description differently on each call (CSG-67), and it costs an LLM call for
fields the API already provides.

### URL recognition

An Ashby posting URL has host `jobs.ashbyhq.com` (case-insensitive) and a path of exactly
two segments, `/<board>/<job-id>`, with an optional trailing slash, where `<job-id>` is a
UUID. The query string and fragment are ignored. Any other URL, including a board root, an
application form path or a non-UUID job segment, is not an Ashby posting URL and takes the
existing path.

### Fetching the board

The posting data is fetched with `requests`, which `jobsearch/commute.py` already uses, with
a browser User-Agent and a timeout. The board name is URL-quoted into the endpoint path.
`includeCompensation` is not requested.

`ScrapeError` naming the posting URL is raised when:

- the request raises a `requests` exception, including a timeout,
- the response status is not 200,
- the body is not JSON, or has no `jobs` list,
- no job's `id` equals the job id in the URL.

Alternative: `urllib.request`. Rejected because `requests` is already a dependency and the
codebase uses it for HTTP.

### Mapping a job to a post

| Post field | Source |
| -- | -- |
| `job_title` | `title` |
| `company` | the board name from the URL, as written in the URL |
| `location` | `location` |
| `description` | `descriptionPlain`, then the remote policy lines from the spec |

The post is passed through `validate_post()` with the posting URL as source, as an
extracted post is.

Company from the board name: the API response has no company name. The board name is the
company's Ashby handle (`alan` for Alan). The compatibility score reads the description,
which names the company.

Alternative: extract the company name from the description with the extraction model.
Rejected because it reintroduces an LLM call and its run-to-run variance for one field.

Alternative: read the company name from the posting page's HTML title. Rejected because it
adds a second request to an undocumented page format.

### System diagram

The engine gains an access to Ashby, a job board. This changes an existing relationship and
adds no element:

- `boards` description: "Indeed, LinkedIn, Ashby".
- `engine -> boards`: "Searches postings; fetches Ashby postings", technology
  "JobSpy, HTTPS".

The DSL and the rendered `containers.png` are updated in the design pull request, so both
are in place before implementation.

Alternative: a separate `ashby` external system. Rejected because Ashby is a job board and
`boards` already groups the job boards the engine accesses.

### Tests with a stored board response

A fixture file under `tests/unit/` holds a board response trimmed to a few jobs, taken from
the live API. It covers a posting with workplace type, remote flag and secondary locations,
and a posting with null workplace type and remote flag and no secondary locations. Tests
replace the HTTP call with a mock that returns the fixture, a 404 or a malformed body. URL
recognition is tested on its own, with hit and miss cases.

## Risks / Trade-offs

- [The board name differs from the company name, e.g. a lowercase or hyphenated handle] →
  The office-address search and the stored `company` show the handle. The description,
  which the scoring reads, names the company.
- [The posting API is undocumented as a contract and can change] → A change surfaces as
  `ScrapeError` naming the URL, not as a wrong post, because the job lookup and
  `validate_post()` require every field.
- [Each Ashby scrape downloads the whole board] → One request per evaluation. Evaluations of
  the same URL are cached in the evaluations database.
