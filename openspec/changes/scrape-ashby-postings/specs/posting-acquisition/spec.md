# Spec Delta

## Purpose

Obtaining the title, company, location and description of a job posting from its URL, for
job boards whose posting pages do not serve the posting content.

## ADDED Requirements

### Requirement: An Ashby posting URL is scraped from Ashby's published posting data
The system SHALL recognize an Ashby posting URL: host `jobs.ashbyhq.com` and path
`/<board>/<job-id>`, where `<job-id>` is a UUID, with an optional trailing slash and any
query string. For such a URL, the scraped post SHALL hold:

- `job_title`: the posting's title.
- `company`: the board name from the URL.
- `location`: the posting's primary location.
- `description`: the posting's plain-text description, verbatim, followed by the remote
  policy lines below.

The system SHALL NOT use an LLM to produce the post of an Ashby posting.

#### Scenario: Ashby posting URL
- **WHEN** the user runs `evaluate_job_post.py https://jobs.ashbyhq.com/alan/7cb7ef50-e248-4967-ace5-d2a0d97f395e`
  and the posting is published on the `alan` board
- **THEN** the evaluation completes with the posting's title, `alan` as the company and the
  posting's primary location

#### Scenario: Query string and trailing slash
- **WHEN** the URL carries a `?source=` query string or a trailing slash
- **THEN** the scraped post is the same as for the URL without them

#### Scenario: Same posting scraped twice
- **WHEN** the same Ashby posting URL is scraped twice and the published posting has not
  changed
- **THEN** both scraped posts are identical

### Requirement: The description of an Ashby posting states its remote policy
The description of an Ashby posting SHALL end with one line per remote policy field that
Ashby publishes for the posting, in this order:

- `Workplace type: <value>`, when the workplace type is not null.
- `Remote: yes` or `Remote: no`, when the remote flag is not null.
- `Other locations: <location>; <location>`, when the posting has secondary locations, in
  the order Ashby lists them.

A field that Ashby publishes as null or empty SHALL produce no line. The lines SHALL be
separated from the description text by one blank line.

#### Scenario: Hybrid posting with secondary locations
- **WHEN** the posting has workplace type `Hybrid`, remote flag true and secondary locations
  `Brussels` and `Madrid`
- **THEN** the description ends with `Workplace type: Hybrid`, `Remote: yes` and
  `Other locations: Brussels; Madrid`, one per line

#### Scenario: No remote policy published
- **WHEN** the posting's workplace type and remote flag are null and it has no secondary
  locations
- **THEN** the description is the posting's plain-text description, with no added line

### Requirement: An Ashby posting that cannot be obtained fails with a scrape error
The system SHALL raise a scrape error naming the URL when the posting data cannot be
obtained or does not hold the posting: the board does not exist, the job id is not on the
board (closed posting), the request fails, or the response is not the expected JSON. A post
with a blank title, company, location or description SHALL be rejected as for any other
scraped post.

#### Scenario: Closed posting
- **WHEN** the job id in the URL is not among the board's published postings
- **THEN** scraping raises a scrape error that names the URL

#### Scenario: Unknown board
- **WHEN** Ashby responds that the board does not exist
- **THEN** scraping raises a scrape error that names the URL

#### Scenario: Malformed response
- **WHEN** the response body is not JSON or holds no list of postings
- **THEN** scraping raises a scrape error that names the URL

### Requirement: Other URLs are scraped as before
A URL that is not an Ashby posting URL SHALL be scraped with the existing page fetch and
extraction, including the LinkedIn guest-page mapping.

#### Scenario: Non-posting Ashby URL
- **WHEN** the URL is a board root such as `https://jobs.ashbyhq.com/alan` or its path does
  not end in a UUID
- **THEN** the URL is scraped with the existing page fetch and extraction

#### Scenario: LinkedIn URL
- **WHEN** the URL is a LinkedIn job view URL
- **THEN** it is scraped through the LinkedIn guest posting address, as before
