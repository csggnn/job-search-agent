# Tests and evals

Two test tiers plus an eval harness. They answer different questions: the tests ask "does
it run?", the evals ask "did this change make the judgments better?".

## Tests

`tests/unit/` and `tests/e2e/` are separate subdirectories so the offline suite runs
without credentials.

- **`tests/unit/`** offline unit tests for the deterministic helpers (URL normalization,
  rubric hashing and application, section extraction, query validation, JSON parsing) and
  for pre-selection, whose one LLM call is patched out. No LLM, network or `.env` required.
- **`tests/e2e/`** a live end-to-end smoke test that drives the pipeline through the CLI
  entrypoint and inspects the saved SQLite row. Requires API keys. Set `TARGET_URL` near
  the top of `tests/e2e/test_e2e_pipeline.py` to a currently-live posting.

```
podman-compose exec job-search python3 -m unittest discover -s tests/unit   # offline
podman-compose exec job-search python3 -m unittest discover -s tests/e2e    # needs keys
```

`.github/workflows/unit-tests.yml` runs the unit suite on every pull request. It builds the
image from the `Dockerfile` and runs `unittest discover -s tests/unit` inside it, mounting
the checkout at `/workspace` as `podman-compose` does. The e2e suite is not run in CI: it
needs API keys and a live posting.

## The eval set

A hand-curated set of 5-10 cases, deliberately not the whole database. The database records
real usage and grows on its own. An eval set only means anything if it is small enough to
hold ground truth a human has actually checked.

**The database is for usage; `evals/` is for eval.** Eval code may import only the pure
helpers from `jobsearch.storage` (`normalize_url`, `rubric_content_hash`), never `get_*`,
`save_*` or `list_*`, which open the database. Nothing under `evals/` reads or writes
`data/evaluations.db`, and the eval set is never populated by sweeping it.

### Case shape

`evals/cases.json`, each case: `{name, url, ad, verified, notes, expected: {...}}`.

`ad` names a file in `evals/ads/` and is what the case replays against. The `url` is
provenance, not an input, so a posting being taken down cannot break a case. `ad: null`
means capture failed; the case is kept, reported and skipped. The ad is recorded explicitly
rather than derived from `name`, so renaming a case cannot orphan its inputs.

`expected` keys are independent and optional. Only the ones present are checked:

| Key | Type |
|-----|------|
| `compatibility_score` | int 0-100 |
| `days_on_office` | int, exact match |
| `commute_score` | weighted minutes |
| `address_contains` | a short distinctive substring, or the `FULLY_REMOTE` sentinel, compared by equality |
| `criteria` | exact criterion name to bool |

**Ground truth is one value per step, never a `[lo, hi]` range.** A range is passed by two
runs that are nowhere near each other, which hides the change an eval exists to detect. The
accepted margin belongs to the harness (`--tolerance-*`), not the case.
`dataset.py`'s `EXPECTED_TYPES` and `validate_expected` enforce this: a leftover range is
rejected with the command to re-draft rather than silently scored.

**`criteria` uses exact names, and unknown names are never scored.** Each label sorts into
correct, wrong, `stale_label` (a name the rubric no longer has), or `unlabeled` (a rubric
name with no label). Only correct and wrong reach accuracy. A rubric rename therefore
surfaces as reported work rather than a silent pass or fail.

The predecessor shape, `criteria_matched_contains` and `criteria_unmatched_contains`,
asserted the absence of a substring, so a renamed criterion passed vacuously. The current
shape exists to make that impossible.

## Workflow

Capture, draft, verify, run:

```
python evals/capture.py <url>      # save the posting as an ad; do this early, postings expire
python evals/draft.py --all        # pre-fill ground truth from what the pipeline says today
                                   # then hand-edit cases.json and set "verified": true
python evals/run_evals.py --verified-only --compare
```

Drafting is a starting point, never an answer. It records what the current pipeline
produced, which is the thing under test, so trusting it would be circular. Every drafted
case is written `"verified": false`, and only a human review makes it ground truth.
`--verified-only` filters to the reviewed set.

`evals/capture.py --list-cases` reviews the eval set before picking cases.
`evals/capture.py --re-extract --all` rebuilds extracted fields from saved text.

## Metrics

Results are reported two ways, because pass-rates alone cannot show progress: two runs can
both sit inside a tolerance band while one is much closer.

| Step | Continuous metric | Pass criterion |
|------|-------------------|----------------|
| `compatibility_score` | mean absolute error | `--tolerance-score`, default 10 on a 0-100 judgment |
| `commute_score` | mean absolute error | `--tolerance-commute`, default 5 weighted minutes |
| `days_on_office` | exact match | exact |
| `criteria` | accuracy, precision, recall | per-label |

Tolerances are harness policy, not per-case data. `--tolerance-commute` is deliberately
tight because the commute accept/reject boundary is only a few minutes wide.

Each run is snapshotted to `evals/runs/` with the rubric hash and both model ids, so
`--compare` can attribute a change afterwards.

## Cost tiers

A case replays against its saved posting text rather than re-scraping, so `run_evals.py`
picks a tier by what it needs to check. It batches per case: at most one `commute_score()`
call and one `compatibility_score()` call, with the criteria pass being free regex over the
stored ad.

| Tier | Cost per case | What it checks |
|------|---------------|----------------|
| `--criteria-only` | free, no network | the rubric's regexes against saved text |
| `--no-commute` | 2 LLM calls | plus `days_on_office` and the compatibility judgment |
| (default) | 2 LLM calls + live address search + routing | plus the office address and commute score |

`--criteria-only` runs the whole eval set in well under a second, which makes it usable as
a regression check on every rubric edit.

`evals/capture.py --re-extract` rebuilds a stored ad's extracted fields from its saved page
text for one LLM call and no Tavily call. That is what makes the extraction prompt iterable
after a posting is taken down.

## Harness modules

| File | Role |
|------|------|
| `evals/dataset.py` | `cases.json` and stored-ad I/O; ground-truth shape checks |
| `evals/scoring.py` | pure scoring: criteria labels, scalars, aggregation, run diffs |
| `evals/capture.py` | posting URL to replayable ad (raw page text plus extracted post) |
| `evals/draft.py` | stored ad to pre-filled ground truth for a human to correct |
| `evals/run_evals.py` | replay the eval set, score it, snapshot the run, compare runs |

Stored ads hold verbatim scraped job-ad text. That content is data under `evals/` and is
never inlined into a `.py` file.
