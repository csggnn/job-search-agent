# Proposal

## Why

An ad with no findable street address gets an unknown commute, and ranking treats it as
neutral. Recruiter ads, multi-site employers and companies with no public office address
fall into this group. In a 15-ad run, 7 non-remote ads had an unknown commute, including 3
of the top 5 proposed jobs. When the office web search returns only a city, the commute is
routed to that city and stored as if it were a street address, with no mark that it is
approximate.

## What Changes

- An ad that states no street address triggers a web search for the employer's office
  address.
- A street address found in the ad or by the office web search gives a precise commute.
- When only a city or town is known, the commute is computed to that city or town and the
  one-way drive time is increased by 10 minutes. The commute score is weighted by the
  required office days as for a precise commute.
- When the office web search returns only a city or town, that city or town is used, also
  when the ad names a different one.
- When the office web search finds nothing and the ad location field or the ad description
  names a city or town, the commute is computed to that city or town.
- When the ad description states that the role is based at a different place than the ad
  location field, that place is used.
- An approximate commute is marked as approximate in the saved evaluation, in the printed
  evaluation summary and in the proposed shortlist.
- When the office web search finds nothing and the ad location field and the ad
  description name no city or town, only a region, a country or no place at all, the
  commute stays unknown. Ranking treats an unknown commute as neutral, as it does today.
- Ranking applies no separate penalty. The 10 minutes are part of the saved commute score.
- Saved evaluations from before this change keep their scores and read as not approximate
  until re-evaluated.
- The documentation describes the city-level fallback and the 10-minute increase.

## Capabilities

### New Capabilities
- `commute-scoring`: choosing the job location from the ad and the office web search,
  classifying it as precise, approximate or unknown, and the commute score derived from it.

### Modified Capabilities

## Impact

- `jobsearch/commute.py`: address resolution and commute score.
- `jobsearch/storage.py`: saved evaluations carry the approximate mark.
- `jobsearch/evaluation.py`: evaluation summary text.
- `jobsearch/ranking.py`: shortlist output text.
- `evals/run_evals.py`: commute cases whose ground truth was set against an unknown or
  unmarked city-level commute may change result.
- `README.md`, `docs/architecture.md`.
- The read-only UI in `ui/` shows the commute score with no approximate mark.
- External systems: Tavily (address search) and OpenRouteService (geocoding, routing), both
  already used.
