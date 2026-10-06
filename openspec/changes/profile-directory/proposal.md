# Proposal

## Why

Personal data currently lives in files committed as templates and hidden with the skip-worktree bit:
`.env`, `data/resume.md` and `data/job_preferences.md`.
This approach, which targets protecting personal data and making it easy for an new user to edit them, increases risks and complexity and needs to be revised:
- Real API keys sit in a tracked file. One `git update-index --no-skip-worktree` or `git add -A` in the wrong checkout commits them. This must be prevented.
- `git status` reports the files as clean, but switching branches or mergeing aborts because personal data files differ.
- The skip-worktree mechanism itself is not a commonly used git feature, a developer requires additional context, this increases the complexity of the software project.
- Sample candidate configuration and personal candidate configuration share one set of paths and one database. A developer needs to work on both. alternating runs with these two configurations results in a job database with mixed jobs.
- There is no clear shared practice on how to test with the sample and personal data without compromising the database and without the risk of losing or leaking personal data

## What Changes

- All data related to a user (inputs, generated files, database, eval set) is grouped in one place, untracked by git, and copied or transferred as a unit.
- The repository ships the example user's data as a template. A new user starts from it.
- A run without user data fails and states how to create it.
- API keys live outside every checkout and are configured from a committed template.
- Personal data needs no git index manipulation. Switching or merging branches does not conflict over it.
- The README describes how to work on the example data and on personal data in separate checkouts without mixing them.

Deferred to later changes:
- An init tool that creates user data from the template and sets up keys.
- Backup and restore commands.
- A configurable location for user data.
- Detecting and handling database entries evaluated against different user data.

## Capabilities

### New Capabilities
- data-directory: User data is grouped in one place per checkout. A run on incomplete user data fails with an error stating how to create it. Setup verification reports missing sections in the user's preferences. The README describes working on example and personal data in separate checkouts.
- personal-data-protection: API keys and user data are never tracked by git, need no git index manipulation, and cause no conflicts on branch operations.

### Modified Capabilities
- default-profile-data: the example data is a committed template, a fresh clone runs it after creating user data from it, and the offline check reads the template. "Setup protects personal data in a fresh checkout" is removed.
