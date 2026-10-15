# Spec Delta

## Purpose

Chooses the job location a commute is routed to from the places an ad and an office web
search provide, classifies it as precise, approximate or unknown, and derives the commute
score that ranking uses from it.

## ADDED Requirements

### Requirement: Job location sources
The system SHALL choose the job location, the place a commute is routed to, from these
sources:

- ad location field: the location field of the ad, as the job board or the ad page gives it.
- ad description location: a place the ad description states as this role's workplace.
- office search result: the office address or place returned by the web search for the
  employer's office.

The judged workplace SHALL be the most precise place the ad states for this role: a street
address when the ad gives one, otherwise a city or town. It SHALL be taken from the ad
location field, or from the ad description location when the description states that this
role is based at another place. A description that only mentions another office of the
employer, such as a headquarters, SHALL NOT override the ad location field.

#### Scenario: Description places the role elsewhere
- **WHEN** the ad location field is "Ghent, Belgium" and the description states that the
  role is based in the Antwerp office
- **THEN** the judged workplace is Antwerp

#### Scenario: Description mentions headquarters only
- **WHEN** the ad location field is "Ghent, Belgium" and the description states that the
  company is headquartered in Antwerp, with no statement about where the role is based
- **THEN** the judged workplace is Ghent

#### Scenario: Description street address for another office
- **WHEN** the ad location field is "Ghent, Belgium" and the description gives a street
  address in Antwerp as the headquarters address
- **THEN** the judged workplace is Ghent and the Antwerp address is not used

### Requirement: Job location order
The system SHALL prefer any street-level place to any city-level place. Within a level, the
system SHALL use the first usable place in this order:

- street level: the judged workplace, then the office search result
- city level: the office search result, then the judged workplace, then the ad location
  field

The ad location field SHALL be used only when no workplace is judged. A place that names
only a region or a country SHALL NOT be usable.

#### Scenario: Office search street address wins over the ad's city
- **WHEN** the judged workplace is "Ghent, Belgium" and the office search result is
  "Meir 1, Antwerp, Belgium"
- **THEN** the job location is the Antwerp street address and the commute is not marked
  approximate

#### Scenario: Office search city wins over the ad's city
- **WHEN** the ad location field is "Ghent, Belgium", the ad states no street address and
  the office search result is "Antwerp, Belgium"
- **THEN** the job location is Antwerp and the commute is marked approximate

#### Scenario: Ad street address wins with no search
- **WHEN** the ad location field is "Bahnhofstrasse 1, 8001 Zurich, Switzerland"
- **THEN** the job location is that address and no office web search runs

### Requirement: Office address is searched when the ad gives no street address
When the judged workplace is not a street address, the system SHALL search the
web for the employer's office address, using the judged workplace to pick the office. When
no workplace is judged, the search SHALL use the ad location field.

#### Scenario: Search follows the judged workplace
- **WHEN** the ad location field is "Ghent, Belgium" and the judged workplace is Antwerp
- **THEN** the system searches the web for the employer's office address in Antwerp

#### Scenario: Ad location field names a city only
- **WHEN** the ad location field of a non-remote ad is "Ghent, Belgium" and the description
  states no other workplace
- **THEN** the system searches the web for the employer's office address in Ghent

#### Scenario: Ad description holds a street address
- **WHEN** the ad location field is "Zurich, Switzerland" and the description states the
  office is at "Bahnhofstrasse 1, 8001 Zurich"
- **THEN** the job location is that address and no office web search runs

### Requirement: A street-level job location gives a precise commute
When the job location is a street address, the commute score SHALL be the one-way drive time
from the home address to it, weighted by the required office days per week: ×1.5 for 5
days, ×1 for 3 or 4 days, ×days/3 for 1 or 2 days. The commute SHALL NOT be marked
approximate.

#### Scenario: Street address in the office search result
- **WHEN** the office search result is a street address, the drive takes 30 minutes and the
  ad requires 3 office days per week
- **THEN** the commute score is 30 and the commute is not marked approximate

### Requirement: A city-level job location gives an approximate commute 10 minutes longer
When the job location is a city, town or comparable locality, the system SHALL route to it,
add 10 minutes to the one-way drive time, and weight the sum by the required office days per
week with the same factors as a precise commute. The commute SHALL be marked approximate.

#### Scenario: Office search finds nothing, ad location field names a city
- **WHEN** the office search result is empty, the ad location field names a city, the
  drive to that city takes 25 minutes and the ad requires 3 office days per week
- **THEN** the commute score is 35 and the commute is marked approximate

#### Scenario: Office search finds nothing, ad description location names a city
- **WHEN** the ad location field is "Belgium", the ad description location is Antwerp, and
  the office search result is empty
- **THEN** the job location is Antwerp, 10 minutes are added and the commute is marked
  approximate

#### Scenario: Weighting applies to the increased time
- **WHEN** the job location is a city, the drive to it takes 25 minutes and the ad requires
  5 office days per week
- **THEN** the commute score is 52.5 and the commute is marked approximate

#### Scenario: Office search result is a city
- **WHEN** the office search result gives "Puurs-Sint-Amands, Belgium" as the office address
- **THEN** the job location is Puurs-Sint-Amands, 10 minutes are added and the commute is
  marked approximate

### Requirement: No usable job location gives an unknown commute
When no source gives a usable place, the commute score SHALL be unknown. Ranking SHALL treat
an unknown commute as neutral, with compatibility passing through unchanged.

#### Scenario: Ad names only a country
- **WHEN** the office search result is empty, the ad location field is "Belgium" and the
  description states no city or town
- **THEN** the commute score is unknown and the commute is not marked approximate

#### Scenario: No source can be geocoded
- **WHEN** neither the office search result, the judged workplace nor the ad location field
  can be geocoded
- **THEN** the commute score is unknown and the evaluation completes

#### Scenario: Unknown commute in ranking
- **WHEN** a job with compatibility 70 has an unknown commute
- **THEN** its combined score is 70

### Requirement: Fully remote jobs have no commute
A job requiring 0 office days per week, or whose ad location field is classified as fully
remote, SHALL have a commute score of 0 and SHALL NOT be marked approximate.

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
