# Tasks

## 1. Offline guard

- [x] 1.1 Add a `DefaultDataTest` class to `tests/unit/test_units.py` that reads the active files through `jobsearch.config` and asserts: `config.home_address()` returns a value, `discovery._resolve_target_locations()` returns the `## Location` bullets, `extract_section(..., "Scoring Notes")` is non-empty, and neither file matches `(fill in` or `\[[^\]\n]+\](?!\()` (bracketed text not followed by a link target). Each failure message names the section or file. Verify it fails against the current placeholder files: `podman-compose exec job-search python3 -m unittest discover -s tests/unit`

## 2. Sample candidate

- [x] 2.1 Rewrite `data/resume.md` as a fictional mid/senior front-end TypeScript/React engineer in Brussels: fictional name, `example.com` contact details, `- Location: Brussels, Belgium`, skills, languages, summary, two or three roles at fictional employers, education. Verify the placeholder scan finds nothing.
- [x] 2.2 Rewrite `data/job_preferences.md` to match: filled `Role & Seniority`, `Must-Haves` (hybrid in Brussels or Charleroi, or fully remote), `Disqualifiers`, `Nice-to-Haves`, `## Location` with `- Brussels, Belgium` then `- Charleroi, Belgium`, `## Home Address` with `Rue des Halles 4, 1000 Bruxelles, Belgium`, `## Scoring Notes` with two or three whole-posting judgment rules, and `Compensation & Logistics`. Verify task 1.1's test passes and that `_resolve_target_locations()` returns both entries in that order.
- [x] 2.3 Confirm the home address geocodes through OpenRouteService from inside the container (a one-off call to the geocoder `jobsearch.commute` uses). Verify it returns a coordinate in Brussels.

## 3. Docs

- [x] 3.1 Update `README.md` "Default usage" and setup step 2 to state the files ship as a runnable sample candidate to replace with your own. Verify no "template"/"example is provided" wording contradicts it.
- [x] 3.2 Update `docs/architecture.md`: the `data/resume.md` and `data/job_preferences.md` rows in the file table, the "Personalization files stay out of git" section wording, and note `## Location` alongside `## Scoring Notes` and `## Home Address`. Verify with `grep -n "template" docs/architecture.md README.md`.
- [x] 3.3 Update `CLAUDE.md` "Git-invisible files" if its "generic templates" wording no longer holds. Verify by reading the section.

## 4. Live acceptance

- [x] 4.1 Run `podman-compose exec job-search python3 propose_jobs.py 2` in this worktree. Verify it completes, both shortlists render, and at least one job has a resolved commute. Record the output summary here.
  - Run on 2026-09-23 with the main checkout's `.env` in a one-off container: exit 0. Discovery dropped 15 stale, 3 duplicate and 52 not-selected ads, then evaluated 6. Both shortlists rendered 2 jobs each. Top job: Senior Front-End Engineer at Vivid Resourcing, fit 82, commute 15 weighted min (resolved). 3 of 6 commutes were unknown because the office address was not found. Evaluations cited the Scoring Notes consultancy and full-stack rules.
- [x] 4.2 Delete the generated `data/evaluations.db`, `data/compatibility_rubric.json` and `data/search_queries.json` from this worktree. Verify `git status --short --ignored data/` lists none of them.
- [x] 4.3 Run the full offline suite: `podman-compose exec job-search python3 -m unittest discover -s tests/unit`. Verify all tests pass.
