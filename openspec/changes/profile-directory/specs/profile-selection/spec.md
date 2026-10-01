# profile-selection Delta

## Purpose

A profile is one candidate as a unit: a resume and job preferences, plus the generated state
and eval set when they exist.
The default profile holds the committed sample candidate. The personal profile holds the
user's own candidate. Each run uses one profile and reads and writes only that profile's data.

## ADDED Requirements

### Requirement: The active profile follows from the personal files
When no profile is forced, a run SHALL use the personal profile when both a personal resume
and personal job preferences exist, and the default profile when neither exists. When only
one of the two exists, the run SHALL fail with an error naming the missing file.

#### Scenario: Fresh clone runs the default profile
- **WHEN** a user runs the pipeline on a fresh clone with only keys set up
- **THEN** the run uses the default profile

#### Scenario: Personal files select the personal profile
- **WHEN** a personal resume and personal job preferences exist and the user runs the pipeline
- **THEN** the run uses the personal profile

#### Scenario: One personal file is missing
- **WHEN** a personal resume exists without personal job preferences and the user runs the pipeline
- **THEN** the run fails with an error naming the missing job preferences file
- **AND** neither profile's database is written

### Requirement: A profile can be forced
Setting `JOBSEARCH_PROFILE=default` SHALL select the default profile whether or not personal
files exist. Setting `JOBSEARCH_PROFILE=personal` SHALL select the personal profile, and SHALL
fail with an error naming the missing file unless both personal files exist. Any other
non-empty value SHALL fail with an error listing the accepted values.
Setting `JOBSEARCH_PROFILE=auto` or leaving it unset SHALL select the profile as when no
profile is forced.

#### Scenario: Forcing the default profile
- **WHEN** personal files exist and the user runs the pipeline with `JOBSEARCH_PROFILE=default`
- **THEN** the run uses the default profile

#### Scenario: Forcing an incomplete personal profile
- **WHEN** no personal files exist and the user runs the pipeline with `JOBSEARCH_PROFILE=personal`
- **THEN** the run fails with an error naming the missing files

#### Scenario: Unknown profile name
- **WHEN** the user runs the pipeline with `JOBSEARCH_PROFILE=sample`
- **THEN** the run fails with an error listing `default`, `personal` and `auto`

### Requirement: Profiles do not share generated state or eval sets
A profile's evaluations database, compiled rubric, search queries and eval set, when they
exist, SHALL belong to that profile only. A run SHALL read and write only the active
profile's.

#### Scenario: Personal run leaves the default profile unchanged
- **WHEN** the user runs the pipeline on the default profile, then on the personal profile
- **THEN** the default profile's database holds only the default run's evaluations
- **AND** the personal profile's database holds only the personal run's evaluations

#### Scenario: Returning to the default profile
- **WHEN** the user has run both profiles and runs `propose_jobs.py` with `JOBSEARCH_PROFILE=default`
- **THEN** the shortlists contain only jobs evaluated for the default profile

#### Scenario: Evals use the active profile's eval set and rubric
- **WHEN** the personal profile has an eval set and the user runs `evals/run_evals.py` on the personal profile
- **THEN** it scores the personal profile's cases against the personal profile's rubric

#### Scenario: A profile without an eval set does not use another profile's
- **WHEN** only the personal profile has an eval set and the user runs `evals/run_evals.py`
  with `JOBSEARCH_PROFILE=default`
- **THEN** it reports that the default profile has no eval cases
- **AND** it does not read the personal profile's cases

### Requirement: A worktree uses its own copy of profile data
A new worktree SHALL run on the default profile. When personal profile data is copied into
the worktree, the worktree SHALL run on that copy. Runs in a worktree SHALL NOT change the
main checkout's data.

#### Scenario: New worktree without copied data
- **WHEN** a worktree is created and nothing is copied into it
- **THEN** the unit suite passes
- **AND** the active profile is the default profile

#### Scenario: Worktree with copied personal data
- **WHEN** the main checkout's personal profile data is copied into a worktree
  and the user runs the pipeline there
- **THEN** the run uses the personal profile
- **AND** the main checkout's personal database is unchanged

### Requirement: The README documents isolated runs on personal data
The README SHALL describe running on personal data in a worktree with copied data, as one
way to run without changing the real data. It SHALL state that evaluations, caches, eval
runs and input edits made in a worktree stay in its copy and do not reach the main checkout.

#### Scenario: Developer looks for a safe test setup
- **WHEN** a developer reads the README developer section
- **THEN** it lists the commands that create a worktree and copy the personal profile into it
- **AND** it states that changes to the worktree's data do not reach the main checkout

### Requirement: Setup verification checks the personal profile
When the personal profile is active, `scripts/check_setup.py` SHALL report each section the
pipeline reads (`## Location`, `## Home Address`, `## Scoring Notes`) that is missing or
empty in the personal job preferences, before any pipeline run.

#### Scenario: Personal preferences lack a section
- **WHEN** the personal job preferences have no `## Home Address` and the user runs `scripts/check_setup.py`
- **THEN** it reports the missing `## Home Address` and names the personal job preferences file

### Requirement: The README links a profile file at its first mention
The first time the README mentions a profile file (a resume or job preferences, default or
personal) or `.env`, it SHALL give that file's full path: from the checkout root for a
profile file, and `~/.config/job-search-agent/.env` for `.env`. When the file is committed,
the mention SHALL be a relative Markdown link to it. The first mention
of `.env` SHALL link to `.env.example`. The first mention of a personal file SHALL link to
the README section that describes the personal profile.

#### Scenario: First mention of a committed file
- **WHEN** a user reads the README on GitHub and reaches the first mention of the default
  job preferences
- **THEN** the mention shows the file's full path
- **AND** clicking it opens the file

#### Scenario: First mention of .env
- **WHEN** a user reads the README on GitHub and reaches the first mention of `.env`
- **THEN** the mention shows `~/.config/job-search-agent/.env`
- **AND** it links to `.env.example`

#### Scenario: First mention of a personal file
- **WHEN** a user reads the README on GitHub and reaches the first mention of the personal
  job preferences
- **THEN** the mention shows the file's full path
- **AND** clicking it opens the README section that describes the personal profile
