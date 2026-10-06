# personal-data-protection Delta

## Purpose

API keys and personal profile data stay out of git. Keys live outside every checkout, and
the ignore rules protect personal profile data without any git index setup, so ordinary git
use cannot commit them and branch operations do not conflict over them.

## ADDED Requirements

### Requirement: Personal profile data is ignored by git
Every file of the personal profile (resume, job preferences, generated state and eval set)
SHALL be ignored by git. `git status` SHALL NOT list them, and `git add -A` SHALL NOT stage
them.

#### Scenario: After setup and a personal run
- **WHEN** a user creates `~/.config/job-search-agent/.env`, adds a personal resume and job
  preferences, runs the pipeline on the personal profile and runs `git status`
- **THEN** none of these files, nor the personal database, rubric, search queries or eval
  set, is listed
- **AND** `git add -A` stages none of them

### Requirement: Keys are read from one file outside every checkout
The pipeline SHALL read API keys from `~/.config/job-search-agent/.env`. Every checkout and
worktree SHALL read the same file. Git operations in a checkout SHALL NOT change or delete
it, and the pipeline SHALL NOT write it.

#### Scenario: A worktree uses the shared keys
- **WHEN** a worktree is created, nothing is copied into it, and the user runs the pipeline
  there with `--default-profile`
- **THEN** API calls use the keys in `~/.config/job-search-agent/.env`

#### Scenario: Cleaning a checkout keeps the keys
- **WHEN** a user runs `git clean -x -f -d` in a checkout
- **THEN** `~/.config/job-search-agent/.env` is unchanged

#### Scenario: Key directory is missing
- **WHEN** `~/.config/job-search-agent/` does not exist and the user starts the container
- **THEN** the container starts and `~/.config/job-search-agent/` exists, empty
- **AND** a command that reads an API key fails naming the key and
  `~/.config/job-search-agent/.env`

### Requirement: Keys are configured from a committed template
The repository SHALL commit `.env.example`, listing every API key the pipeline reads, with
no values. The repository SHALL NOT commit `.env`. The unit test suite SHALL verify, without
network access, that `.env.example` names every API key the pipeline reads.

#### Scenario: Fresh clone
- **WHEN** a user clones the repository
- **THEN** `.env.example` exists and names every API key the pipeline reads
- **AND** the checkout contains no `.env`

#### Scenario: A key is missing from the template
- **WHEN** the pipeline reads an API key that `.env.example` does not name and the unit suite runs
- **THEN** the test fails and names the missing key

### Requirement: Personal data needs no git index manipulation
Setting up and using keys and the personal profile SHALL require no `git update-index` or
other command that changes git's index flags. The README SHALL contain no such command.

#### Scenario: README setup
- **WHEN** a user follows the README from clone to a first personal run
- **THEN** no step runs `git update-index`

### Requirement: The README documents backing up the personal profile
The README section on the personal profile SHALL give a command that copies the personal
profile to a target folder, and a command that restores it. The restore command SHALL leave
the current personal profile unchanged when the copy fails, and SHALL remove files that the
backup does not hold. The section SHALL state that `git clean -x` deletes the personal
profile, and that a copy taken while a pipeline command runs may hold an inconsistent
database.

#### Scenario: User looks for how to protect personal data
- **WHEN** a user reads the README section on the personal profile
- **THEN** it gives the backup and restore commands
- **AND** it warns about `git clean -x` and about copying during a running command

#### Scenario: Restore over newer data
- **WHEN** the personal profile holds files that the backup does not and the user runs the
  README restore command
- **THEN** the personal profile equals the backup

### Requirement: Branch operations do not conflict over personal data
Switching or merging branches SHALL NOT conflict over keys or personal profile data, and
SHALL leave them unchanged.

#### Scenario: Switching branches after a personal run
- **WHEN** a user runs the pipeline on the personal profile and switches to another branch
- **THEN** the switch completes without error
- **AND** the keys and the personal profile files are unchanged

#### Scenario: Merging after a personal run
- **WHEN** a user runs the pipeline on the personal profile and merges another branch
- **THEN** no conflict involves a personal profile file
