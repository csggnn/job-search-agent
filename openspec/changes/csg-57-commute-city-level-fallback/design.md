# Design

## Context

See proposal.md (Why) for motivation and specs/commute-scoring/spec.md for the required
behavior.

Containers, stores and external systems involved, as named in
`docs/structurizr/workspace.dsl`:

- Job search engine: `jobsearch/commute.py` resolves the office and scores the commute,
  `jobsearch/evaluation.py` prints and summarizes it, `jobsearch/ranking.py` renders the
  shortlist.
- Evaluations DB: `engine -> db` "Reads and writes evaluations". The `evaluations` table
  stores `commute_address` and `commute_score`.
- Eval harness: calls `commute_score()` directly and compares `commute_score` and the
  address against ground truth.
- UI: `ui -> db` "Reads". It renders `commute_score` and `commute_address` and tolerates
  extra columns.
- External: Tavily (`engine -> tavily`, `evals -> tavily` "office-address search") and
  OpenRouteService (`engine -> ors`, `evals -> ors` "Geocoding, routing").

Terms: ad location field, ad description location, office search result, judged workplace
and job location are defined in specs/commute-scoring/spec.md. Discovery fills the ad
location field with the discovery query's place when the job board returns none
(`jobspy_search()` in `jobsearch/discovery.py`).

Current resolution in `commute.py`:

- `commute_score()` runs only for jobs that reach evaluation, after pre-selection. Each
  evaluated non-remote job already makes LLM calls in `figure_days_on_office()`, which
  reads the description, and in `classify_location()`, which reads only the ad location
  field.
- `figure_address()` classifies the ad location field with the LLM as remote, full address
  or generic. A generic ad location field goes to a Tavily search for company plus ad
  location field, and `resolve_office_address()` asks the LLM to pick the office address or
  return null.
- `commute_score()` returns `score: None` when `figure_address()` returns no address.
- `commute_route()` geocodes the home address and the destination through ORS
  `/geocode/search`. It reads only the coordinates of the first feature.
- `geocode_address()` retries once with an LLM-rewritten address, then raises `ValueError`.
  `commute_score()` does not catch it, so a failed geocode aborts the evaluation.
- The resolver LLM can return a bare city as the "address". It is routed and stored like a
  street address.

Constraints:

- Schema upgrades go through `storage._MIGRATIONS` and never drop rows.
- `combined_score` is never persisted.
- No `.py` file holds candidate-specific content.

## Goals / Non-Goals

**Goals:**
- Precision is classified from the place the route actually ends at, whichever step produced
  that place, so a city in the office search result and a city taken from the ad are
  classified the same way.
- Precision classification and the workplace judgment add no LLM call per evaluated job.
- The workplace judgment is unit-testable offline with a mocked LLM response.
- The precision rule is unit-testable offline, with no ORS or LLM call.

**Non-Goals:**
- Better street-address search. CSG-56 covers it.
- Recording precision in eval ground truth or eval run snapshots.

## Decisions

### D1. The ORS geocoder's `layer` decides precision

ORS geocoding is Pelias. Each feature carries `properties.layer`. `geocode_address()`
returns the layer with the coordinates, and a pure function maps the layer to a precision:

```
layer                                              precision
-------------------------------------------------  -----------
address, venue, street                             precise
postalcode, neighbourhood, borough, localadmin,    approximate
locality, county, macrocounty
region, macroregion, country, dependency,          unusable
unknown layer
```

Precision is read from the destination geocode, not from which resolution step ran. This
catches a city returned by the resolver.

Alternative rejected: ask the resolver LLM for a precision field. It costs prompt changes,
does not cover the fallback path, and leaves precision to the model's judgment.

Alternative rejected: mark approximate only when the fallback path runs. It misses the
resolver returning a city.

### D2. `classify_location()` judges the workplace from the ad

`classify_location()` receives the description in addition to the company and the ad
location field. The prompt presents the ad location field as the default workplace and
instructs the LLM to override it only when the description states that this role is based
at another place. A mention of another office, such as a headquarters, does not override
it. The JSON response holds `status` and `workplace`. `workplace` is the most precise place
the ad states for this role: a street address when the ad location field or the description
gives one, otherwise a city or town with its country when stated, or null. `status` takes
`remote` or `on_site`. The `full_address` and `generic` values are dropped, since the
geocoded layer of `workplace` decides whether it is street level (D1).

`search_office_address()` and `resolve_office_address()` receive the judged workplace in
place of the ad location field, and the ad location field when `workplace` is null.

Alternative rejected: two keys, a street address and a city. The same place at two levels
of detail made the order of sources ambiguous, and the LLM's street/city split would
duplicate the geocoder's layer.

Alternative rejected: keep the search on the ad location field. A search steered by the ad
location field finds that office, which then wins over an override at D3 step 1, so an
override would only take effect when the search finds nothing.

Alternative rejected: the ad location field always wins and the description only fills
gaps. It ignores ads whose description states a different workplace than the ad location
field.

Alternative rejected: a separate LLM call that reads the description only when the search
finds nothing. It adds a call and a prompt for a subset of jobs. `classify_location()`
already runs once per evaluated non-remote job, and the description costs only input
tokens there.

