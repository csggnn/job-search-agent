# default-profile-data Delta

## MODIFIED Requirements

### Requirement: A fresh clone runs the pipeline on the sample data
On a fresh clone, `propose_jobs.py` SHALL complete discovery, evaluation and ranking on the
committed sample resume and job preferences when the only local setup is
`~/.config/job-search-agent/.env` holding API keys.

#### Scenario: Fresh clone proposes jobs
- **WHEN** a user clones the repository, creates `~/.config/job-search-agent/.env` with API
  keys and runs `propose_jobs.py 2`
- **THEN** the run completes without raising
- **AND** both shortlists render with at least one proposed job
- **AND** at least one proposed job has a resolved commute rather than unknown

### Requirement: Default preferences fill every section the pipeline reads
The committed sample job preferences SHALL contain `## Location`, `## Home Address` and
`## Scoring Notes` sections, each holding a non-placeholder value.

#### Scenario: Home address resolves
- **WHEN** the home address is read from the default preferences
- **THEN** it returns a single street address line
- **AND** that address geocodes to a real location

#### Scenario: Target locations come from the Location section
- **WHEN** discovery resolves target search locations from the default data
- **THEN** it returns the entries listed under `## Location`
- **AND** it does not fall back to the resume contact line or the home address

#### Scenario: Scoring guidance is present
- **WHEN** the rubric is compiled from the default data
- **THEN** its scoring guidance is the non-empty text of `## Scoring Notes`

### Requirement: Offline check of the committed sample data
The unit test suite SHALL verify, without network access, that the committed sample job
preferences yield a home address, target locations equal to the `## Location` entries in
the same order, and non-empty scoring notes, and that neither committed sample file contains
placeholder text. The check SHALL read the sample files whichever profile is active. The
test SHALL contain no candidate-specific content.

#### Scenario: Required section removed
- **WHEN** `## Scoring Notes` is removed from the sample preferences file and the unit suite runs
- **THEN** the default-data test fails and names the missing section

#### Scenario: Resolved locations differ from the Location entries
- **WHEN** the resolved target locations are empty, omit an entry, or list the entries in a different order
- **THEN** the default-data test fails

#### Scenario: Personal profile does not affect the check
- **WHEN** the personal profile is active, its preferences lack `## Scoring Notes`, and the unit suite runs
- **THEN** the default-data test passes

### Requirement: Running the sample does not affect later personal runs
The README setup SHALL run the sample candidate before the user adds a personal profile.
Adding the personal profile SHALL require no cleanup of the sample candidate's evaluations.

#### Scenario: Switching from the sample to a personal profile
- **WHEN** a user runs `propose_jobs.py` on the sample candidate, adds a personal resume
  and job preferences, and runs `propose_jobs.py` again
- **THEN** no job evaluated for the sample candidate appears in either shortlist
- **AND** a posting evaluated for the sample candidate is evaluated again if discovery
  finds it

## REMOVED Requirements

### Requirement: Setup protects personal data in a fresh checkout
**Reason**: Personal data and keys are untracked, so no git index setup exists to protect them.
**Migration**: Protection is specified by the `personal-data-protection` capability.

## RENAMED Requirements

- FROM: `### Requirement: Offline check of the active data files`
- TO: `### Requirement: Offline check of the committed sample data`
- FROM: `### Requirement: Default data runs the pipeline on a fresh clone`
- TO: `### Requirement: A fresh clone runs the pipeline on the sample data`
