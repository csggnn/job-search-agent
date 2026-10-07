# Proposal

## Why

Personal data currently lives in files committed as templates and hidden with the skip-worktree bit:
`.env`, `data/resume.md` and `data/job_preferences.md`.
This approach, which targets protecting personal data and making it easy for a new user to edit them, increases risks and complexity and needs to be revised:
- Real API keys sit in a tracked file. One `git update-index --no-skip-worktree` or `git add -A` in the wrong checkout commits them. This must be prevented.
- Each checkout holds its own copy of the API keys. A new checkout starts with none.
- `git status` reports the files as clean, but switching branches or merging aborts because personal data files differ.
- The skip-worktree mechanism itself is not a commonly used git feature. A developer requires additional context. This increases the complexity of the software project.
- Example candidate configuration and personal candidate configuration share one set of paths and one database. A developer needs to work on both. Alternating runs with these two configurations result in a job database with mixed jobs.
- There is no clear shared practice on how to test with the example and personal data without compromising the database and without the risk of losing or leaking personal data.

## What Changes

- All data related to a user (inputs, generated files, database, eval set) is grouped in one place, untracked by git, and copied or transferred as a unit.
- Example data is provided to help a user test the pipeline before writing their own data.
- A run never uses data other than the user's own without notice. A run that finds no user data stops and states what is missing.
- API keys cannot be committed.
- API keys have a single source of truth for every checkout.
- A new user is assisted in setting the API keys the pipeline reads.
- Personal data needs no git index manipulation. Switching or merging branches does not conflict over it.
- A developer can run the example data and personal data on one machine without mixing their evaluations, databases or eval sets.
- A documented practice describes how to work on example and personal data without mixing results and without losing or leaking personal data.

Deferred to later changes:
- A single step that creates a new user's data and sets up keys.
- Backup and restore commands.
- A configurable location for user data.
- Detecting and handling database entries evaluated against different user data.

## Capabilities

### New Capabilities
- data-directory: User data is grouped in one place and copied as a unit. A run on incomplete user data stops and states what is missing. Setup verification reports missing sections in the user's preferences. A documented practice covers working on example and personal data without mixing results and without losing or leaking personal data.
- personal-data-protection: API keys and user data are never tracked by git, need no git index manipulation, and cause no conflicts on branch operations.

### Modified Capabilities
- default-profile-data: example data is provided, a new user can run the pipeline on it, and the offline check verifies the committed example data whatever the user data holds. "Setup protects personal data in a fresh checkout" is removed.