Alternative rejected: reuse `figure_days_on_office()`, which already reads the
description. Its response is a bare integer, and adding the workplace to it couples two
unrelated judgments.

### D3. Job location: precision first, then source

`figure_address()` geocodes each source once and returns the job location's coordinates,
label and precision, in the order of the spec's job location order requirement.
`commute_score()` routes to the returned coordinates:

```
classify_location() -> judged workplace
geocode judged workplace
   street level? ---------------------------------------> job location, precise. No search
office web search (steered by the judged workplace, or the ad location field if null)
geocode office search result
   street level or city level? -------------------------> job location
judged workplace city level? ---------------------------> job location, approximate
geocode ad location field, without "Metropolitan Area"
   city level? -----------------------------------------> job location, approximate
otherwise ----------------------------------------------> None
```

A geocode that raises `ValueError`, or returns an unusable layer, counts as no place for
that source. The office web search runs only when the judged workplace is not street level,
so a street address from the ad and one from the office search never compete. An office
search city precedes the judged workplace city. The ad location field is a separate source
only when the LLM returns no workplace; otherwise the judged workplace already reflects it.

Alternative rejected: one fixed list of candidates tried in order regardless of precision.
It cannot express that an office search street address beats the ad's city while the ad's
street address beats the office search.

`geocode_address()` keeps its single LLM rewrite retry. The rewrite can turn a street
address into a city-level match, and the layer then classifies it as approximate.

The home address geocode is unchanged and still raises on failure, since no commute can be
computed without it.

### D4. The 10 minutes are added to the one-way time before weighting

`commute.py` defines `APPROXIMATE_COMMUTE_EXTRA_MINUTES = 10`. The value appears in code
only in this definition. Docstrings and comments name the constant, the text passed to the
summary LLM interpolates it, and unit tests compute expected scores from it. For an
approximate
destination, `raw_minutes` is the routed time plus that constant, and the weighting by
office days applies to the sum. `distance_km` remains the routed distance. The returned
dict gains `"approximate": bool`. Remote and unknown results set it to `False`.

Alternative rejected: add the penalty in `ranking.combined_score()`. Displayed and ranked
values would differ, and ranking would need `days_on_office` to weight it.

### D5. Storage gains a nullable `commute_approximate` column

`_SCHEMA` and `_MIGRATIONS` add `commute_approximate INTEGER`. `save_evaluation()` writes
it on insert and on re-evaluation. `get_evaluation()` and `list_evaluations()` return it.
Rows saved before the migration hold `NULL`, which reads as not approximate. No value is
inferred for old rows.

The user-tracked fields are unaffected, since the upsert already preserves them.

### D6. Labels in the three outputs

- `evaluation._print_evaluation()`: "Commute score: 35.0 min, city-level (3 days/week,
  Ghent, Belgium)".
- `evaluation.summarize_evaluation()`: the commute context passed to the LLM states that the
  job location is city-level and the commute includes `APPROXIMATE_COMMUTE_EXTRA_MINUTES`
  extra minutes, interpolated from the constant.
- `ranking._proposal_line()`: "commute ~35 (weighted min, city-level)".
  `rank_evaluations()` is unchanged.

### D7. No relationship changes

The engine and the eval harness already call Tavily and ORS for these purposes. The engine
already reads and writes the evaluations DB. `docs/structurizr/workspace.dsl` is unchanged.

## Risks / Trade-offs

- [ORS layer names change, or a result has no `layer`] -> An unknown or missing layer maps
  to unusable, so the result is an unknown commute rather than a wrong precise one. Unit
  tests pin the mapping.
- [A county or postcode centroid is far from the office] -> Accepted. These layers are
  approximate and get the 10 minutes. The label shows the commute is approximate.
- [The ad location field geocodes to a same-named town in another country] -> Job boards
  normally include region or country in the ad location field. The stored
  `commute_address` shows which place was used.
- [The LLM overrides the ad location field wrongly, e.g. on a description listing all the
  employer's offices] -> The prompt keeps the ad location field unless the description
  states where this role is based. The stored `commute_address` shows which place was used.
  Unit tests cover only the wiring; the judgment itself needs eval cases where the ad
  location field and the ad description location differ.
- [The ad location field holds the discovery query's place, filled in when the job board
  returned none] -> It is the last candidate. A judged workplace or an office search result
  precedes it.
- [With the description in its input, `classify_location()` returns `remote` for a hybrid
  role] -> `figure_days_on_office()` runs first and decides remote by office days. The
  prompt keeps `remote` for no office attendance.
- [An office search street address lies in another city than the judged workplace, e.g.
  the ad says Ghent and the office search returns "Meir 1, Antwerp"] -> Accepted. Any
  street address is preferred to any city, so the job location is the Antwerp address,
  marked precise. The office web search is steered by the judged workplace, so it normally
  returns an office in that city. The stored `commute_address` shows which place was used.
- [An approximate commute pushed past the 80-minute cutoff zeroes a job] -> Accepted as a
  consequence of the 10-minute assumption.
- [Eval commute cases change result] -> Cases previously unresolved now produce a score.
  `address_contains` cases expecting a street still fail on a city. Ground truth is
  re-verified by hand where needed. Nothing under `evals/` changes.

## Migration Plan

The column is added on the first database open after deploy. Old rows read as not
approximate. Rollback: the old code ignores the extra column.
