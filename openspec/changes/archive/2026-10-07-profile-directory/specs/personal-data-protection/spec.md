# personal-data-protection Delta

## Purpose

API keys and user data stay out of git. Keys live outside every checkout and user data is
ignored by git, so ordinary git use does not commit them and branch operations do not
conflict over them.

## ADDED Requirements

### Requirement: User data is ignored by git
Every file in `data/` SHALL be ignored by git. `git status` SHALL NOT list these files,
and `git add -A` SHALL NOT stage them.

#### Scenario: After setup and a run
- **WHEN** a user creates `data/` from the template, replaces the resume and job
  preferences, runs the pipeline and the eval tools, and runs `git status`
- **THEN** no file in `data/` is listed
- **AND** `git add -A` stages none of them

### Requirement: Keys are read from one file outside every checkout
The pipeline SHALL read API keys from `~/.config/job-search-agent/.env`. Every checkout and
worktree SHALL read the same file. Git operations in a checkout SHALL NOT change or delete
it, and the pipeline SHALL NOT write it.

#### Scenario: A worktree uses the shared keys
- **WHEN** a worktree is created, no key file is copied into it, its `data/` is created
  from the template, and the user runs the pipeline there
- **THEN** API calls use the keys in `~/.config/job-search-agent/.env`

#### Scenario: Cleaning a checkout keeps the keys
- **WHEN** a user runs `git clean -x -f -d` in a checkout
- **THEN** `~/.config/job-search-agent/.env` is unchanged

#### Scenario: Key directory is missing
- **WHEN** `~/.config/job-search-agent/` does not exist and the user starts the container
- **THEN** the container starts and `~/.config/job-search-agent/` exists, empty
- **AND** a command that reads an API key fails and names the key and
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
Setting up and using keys and user data SHALL require no `git update-index` or other command
that changes git's index flags. The README SHALL contain no such command.

#### Scenario: README setup
- **WHEN** a user follows the README from clone to a first run on personal data
- **THEN** no step runs `git update-index`

### Requirement: Branch operations do not conflict over personal data
Switching or merging branches SHALL NOT conflict over keys or user data, and SHALL leave
them unchanged.

#### Scenario: Switching branches after a run
- **WHEN** a user runs the pipeline on personal data and switches to another branch
- **THEN** the switch completes without error
- **AND** the keys and the files in `data/` are unchanged

#### Scenario: Merging after a run
- **WHEN** a user runs the pipeline on personal data and merges another branch
- **THEN** no conflict involves a file in `data/`
