# default-profile-data Delta

## RENAMED Requirements

- FROM: `### Requirement: Default data runs the pipeline on a fresh clone`
- TO: `### Requirement: A fresh clone runs the pipeline on the example data`
- FROM: `### Requirement: Offline check of the active data files`
- TO: `### Requirement: Offline check of the template data`

## MODIFIED Requirements

### Requirement: A fresh clone runs the pipeline on the example data
On a fresh clone, after `data/` is created from the template, `propose_jobs.py` SHALL
complete discovery, evaluation and ranking when the only other local setup is
`~/.config/job-search-agent/.env` holding API keys.

#### Scenario: Fresh clone proposes jobs
- **WHEN** a user clones the repository, creates `~/.config/job-search-agent/.env` with API
  keys, creates `data/` from the template with the README command and runs
  `propose_jobs.py 2`
- **THEN** the run completes without raising
- **AND** both shortlists render with at least one proposed job
- **AND** at least one proposed job has a resolved commute rather than unknown

### Requirement: Default preferences fill every section the pipeline reads
The template job preferences SHALL contain `## Location`, `## Home Address` and
`## Scoring Notes` sections, each holding a non-placeholder value.

#### Scenario: Home address resolves
- **WHEN** the home address is read from the template preferences
- **THEN** it returns a single street address line
- **AND** that address geocodes to a real location

#### Scenario: Target locations come from the Location section
- **WHEN** discovery resolves target search locations from the template data
- **THEN** it returns the entries listed under `## Location`
- **AND** it does not fall back to the resume contact line or the home address

#### Scenario: Scoring guidance is present
- **WHEN** the rubric is compiled from the template data
- **THEN** its scoring guidance is the non-empty text of `## Scoring Notes`

### Requirement: Offline check of the template data
The unit test suite SHALL verify, without network access, that the template job preferences
yield a home address, target locations equal to the `## Location` entries in the same
order, and non-empty scoring notes, and that neither template file contains placeholder
text. The check SHALL read the template files whether or not `data/` exists, and SHALL
NOT read `data/`. The test SHALL contain no candidate-specific content.

#### Scenario: Required section removed
- **WHEN** `## Scoring Notes` is removed from the template preferences file and the unit suite runs
- **THEN** the default-data test fails and names the missing section

#### Scenario: Resolved locations differ from the Location entries
- **WHEN** the resolved target locations are empty, omit an entry, or list the entries in a different order
- **THEN** the default-data test fails

#### Scenario: User data does not affect the check
- **WHEN** the job preferences in `data/` lack `## Scoring Notes` and the unit suite runs
- **THEN** the default-data test passes

#### Scenario: Checkout without user data
- **WHEN** `data/` does not exist and the unit suite runs
- **THEN** the default-data test passes

### Requirement: Running the sample does not affect later personal runs
The README setup SHALL run the example user before the user adds personal data. The README
step that adds personal data SHALL leave no evaluation of the example user in the database
that personal runs use.

#### Scenario: Switching from the sample to a personal profile
- **WHEN** a user runs `propose_jobs.py` on the example data, follows the README step that
  adds a personal resume and job preferences, and runs `propose_jobs.py` again
- **THEN** no job evaluated for the example user appears in either shortlist
- **AND** a posting evaluated for the example user is evaluated again if discovery finds it

## REMOVED Requirements

### Requirement: Setup protects personal data in a fresh checkout
**Reason**: Keys live outside every checkout and user data is ignored by git, so no git index setup exists to protect them.
**Migration**: Protection is specified by the `personal-data-protection` capability.
