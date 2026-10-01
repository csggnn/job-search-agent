# Proposal

## Why

Personal data currently lives in files committed as templates and hidden with the skip-worktree bit:
`.env`, `data/resume.md` and `data/job_preferences.md`.
This approach, which targets protecting personal data and making it easy for an new user to edit them, increases risks and complexity and needs to be revised:
- Real API keys sit in a tracked file. One `git update-index --no-skip-worktree` or `git add -A` in the wrong checkout commits them. This must be prevented.
- `git status` reports the files as clean, but switching branches or mergeing aborts because personal data files differ.
- The skip-worktree mechanism itself is not a commonly used git feature, a developer requires additional context, this increases the complexity of the software project.
- Sample candidate configuration and personal candidate configuration share one set of paths and one database. A developer needs to work on both. alternating runs with these two configurations results in a job database with mixed jobs.
- There is no clear shared practice on how to test with the default and personal profiles without compromising the database and without the risk of losing or leaking personal data

## What Changes

- The notion of `profile` is introduced. A `profile` collects all data related to a user: preferences, data, generated files and databases.
- At least two separate profiles, default and personal, exist. Runs use the personal profile of the workspace. A run on the default profile is requested explicitly in the command. Software runs on a profile can only affect that profile.
- `.env`, holding personal keys is stored in a location which is not prone to be accidentally shared. The software provides clear instructions on how to fill it up.
- Working with personal data requires no git index manipulation by the developer.
- Switching or merging branches after a personal profile job search run does not result in conflicts
- A user's personal information (keys, preferences, database) is never tracked in git. The README documents how to back up the personal profile to a target folder and restore it.
- A user can choose to run the pipeline on any profile, in a mode which does not change the real personal database or generated state.
- A user can reset the generated state of the default profile.
- Eval sets are treated as profile data. Separate eval sets exist for the default user and for the personal user.

## Capabilities

### New Capabilities
- profile-selection: Runs use the personal profile of the workspace. A run on the `default` profile is requested explicitly in the command, so a fresh clone runs the sample with no personal data. Without a personal profile and without that request, a run fails with an error that names both options. Clear instructions are provided on how to create the personal profile. The two profiles work on separate intermediate files and databases. Setup verification reports missing or malformed section in a profile before a run.
- personal-data-protection: API keys and personal profile data are never tracked by git, and no ordinary `git add` stages them. Working with personal data requires no git index manipulation. Switching or merging branches causes no conflicts from personal data.

### Modified Capabilities
- default-profile-data:
  - "Setup protects personal data in a fresh checkout" is removed. Protection is covered by personal-data-protection.
  - "Running the sample does not affect later personal runs" holds without deleting the sample's evaluations via profile-selection.
  - "Offline check of the active data files" checks the committed sample data, whichever profile is active. Checking personal profile files is part of setup verification, not the unit suite.
  - "Default data runs the pipeline on a fresh clone" is renamed "A fresh clone runs the pipeline on the sample data". It refers to the committed sample files independently of their location, which this change moves. The only local step is creating `.env` with API keys.
  - "Default preferences fill every section the pipeline reads" refers to the committed sample preferences independently of their location.

