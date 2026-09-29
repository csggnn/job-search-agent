# personal-data-protection Delta

## Purpose

API keys and personal profile data stay out of git. The ignore rules protect them without
any git index setup, so ordinary git use cannot commit them and branch operations do not
conflict over them.

## ADDED Requirements

### Requirement: Keys and personal profile data are ignored by git
`.env` and every file of the personal profile (resume, job preferences, generated state and
eval set) SHALL be ignored by git. `git status` SHALL NOT list them, and `git add -A` SHALL
NOT stage them.

#### Scenario: After setup and a personal run
- **WHEN** a user creates `.env`, adds a personal resume and job preferences, runs the
  pipeline on the personal profile and runs `git status`
- **THEN** none of these files, nor the personal database, rubric, search queries or eval
  set, is listed
- **AND** `git add -A` stages none of them

#### Scenario: A new worktree holds no keys or personal data
- **WHEN** a worktree is created with `git worktree add` and nothing is copied into it
- **THEN** it contains no `.env` and no personal profile files

### Requirement: Keys are configured from a committed template
The repository SHALL commit `.env.example`, listing every API key the pipeline reads, with
no values. The repository SHALL NOT commit `.env`. The unit test suite SHALL verify, without
network access, that `.env.example` names every API key the pipeline reads.

#### Scenario: Fresh clone
- **WHEN** a user clones the repository
- **THEN** `.env.example` exists and names every API key the pipeline reads
- **AND** `.env` does not exist

#### Scenario: A key is missing from the template
- **WHEN** the pipeline reads an API key that `.env.example` does not name and the unit suite runs
- **THEN** the test fails and names the missing key

### Requirement: Personal data needs no git index manipulation
Setting up and using keys and the personal profile SHALL require no `git update-index` or
other command that changes git's index flags. The README SHALL contain no such command.

#### Scenario: README setup
- **WHEN** a user follows the README from clone to a first personal run
- **THEN** no step runs `git update-index`

### Requirement: Branch operations do not conflict over personal data
Switching or merging branches SHALL NOT conflict over keys or personal profile data, and
SHALL leave them unchanged.

#### Scenario: Switching branches after a personal run
- **WHEN** a user runs the pipeline on the personal profile and switches to another branch
- **THEN** the switch completes without error
- **AND** `.env` and the personal profile files are unchanged

#### Scenario: Merging after a personal run
- **WHEN** a user runs the pipeline on the personal profile and merges another branch
- **THEN** no conflict involves `.env` or a personal profile file
