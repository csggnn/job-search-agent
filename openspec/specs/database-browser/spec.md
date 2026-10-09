# database-browser Specification

## Purpose

A local, read-only web UI for browsing the saved evaluations in the evaluations database:
a sortable, filterable list of jobs and a detail view of one evaluation.

## Requirements

### Requirement: The UI is served locally for a given database file
A command SHALL start the UI for a database file named on its command line. The UI SHALL be
reachable from a browser on the host at `http://localhost:8000` and SHALL NOT be reachable
from other machines. The command SHALL NOT require the resume, the job preferences or API
keys.

#### Scenario: User opens the UI
- **WHEN** the user starts the UI command with `data/evaluations.db` and opens
  `http://localhost:8000` in a host browser
- **THEN** the browser shows the list page for that database

#### Scenario: No resume or preferences
- **WHEN** `data/` holds an evaluations database and no resume or job preferences, and the
  user starts the UI command with that database
- **THEN** the UI serves the list page

### Requirement: The UI does not change the database
The UI SHALL NOT write, create or migrate the evaluations database. Every page SHALL leave
the database file byte-identical. When the database file does not exist, the list page SHALL
state that there are no saved evaluations, and no database file SHALL be created.

#### Scenario: Browsing leaves the database unchanged
- **WHEN** the user opens the list page, a filtered list and a detail page
- **THEN** the database file is byte-identical to its state before the UI started

#### Scenario: No database yet
- **WHEN** the named database file does not exist and the user opens the list page
- **THEN** the page states that there are no saved evaluations
- **AND** no database file exists afterwards

### Requirement: The UI tolerates schema differences
The UI SHALL render every page when the database schema differs from the one it expects.
Columns beyond those the UI shows SHALL NOT change any page. Every expected column except
`evaluations.id` and `evaluation_criteria.evaluation_id` SHALL be optional: when an optional
column is missing, the UI SHALL NOT show its field, SHALL NOT offer a filter or sort that
needs it, and SHALL ignore URL parameters for that filter or sort. When a table or its
mandatory column is missing, the UI SHALL treat the table as absent: without `evaluations`
the list page states that there are no saved evaluations, and without `evaluation_criteria`
the detail page shows no criteria. A job with no title SHALL be listed with a placeholder
title that links to its detail page.

When an expected table or column is missing, every page SHALL show a warning that names
each missing table and column. When the database file does not exist, no warning SHALL be
shown.

#### Scenario: Database with an extra column
- **WHEN** the `evaluations` table has an additional text column holding a value
- **THEN** the list page and the detail page render with the same content as without it
- **AND** no warning is shown

#### Scenario: Optional column missing
- **WHEN** the `evaluations` table has no `notes` column and no `commute_score` column
- **THEN** the list page and the detail page render without notes and without commute
- **AND** the maximum-commute filter is not offered
- **AND** every page shows a warning naming `evaluations.notes` and
  `evaluations.commute_score`

#### Scenario: Criteria table missing
- **WHEN** the database has no `evaluation_criteria` table
- **THEN** the detail page renders without a criteria section
- **AND** every page shows a warning naming the `evaluation_criteria` table

#### Scenario: Mandatory column missing
- **WHEN** the `evaluations` table has no `id` column
- **THEN** the list page states that there are no saved evaluations
- **AND** the warning names `evaluations.id`

#### Scenario: Job without a title
- **WHEN** an evaluation has no title
- **THEN** its row shows a placeholder title that links to its detail page

### Requirement: The list page shows every saved evaluation
The list page SHALL show one row per saved evaluation. Every value shown SHALL be a stored
database value or a direct rendering of one; the UI SHALL compute no score. The default
order SHALL be descending compatibility score. Each row SHALL show title, company,
compatibility score, commute, reviewed state, application status, evaluation date and a
link to the original ad. The ad link SHALL open in a new tab. A remote job SHALL show its
commute as remote. An unknown commute SHALL be shown as unknown. The title SHALL link to the
job's detail page. The page SHALL show the number of rows displayed.

#### Scenario: Default order
- **WHEN** the database holds three evaluations with compatibility scores 82, 60 and 75
- **THEN** the list page shows them in the order 82, 75, 60

