# profile-selection Delta

## Purpose

A profile is one candidate as a unit: a resume and job preferences, plus the generated state
and eval set when they exist.
The default profile holds the committed sample candidate. The personal profile holds the
user's own candidate. Each run uses one profile and reads and writes only that profile's data.

## ADDED Requirements

### Requirement: A run uses the personal profile unless the default profile is requested
A run without `--default-profile` SHALL use the checkout's personal profile. It SHALL fail
when the personal resume or the personal job preferences is missing, with an error naming
each missing file and `--default-profile`. A run with `--default-profile` SHALL use the
default profile whether or not personal files exist. Every pipeline command SHALL accept
`--default-profile`.

#### Scenario: Fresh clone runs the default profile
- **WHEN** a user runs the pipeline with `--default-profile` on a fresh clone with only keys
  set up
- **THEN** the run uses the default profile

#### Scenario: Fresh clone without the flag
- **WHEN** a user runs the pipeline without `--default-profile` on a fresh clone
- **THEN** the run fails with an error naming the missing personal resume and job
  preferences and `--default-profile`
- **AND** neither profile's database is written

#### Scenario: Personal files select the personal profile
- **WHEN** a personal resume and personal job preferences exist and the user runs the
  pipeline without `--default-profile`
- **THEN** the run uses the personal profile

#### Scenario: One personal file is missing
- **WHEN** a personal resume exists without personal job preferences and the user runs the
  pipeline without `--default-profile`
- **THEN** the run fails with an error naming the missing job preferences file and
  `--default-profile`
- **AND** neither profile's database is written

#### Scenario: Requesting the default profile
- **WHEN** personal files exist and the user runs the pipeline with `--default-profile`
- **THEN** the run uses the default profile

### Requirement: Profiles do not share generated state or eval sets
A profile's evaluations database, compiled rubric, search queries and eval set, when they
exist, SHALL belong to that profile only. A run SHALL read and write only the active
profile's.

#### Scenario: Personal run leaves the default profile unchanged
- **WHEN** the user runs the pipeline on the default profile, then on the personal profile
- **THEN** the default profile's database holds only the default run's evaluations
- **AND** the personal profile's database holds only the personal run's evaluations

#### Scenario: Returning to the default profile
- **WHEN** the user has run both profiles and runs `propose_jobs.py --default-profile`
- **THEN** the shortlists contain only jobs evaluated for the default profile

#### Scenario: Evals use the active profile's eval set and rubric
- **WHEN** the personal profile has an eval set and the user runs `evals/run_evals.py` on the personal profile
- **THEN** it scores the personal profile's cases against the personal profile's rubric

#### Scenario: A profile without an eval set does not use another profile's
- **WHEN** only the personal profile has an eval set and the user runs `evals/run_evals.py`
  with `--default-profile`
- **THEN** it reports that the default profile has no eval cases
- **AND** it does not read the personal profile's cases

### Requirement: A run can leave its profile unchanged
A run with `--scratch` SHALL read and write a temporary copy of its profile, and SHALL
leave the profile's files unchanged. The copy SHALL be removed when the command exits.
`--scratch` SHALL combine with `--default-profile`. Every pipeline command SHALL accept
`--scratch`.

#### Scenario: Scratch run on the personal profile
- **WHEN** the user evaluates a URL with `--scratch` on the personal profile
- **THEN** the evaluation completes
- **AND** the personal database, rubric and search queries are unchanged
- **AND** no temporary copy remains after the command exits

#### Scenario: Scratch run on the default profile
- **WHEN** the user evaluates a URL with `--default-profile --scratch`
- **THEN** the default profile's files are unchanged

#### Scenario: A scratch copy lasts one command
- **WHEN** the user evaluates a URL with `--scratch`, then evaluates it again with `--scratch`
- **THEN** the second evaluation is computed, not returned from the cache

### Requirement: The default profile's generated state can be reset
`scripts/reset_default_profile.sh` SHALL remove the default profile's evaluations database,
compiled rubric and search queries. It SHALL keep the default resume, job preferences and
eval set, and SHALL leave the personal profile unchanged.

#### Scenario: Reset the default profile
- **WHEN** the default profile has a database, rubric and search queries and the user runs
  `scripts/reset_default_profile.sh`
- **THEN** none of the three files exists
- **AND** the default resume, job preferences and eval set are unchanged
- **AND** the personal profile is unchanged

#### Scenario: Run after a reset
- **WHEN** the user evaluates a URL with `--default-profile`, runs
  `scripts/reset_default_profile.sh`, and evaluates the URL again with `--default-profile`
- **THEN** the second evaluation is computed, not returned from the cache

### Requirement: A worktree uses its own copy of personal data
A new worktree SHALL hold no personal profile. When the main checkout's personal profile is
copied into the worktree, runs in the worktree SHALL use that copy. Runs in a worktree SHALL
NOT change the main checkout's data.

#### Scenario: New worktree without copied data
- **WHEN** a worktree is created and nothing is copied into it
- **THEN** the unit suite passes
- **AND** a run without `--default-profile` fails naming `--default-profile`

#### Scenario: Worktree with copied personal data
- **WHEN** the main checkout's personal profile is copied into a worktree and the user runs
  the pipeline there
- **THEN** the run uses the copied personal profile
- **AND** the main checkout's personal database is unchanged

### Requirement: The README documents runs that leave real data unchanged
The README developer section SHALL describe `--scratch`, `scripts/reset_default_profile.sh`
and running on a copy of the personal profile in a worktree. It SHALL state that a scratch
copy lasts one command, and that changes to a worktree's data stay in its copy.

#### Scenario: Developer looks for a safe test setup
- **WHEN** a developer reads the README developer section
- **THEN** it describes `--scratch` and `scripts/reset_default_profile.sh`
- **AND** it gives the command that copies the personal profile into a worktree
- **AND** it states that changes to the worktree's data do not reach the main checkout

### Requirement: Setup verification checks the active profile
`scripts/check_setup.py` SHALL report each section the pipeline reads (`## Location`,
`## Home Address`, `## Scoring Notes`) that is missing or empty in the active profile's job
preferences, before any pipeline run.

#### Scenario: Personal preferences lack a section
- **WHEN** the personal job preferences have no `## Home Address` and the user runs
  `scripts/check_setup.py`
- **THEN** it reports the missing `## Home Address` and names the personal job preferences file

### Requirement: The README links a profile file at its first mention
The first time the README mentions a profile file (a resume or job preferences, default or
personal) or `.env`, it SHALL give that file's full path: from the checkout root for a
profile file, and `~/.config/job-search-agent/.env` for `.env`. When the file is committed,
the mention SHALL be a relative Markdown link to it. The first mention of `.env` SHALL link
to `.env.example`. The first mention of a personal file SHALL link to the README section
that describes the personal profile.

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
