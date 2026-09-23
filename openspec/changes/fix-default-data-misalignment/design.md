# Design

## Context

See proposal.md for the failure. The pipeline reads the preference file in two ways:

- **Parsed sections.** `config.home_address()` reads the first content line of
  `## Home Address`. `discovery._resolve_target_locations` reads `-` bullets under
  `## Location`, then the resume's `- Location:` line, then the home address.
  `rubric.compile_rubric` stores `## Scoring Notes` verbatim as `scoring_guidance`.
- **Whole-file prompts.** Query drafting, rubric drafting and reflection, pre-selection and
  evaluation send both files to the LLM in full. The query prompt names
  `Must-Haves`/`Nice-to-Haves`/`Disqualifiers` as the place to find remote openness.

`home_address()` output feeds OpenRouteService geocoding. A fictional address gives an
unknown commute on every job.

## Goals / Non-Goals

**Goals:**
- Both files run as-is and document the expected format by example.
- The persona produces enough postings on Indeed and LinkedIn that `propose_jobs.py 2`
  (6 pre-selected ads by default) returns results.

**Non-Goals:**
- Changing how any section is parsed.
- Moving personal data out of the repository (CSG-37).
- A live default-data CI job (CSG-18).

## Decisions

**Persona: mid/senior front-end engineer, TypeScript and React, based in Brussels.**
The role was chosen by the user. Brussels is the location assumption: it is a real,
geocodable metro area with English-language front-end postings on both boards, and the
discovery prompt's own example (`"Brussels, Belgium" -> "be"`) matches it. The persona
accepts hybrid roles in Brussels or Charleroi and fully remote roles, so discovery exercises
both location-bound and remote queries.

**Home address: a public commercial street address in central Brussels.**
`Rue des Halles 4, 1000 Bruxelles, Belgium`. It must geocode through OpenRouteService.

**`## Location` holds two bullets: `Brussels, Belgium` and `Charleroi, Belgium`.**
Two entries exercise multi-location query drafting and location validation while keeping
the query count within the prompt's 4-10 range. Brussels is first because
`primary_country` derives from the first entry.

**`## Scoring Notes` holds generic, format-demonstrating rules.**
Two or three rules phrased as judgments about a posting as a whole (for example, weighing
front-end ownership against back-end-heavy "full-stack" roles). This shows the section's
purpose: judgments a regex cannot express. It keeps the rubric's `SCORING_NOTES_GUARD`
behavior meaningful on default data.

**Resume uses a fictional name and `example.com` contact details.**
Employer names are fictional. Skills and history are concrete enough for rubric drafting
to produce traceable criteria.

**Offline test reads the active files through `jobsearch.config`.**
The test calls `config.home_address()`, `discovery._resolve_target_locations()` and
`config.extract_section(..., "Scoring Notes")`, and scans both files for placeholders.
It reads whatever `config.RESUME_PATH` and `config.JOB_PREFERENCES_PATH` point to, so it
also checks a personalized checkout. Alternative considered: reading the committed blobs
via `git show HEAD:`. Rejected because the container may not have git and the test would
then pass while the active files are broken. The placeholder check matches `(fill in` and
any bracketed text not followed by a link target, `\[[^\]\n]+\](?!\()`. This covers
lowercase placeholders such as `[your.email@example.com]`.

**Switching profiles deletes `data/evaluations.db`.**
Ranking and discovery do not filter saved evaluations by the rubric that scored them
(CSG-48), so sample-candidate rows would be ranked with personal ones and block their
re-evaluation. The README tells the user to delete the database after replacing the
profile. This is a manual workaround. CSG-48 or CSG-37's per-profile database replaces it.

**Live acceptance is a manual run, not an automated test.**
`propose_jobs.py 2` against live boards is slow, costs API calls and depends on current
postings. It is run once in the container during apply, with the output recorded in the
task. CSG-18 owns automating it.

## Risks / Trade-offs

- [Skip-worktree hides the new content in the main checkout] → Checkouts with the bit set
  keep local files. Only fresh clones and new worktrees see the sample. Acceptable: that is
  the target audience. No bit manipulation is needed in this worktree.
- [The live run in this worktree writes `data/evaluations.db`, `data/compatibility_rubric.json`
  and `data/search_queries.json`] → All three are gitignored and local to this worktree.
  They are deleted after verification so they do not leak into later runs.
- [Postings volume changes over time] → Brussels, Charleroi and remote give margin. If a run
  returns fewer than two jobs, widen the preferences rather than the code.
- [Charleroi roles score a long commute] → The drive from Rue des Halles is roughly 50-60
  minutes. At 3-5 office days that is below `COMMUTE_CUTOFF` (80) but costs about 10-15
  points, so Charleroi jobs rank below equivalent Brussels jobs. This is expected behavior
  and demonstrates the commute modifier.
- [The placeholder regex flags legitimate bracketed text] → The sample files avoid square
  brackets outside links.
