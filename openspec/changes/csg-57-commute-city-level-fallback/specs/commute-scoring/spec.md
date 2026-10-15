# Spec Delta

## Purpose

Resolves where a job's office is, classifies that place as precise, approximate or unknown,
and derives the commute score that ranking uses from it.

## ADDED Requirements

### Requirement: Office location is searched when the ad gives no street address
When neither a non-remote job's location text nor its description holds a street address,
the system SHALL search the web for the employer's office address, using the location text
to pick the office. A street address in the location text or the description SHALL be used
without a search.

#### Scenario: Location names a city only
- **WHEN** a non-remote ad's location is "Ghent, Belgium" with no street address
- **THEN** the system searches the web for the employer's office address in Ghent

#### Scenario: Location holds a street address
- **WHEN** a non-remote ad's location is "Bahnhofstrasse 1, 8001 Zurich, Switzerland"
- **THEN** the system uses that address with no web search

#### Scenario: Description holds a street address
- **WHEN** a non-remote ad's location is "Zurich, Switzerland" and its description states
  the office is at "Bahnhofstrasse 1, 8001 Zurich"
- **THEN** the system uses that address with no web search

### Requirement: A street-level place gives a precise commute
When the resolved place is a street address, the commute score SHALL be the one-way drive
time from the home address to that place, weighted by the required office days per week:
×1.5 for 5 days, ×1 for 3 or 4 days, ×days/3 for 1 or 2 days. The commute SHALL NOT be
marked approximate.

#### Scenario: Street address found by the search
- **WHEN** the search finds a street address, the drive takes 30 minutes and the ad
  requires 3 office days per week
- **THEN** the commute score is 30 and the commute is not marked approximate

### Requirement: A city-level place gives an approximate commute 10 minutes longer
When no street address is found and a city, town or comparable locality is known, from the
search result or from the ad's location or description, the system SHALL route to that place, add 10
minutes to the one-way drive time, and weight the sum by the required office days per week
with the same factors as a precise commute. The commute SHALL be marked approximate. A place
returned by the search that is a city rather than a street address SHALL be treated as
approximate.

#### Scenario: Search finds nothing, ad names a city
- **WHEN** the search finds no office address, the ad's location names a city, the drive
  to that city takes 25 minutes and the ad requires 3 office days per week
- **THEN** the commute score is 35 and the commute is marked approximate

#### Scenario: Search finds nothing, description names a city
- **WHEN** the ad's location is "Belgium", its description names an office in Antwerp, and
  the search finds no office address
- **THEN** the commute is computed to Antwerp with 10 minutes added and is marked
  approximate

#### Scenario: Weighting applies to the increased time
- **WHEN** the commute is city-level, the drive to the city takes 25 minutes and the ad
  requires 5 office days per week
- **THEN** the commute score is 52.5 and the commute is marked approximate

#### Scenario: Search returns a city as the address
- **WHEN** the search result gives "Puurs-Sint-Amands, Belgium" as the office address
- **THEN** the commute is computed to Puurs-Sint-Amands with 10 minutes added and is marked
  approximate

### Requirement: No usable location gives an unknown commute
When no street address and no city-level place is known, the commute score SHALL be unknown.
A location that names only a region or a country SHALL count as no usable location. Ranking
SHALL treat an unknown commute as neutral, with compatibility passing through unchanged.

#### Scenario: Ad names only a country
- **WHEN** the search finds no office address, the ad's location is "Belgium" and its
  description names no city or town
- **THEN** the commute score is unknown and the commute is not marked approximate

#### Scenario: Location cannot be geocoded
- **WHEN** neither the search result nor the ad's location text can be geocoded
- **THEN** the commute score is unknown and the evaluation completes

#### Scenario: Unknown commute in ranking
- **WHEN** a job with compatibility 70 has an unknown commute
- **THEN** its combined score is 70

### Requirement: Fully remote jobs have no commute
A job requiring 0 office days per week, or whose location is classified as fully remote,
SHALL have a commute score of 0 and SHALL NOT be marked approximate.

#### Scenario: Remote job
- **WHEN** an ad states the role is fully remote
- **THEN** the commute score is 0 and the commute is not marked approximate

### Requirement: Approximate commutes are labelled
The saved evaluation SHALL record whether its commute is approximate. The printed
evaluation summary and each proposed job in the shortlist output SHALL label an approximate
commute as city-level. An evaluation saved before the approximate mark existed SHALL read as
not approximate.

#### Scenario: Shortlist shows an approximate commute
- **WHEN** a proposed job has an approximate commute score of 42
- **THEN** its shortlist entry shows the commute as approximate and city-level, e.g.
  "commute ~42 (weighted min, city-level)"

#### Scenario: Printed evaluation of an approximate commute
- **WHEN** an evaluation with an approximate commute to Ghent is printed
- **THEN** the commute line states that the commute is city-level

#### Scenario: Evaluation saved before the mark existed
- **WHEN** the database holds an evaluation saved before the approximate mark existed
- **THEN** the evaluation loads, keeps its commute score and reads as not approximate

### Requirement: Ranking applies no separate approximate penalty
The combined score of a job with an approximate commute SHALL be computed from its saved
commute score with the same formula as a precise commute.

#### Scenario: Equal scores, different precision
- **WHEN** two jobs have compatibility 70 and commute score 35, one precise and one
  approximate
- **THEN** both have the same combined score
