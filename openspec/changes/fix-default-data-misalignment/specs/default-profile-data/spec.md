# Spec Delta

## Purpose

The committed resume and job preferences describe a complete sample candidate, so a fresh
clone runs the full discovery, evaluation and ranking pipeline with only API keys configured.

## ADDED Requirements

### Requirement: Default data runs the pipeline on a fresh clone
The committed `data/resume.md` and `data/job_preferences.md` SHALL allow `propose_jobs.py`
to complete discovery, evaluation and ranking when the only local change is a filled-in
`.env`.

#### Scenario: Fresh clone proposes jobs
- **WHEN** a user clones the repository, fills in `.env` and runs `propose_jobs.py 2`
- **THEN** the run completes without raising
- **AND** both shortlists render with at least one proposed job
- **AND** at least one proposed job has a resolved commute rather than unknown

### Requirement: Default preferences fill every section the pipeline reads
The committed `data/job_preferences.md` SHALL contain `## Location`, `## Home Address` and
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

### Requirement: Default resume and preferences describe one consistent candidate
The committed resume and preferences SHALL describe the same fictional candidate. The
resume's `- Location:` contact line and the `## Home Address` SHALL name the same city, and
that city SHALL be the first `## Location` entry. The target roles in the preferences SHALL
match the skills and work history in the resume.

#### Scenario: Home city leads the target locations
- **WHEN** the resume contact location, the home address and the `## Location` entries are compared
- **THEN** the contact location and the home address name the same city
- **AND** that city is the first `## Location` entry

### Requirement: Default data contains no placeholder text
Neither committed file SHALL contain `(fill in` placeholders or bracketed `[...]`
placeholders.

#### Scenario: Placeholder scan
- **WHEN** both default files are scanned for `(fill in` and for bracketed placeholder tokens
- **THEN** no match is found

### Requirement: Offline check of the active data files
The unit test suite SHALL verify, without network access, that the active
`data/job_preferences.md` yields a home address, at least one target location and non-empty
scoring notes, and that neither active data file contains placeholder text. The test SHALL
contain no candidate-specific content.

#### Scenario: Required section removed
- **WHEN** `## Scoring Notes` is removed from the active preferences file and the unit suite runs
- **THEN** the default-data test fails and names the missing section
