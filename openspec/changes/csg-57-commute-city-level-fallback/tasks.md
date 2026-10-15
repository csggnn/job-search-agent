# Tasks

## 1. Commute resolution and score

- [ ] 1.1 In `jobsearch/commute.py`, make `geocode_address()` return the first feature's `properties.layer` with its coordinates, and update `commute_route()` to accept geocoded destination coordinates. Verify with a unit test in a new `tests/unit/test_commute.py` that mocks the ORS response and asserts the returned coordinates and layer.
- [ ] 1.2 Add a pure function in `jobsearch/commute.py` mapping an ORS layer to `precise`, `approximate` or `unusable` per design D1, with unknown and missing layers mapped to `unusable`. Verify with unit tests covering each layer group and an unknown layer.
- [ ] 1.3 Extend `classify_location()` per design D2: it receives the description, the prompt presents the location text as the default workplace and allows an override only when the description states this role is based elsewhere, a street address stated for the workplace counts as `full_address`, and the response has a `workplace` key. Make `figure_address()` pass the judged workplace to the search and the resolver, fall back to the location text when it is null, and return the workplace with the resolved address. Pass the description from `commute_score()`. Verify with unit tests that mock `ask_json` and Tavily: the description and the location reach the prompt, the search query uses the mocked workplace (Antwerp for location Ghent), the search uses the location text when the workplace is null, and `figure_address()` returns the workplace when the search resolves no address.
- [ ] 1.4 Add `APPROXIMATE_COMMUTE_EXTRA_MINUTES = 10` and restructure `commute_score()` per design D3 and D4: ordered destination candidates (resolved address, then the judged workplace, then location text without "Metropolitan Area"), skip candidates that raise `ValueError` or map to `unusable`, add the extra minutes to `raw_minutes` before weighting for an approximate destination, and return `"approximate"` in every result. Verify with mocked unit tests for each spec scenario: street address found, search finds nothing and the ad names a city (25 min, 3 days -> 35), location "Belgium" with the judged workplace Antwerp used before the location text, 5-day weighting (25 min -> 52.5), resolver returns a city, location names only a country (score `None`), geocode failure on every candidate (score `None`, no exception), and remote (score 0, not approximate).
- [ ] 1.5 Update the `classify_location()`, `figure_address()` and `commute_score()` docstrings to state the description input, the workplace override rule, the candidate order, the precision rule and the 10-minute increase. Verify by reading them against design D1 to D4.

## 2. Storage

- [ ] 2.1 Add `commute_approximate INTEGER` to `_SCHEMA` and to `_MIGRATIONS` in `jobsearch/storage.py`, write it in both branches of `save_evaluation()`, and return it from `get_evaluation()` and `list_evaluations()`. Verify with a unit test against a temporary database: a database created without the column migrates, its existing row loads with its commute score unchanged and reads as not approximate, and a re-saved approximate evaluation reads back as approximate with user-tracked fields preserved.

## 3. Outputs

- [ ] 3.1 In `jobsearch/evaluation.py`, label an approximate commute as city-level in `_print_evaluation()` and in the commute context of `summarize_evaluation()`, per design D6. Verify with a unit test that captures `_print_evaluation()` output for an approximate row and for a pre-migration row.
- [ ] 3.2 In `jobsearch/ranking.py`, make `_proposal_line()` render an approximate commute as `commute ~<score> (weighted min, city-level)`, leaving `combined_score()` and `rank_evaluations()` unchanged. Verify with tests in `tests/unit/test_ranking.py`: the approximate shortlist line, and equal combined scores for a precise and an approximate job with the same commute score.

## 4. Documentation

- [ ] 4.1 Update `docs/architecture.md`: the `commute_score` step of the `evaluate_job` diagram describes the candidate order, the city-level fallback and the 10-minute increase, and the Ranking section states that an approximate commute is ranked by its saved score with no separate penalty. Verify by reading the sections against the spec.
- [ ] 4.2 Update `README.md`: the evaluation output example and the shortlist example include a city-level commute, and the ranking description mentions the 10-minute increase. Verify by reading the sections against the spec.
- [ ] 4.3 Check `docs/evals.md` for statements about unresolved commutes and update any that the fallback makes inaccurate. Verify by reading the commute metric descriptions.

## 5. Checks

- [ ] 5.1 Run `podman-compose exec job-search python3 -m unittest discover -s tests/unit`, `scripts/ruff.sh check .` and `scripts/ruff.sh format --check .`. Verify all pass.
- [ ] 5.2 Run `podman-compose exec job-search python3 evaluate_job_post.py <url> --force` on an ad with no findable street address, e.g. a recruiter ad. Verify the printed commute is labelled city-level and `sqlite3 data/evaluations.db` shows `commute_approximate = 1` for that row.