#### Scenario: Unknown commute
- **WHEN** an evaluation has no commute score
- **THEN** its row shows the commute as unknown

#### Scenario: Remote job
- **WHEN** an evaluation is marked remote
- **THEN** its row shows the commute as remote

#### Scenario: Ad link
- **WHEN** the user clicks a row's ad link
- **THEN** the original ad URL opens in a new tab

### Requirement: The list can be filtered and sorted through the URL
The list page SHALL accept a filter on application status (`new`, `applied`, `discarded`
or all), a filter on reviewed state (reviewed, not reviewed or all) and a maximum commute in
the stored commute unit. The maximum commute SHALL keep rows whose commute is at or below it,
remote rows and rows with an unknown commute. All filters SHALL combine. The user SHALL be
able to sort by any shown column, ascending or descending, by clicking its header. Every filter and sort state SHALL be encoded in the page URL, so that
loading the URL reproduces the view. An unknown filter or sort value SHALL be ignored.

#### Scenario: Filter by status
- **WHEN** the user selects status `new`
- **THEN** only evaluations with application status `new` are listed
- **AND** the row count reflects the filtered rows

#### Scenario: Maximum commute
- **WHEN** the database holds jobs with commutes 20, 45 and unknown, and a remote job, and
  the user sets a maximum commute of 30
- **THEN** the jobs with commute 20, unknown and remote are listed
- **AND** the job with commute 45 is not listed

#### Scenario: Combined filters
- **WHEN** the user selects status `new` and not reviewed
- **THEN** only evaluations that are `new` and not reviewed are listed

#### Scenario: Sort by column
- **WHEN** the user clicks the company header
- **THEN** rows are ordered by company ascending
- **AND** clicking the header again orders them descending

#### Scenario: URL reproduces the view
- **WHEN** the user copies the URL of a filtered and sorted list and loads it in a new tab
- **THEN** the new tab shows the same rows in the same order

#### Scenario: Unknown sort value
- **WHEN** the user loads the list page with a sort value that names no shown column
- **THEN** the list is shown in the default order

### Requirement: The detail page shows one evaluation in full
The detail page SHALL show the job's title, company, a link to the original ad,
compatibility score, commute, commute address, office days, evaluation date,
application status, reviewed state, status reason, notes, compatibility rationale, what
works well and what does not work. It SHALL show a table of the evaluation's criteria with
name, type, weight, matched, score and rationale. A request for an evaluation that does not
exist SHALL return a not-found page.

#### Scenario: Detail page content
- **WHEN** the user clicks a job title on the list page
- **THEN** the detail page shows that job's fields and notes
- **AND** it lists every criterion stored for that evaluation

#### Scenario: Missing evaluation
- **WHEN** the user requests the detail page of an evaluation id that does not exist
- **THEN** the UI returns a not-found page

### Requirement: UI scenarios run as an automated browser test suite
A test suite SHALL drive the UI in a headless browser and check the scenarios of this
capability. Each test SHALL run against a database it builds with fixed rows. The suite
SHALL NOT read or write `data/`, and SHALL run without API keys or network access beyond the
local UI. A separate test SHALL fail when the pipeline's database schema lacks a column the
UI reads.

#### Scenario: Suite runs offline on test data
- **WHEN** a developer runs the UI test suite
- **THEN** the tests pass against their own databases
- **AND** `data/` is unchanged

#### Scenario: Schema drift
- **WHEN** the pipeline's schema drops or renames a column the UI reads
- **THEN** the schema contract test fails

### Requirement: Continuous integration runs the UI tests
Continuous integration SHALL run the UI test suite on every pull request that changes the
UI code, the UI tests or the UI container configuration. It SHALL run the schema contract
test on every pull request. A failing test SHALL fail the pull request's check.

#### Scenario: Pull request changes the UI
- **WHEN** a pull request changes a file of the UI
- **THEN** the UI test suite runs and its result is reported as a check on the pull request

#### Scenario: Pull request changes the pipeline schema
- **WHEN** a pull request renames a column of the `evaluations` table that the UI reads
- **THEN** the schema contract test fails the pull request's check
