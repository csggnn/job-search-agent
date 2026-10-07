# data-directory Delta

## Purpose

User data is the resume, the job preferences, the files the pipeline generates from them, the
evaluations database and the eval set. A checkout holds its user data in one directory that
is copied as a unit. The repository ships the example user's data as a template in
`data.example/`.

## ADDED Requirements

### Requirement: User data is held in one directory per checkout
The pipeline and the eval tools SHALL read and write user data in `data/` at the
checkout root. User data SHALL comprise the resume, the job preferences, the compiled rubric,
the search queries, the evaluations database and the eval set. No user data SHALL be written
outside `data/`.

#### Scenario: Copying the directory transfers the user data
- **WHEN** a user evaluates a URL in one checkout, copies that checkout's `data/` to
  another checkout and evaluates the same URL there
- **THEN** the second evaluation is returned from the cache
- **AND** `evals/run_evals.py` in the second checkout scores the same cases as in the first

### Requirement: A run without user data fails and states how to create it
Every pipeline command and eval command SHALL fail when `data/` lacks the resume or the
job preferences. The error SHALL name each missing file and give the command that creates
`data/` from the template, `cp -r data.example data`. The command SHALL fail before any
API call or database write. No command SHALL read the template in place of missing user
data.

#### Scenario: Fresh clone
- **WHEN** a user runs `propose_jobs.py` on a fresh clone with only API keys set up
- **THEN** the run fails with an error naming the missing resume and job preferences
- **AND** the error gives the command that creates `data/` from the template
- **AND** no database file is created

#### Scenario: One file is missing
- **WHEN** `data/` holds a resume and no job preferences and the user runs
  `evaluate_job_post.py <url>`
- **THEN** the run fails with an error naming the missing job preferences
- **AND** it does not read the template job preferences
- **AND** no API call is made

### Requirement: Setup verification reports missing preferences sections
`scripts/check_setup.py` SHALL report each section the pipeline reads (`## Location`,
`## Home Address`, `## Scoring Notes`) that is missing or empty in the user's job
preferences, and SHALL name the job preferences file. It SHALL report a missing resume or
job preferences file, naming each, with the command that creates `data/` from the template.

#### Scenario: Preferences lack a section
- **WHEN** the user's job preferences have no `## Home Address` and the user runs
  `scripts/check_setup.py`
- **THEN** it reports the missing `## Home Address` and names the job preferences file

#### Scenario: No user data
- **WHEN** `data/` does not exist and the user runs `scripts/check_setup.py`
- **THEN** it reports the missing resume and job preferences
- **AND** it gives the command that creates `data/` from the template

### Requirement: The README describes example and personal data in separate checkouts
The README SHALL give the command that creates `data/` from the template. It SHALL
describe working on the example data and on personal data in separate checkouts, each a
clone or a worktree. It SHALL give the command that copies `data/` from one checkout to
another, and SHALL state that changes to one checkout's user data do not reach another
checkout. It SHALL state that deleting a checkout or running `git clean -x` in it deletes
its `data/`, and that backing up `data/` beforehand is the user's responsibility. It SHALL
give the command that copies `data/` to a backup location.

#### Scenario: Developer sets up a checkout for the example data
- **WHEN** a developer with personal data in one checkout reads the README to test on the
  example data
- **THEN** it describes creating a second checkout and creating its `data/` from the
  template
- **AND** it states that runs in the second checkout leave the first checkout's user data
  unchanged

#### Scenario: Developer moves personal data to another checkout
- **WHEN** a developer reads the README to run personal data in a new checkout
- **THEN** it gives the command that copies `data/` into the new checkout

#### Scenario: Developer wipes a checkout
- **WHEN** a developer reads the README before deleting a checkout or running `git clean -x`
  in it
- **THEN** it states that this deletes the checkout's `data/` and that backing it up is the
  user's responsibility
- **AND** it gives the command that copies `data/` to a backup location
