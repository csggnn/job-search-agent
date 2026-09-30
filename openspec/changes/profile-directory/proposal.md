# Proposal

## Why

Personal data lives in files committed as templates and hidden with the skip-worktree bit:
`.env`, `data/resume.md` and `data/job_preferences.md`. Tracked as CSG-37.
This approach, which targets protecting personal data, increases risks and complexity and needs to be revised:
- Real API keys sit in a tracked file. One `git update-index --no-skip-worktree`, fresh
  clone or `git add -A` in the wrong checkout commits them. This must be prevented.
- `git status` reports the files as clean while a merge aborts because personal data files differ.
- The skip-worktree mechanism itself is not a commonly used git feature, a developer requires additional context, this increases the complexity of the software project.
- Sample candidate configuration and personal candidate configuration share one set of paths and one database. A developer needs to work on both. Job search runs with these two configurations will result in an incoherent job search database. This issue has been met also in (CSG-48).
- There is no clear shared practice on how to test with sample and personal profile without compromising the database and without the risk of losing or leaking personal data

## What Changes

- At least two separate Sample and Personal profiles exist. Switching profile is one single action, simple, clear and well documented. Software runs on a profile can only affect that profile (the database, all intermediate files such as `compatibility_rubric.json`)
- `.env`, holding personal keys is untracked and gitignored. An example file and clear instructions can be provided to fill it up, but the configuration must be such that a user can not accidentally share API keys.
- Working with personal data requires no git index manipulation by the developer.
- Switching or merging branches after a personal profile job search run does not result in conflicts
- A user's personal information (keys, preferences, database) is never tracked in git, but instrumentation is provided for the user to back up this personal data to a target folder and restore it.
- A developer can choose to run the pipeline on personal data without changing the real personal database or generated state.
- A developer can work on several branches at once, in the main checkout or in git worktrees.
- Eval sets are treated as profile data. Separate eval sets exist for the default user and for the personal user, personal user eval data is not tracked on git.

## Capabilities

### New Capabilities
- profile-selection: a user can choose whether to run on the default or on the personal profile, the two profiles work on separate intermediate files and databases. A worktree runs on the sample profile unless personal profile data is copied into it. A worktree with copied personal data is one way in which a developer runs on personal data without changing the real data. The documentation describes this workflow and states that changes to a worktree's data do not reach the main checkout. Setup verification reports a personal profile with a missing or malformed section before a run. The README gives the full path of each profile file and `.env` at its first mention, linked to the file, to `.env.example` for `.env`, or to the README section on the personal profile for a personal file.
- personal-profile-backup: personal data can be backed up to and restored from a target folder 
- personal-data-protection: API keys and personal profile data are never tracked by git, and no ordinary `git add` stages them. Working with personal data requires no git index manipulation. Switching or merging branches causes no conflicts from personal data.

### Modified Capabilities
- default-profile-data:
  - "Setup protects personal data in a fresh checkout" is removed. Protection is covered by personal-data-protection.
  - "Running the sample does not affect later personal runs" holds without deleting the sample's evaluations via profile-selection.
  - "Offline check of the active data files" checks the committed sample data, whichever profile is active. Checking personal profile files is part of setup verification, not the unit suite.
  - "Default data runs the pipeline on a fresh clone" is renamed "A fresh clone runs the pipeline on the sample data". It refers to the committed sample files independently of their location, which this change moves. The only local step is creating `.env` with API keys.
  - "Default preferences fill every section the pipeline reads" refers to the committed sample preferences independently of their location.

