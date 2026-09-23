# Proposal

## Why

The committed `data/resume.md` and `data/job_preferences.md` hold only placeholder text, and
they have drifted from the sections the code reads. On a fresh clone with only `.env`
filled in, `propose_jobs.py` raises before any search runs. Tracked as CSG-17, detailed in
CSG-38.

Observed against the committed files:

- `## Home Address` holds `(fill in: ...)`. `config._first_content_line` rejects it, so
  `config.home_address()` raises.
- `## Location` is absent. `discovery._resolve_target_locations` falls back to the resume's
  `- Location: [City, Country]`, skips it as placeholder text, then calls
  `config.home_address()`, which raises.
- `## Scoring Notes` is absent. `rubric.compile_rubric` stores `scoring_guidance = None`.
- The resume is placeholder text throughout (`[Your Name]`, `[Skill 1]`), so query drafting
  and rubric drafting have no real input.

## What Changes

- Replace `data/resume.md` with a complete fictional front-end TypeScript/React engineer.
- Replace `data/job_preferences.md` with preferences that match that resume, filling every
  section the code reads: `## Location`, `## Home Address` (a real, geocodable street
  address) and `## Scoring Notes`, plus the free-text sections the LLM prompts receive.
- Remove all `(fill in ...)` and `[placeholder]` text from both files.
- Add an offline unit test that loads the active `data/` files through `jobsearch.config`
  and asserts every section the code reads resolves to a non-placeholder value.
- Update `README.md` and `docs/architecture.md`, which describe the files as templates.

## Capabilities

### New Capabilities
- `default-profile-data`: the committed resume and preferences form a runnable sample
  candidate. Every section the pipeline reads is present and filled in, so a fresh clone
  can run the full pipeline with only API keys configured.

### Modified Capabilities

## Impact

- `data/resume.md`, `data/job_preferences.md`: content replaced. Both have the
  skip-worktree bit set in the main checkout. This worktree has no bits set, so edits
  commit normally. Checkouts that have the bit set keep their local content.
- `tests/unit/`: one new test class. No `.py` file gains candidate content.
- `README.md`, `docs/architecture.md`: setup and file-table wording.
- No code changes to `jobsearch/`. CSG-37 (profile directory) and CSG-18 (default-data CI)
  are out of scope.
