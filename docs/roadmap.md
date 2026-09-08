# Roadmap

Known limitations that require code changes, not documentation or configuration.

Tracked in Linear (team Csggnn), mirrored to GitHub. Issue ids are added below as each is
filed.

## 1. Finer-grained evaluation cache

`evaluate_job(url, force=True)` re-scrapes, re-computes commute, and re-judges
compatibility together. Splitting the cache into independent layers, scrape freshness,
rubric freshness (already tracked via `rubric_content_hash`), and home-address/commute
freshness, would let a single-dimension change such as a new home address refresh only
what it invalidates.

This needs a place to keep the description first. `save_evaluation()` currently drops
`job["description"]` and no column stores it, which is why a re-evaluation must always
re-scrape. `evals/ads/` solves this for the eval set only; its capture path
(`scrape.fetch_page_text` plus `extract_post`) is the seam a storage-side version would
reuse.

Sequence: add description storage first, then layer the cache on top of it.

## 2. No CLI for browsing and updating results

Filtering saved evaluations and updating `reviewed`, `application_status` and `notes`
(`storage.update_review`) are reachable only via raw `sqlite3` or a Python REPL. A small
`query.py` or `review.py` wrapper would remove the need to hand-write SQL for routine use.

This is the near-term CLI-shaped slice of two existing product-level items:
[CSG-9](https://linear.app/csggnn/issue/CSG-9) (a front end to trigger job selections and
browse the database) and [CSG-7](https://linear.app/csggnn/issue/CSG-7) (tracking
applications and the reason for not applying).

## 3. Pre-selection is not measured

Pre-selection is a selector, so a single run says nothing about it. The questions are:

- **precision@N**: of the job ads it kept, what fraction score above a threshold once fully
  evaluated;
- **recall**: whether a good job was dropped, which needs one batch where every discovered
  ad was evaluated.

Both need a fixture holding a captured job ad list as discovery returns it. The existing
`evals/ads/` files are single postings and cannot exercise a stage whose input is a list.

## 4. Ground truth is reviewed by hand-editing JSON

`evals/draft.py` pre-fills a case and the human corrects it in `evals/cases.json`. At the
current size, 5-10 cases, this is workable. A guided review loop that walks unverified
cases one at a time, showing the posting alongside what the pipeline claimed and prompting
accept/flip/skip, would make it faster and harder to typo if the eval set grows.

Not committed: this is conditional on the eval set growing.
