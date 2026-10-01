# job-search-agent

**job-search-agent** is an agentic AI tool which streamlines job search. It takes over
query crafting, searching multiple engines, ad-by-ad validation, evaluation and ranking,
so that jobseekers can focus only on the ads which fit their own skills, preferences
and commute.

This is a personal project, started as an agentic-coding exercise (`docs/plan.md`).

## Key features

- Deriving job search queries from a jobseeker's CV and preferences, and running them across
  multiple job platforms and engines.
- Pre-filtering, deduping and pre-ranking results, ensuring LLM tokens are spent only on the most promising job ads.
- Using AI to score pre-selected ads against the user's skills and preferences, including
  real driving time from the candidate's home.
- Storing every evaluation in a database, so a posting is not re-scored on a later run
  unless you force it.

## Default usage

- The user writes their resume and preferences into
  [`profiles/personal/resume.md`](#your-personal-profile) and
  [`profiles/personal/job_preferences.md`](#your-personal-profile).
- At any time, the user runs `propose_jobs.py <n>` to get the `n` best-fitting newly-discovered jobs and the `n` overall best-fitting jobs in their job database

## Setup

job-search-agent runs inside a container and relies on your own accounts for LLM, web
search and commute-routing calls; it is currently configured to work with Anthropic, but can be edited to use other providers.

1. Clone the repo and put your API keys in
   [`~/.config/job-search-agent/.env`](.env.example). Create it from the template:
   ```
   mkdir -p ~/.config/job-search-agent
   cp .env.example ~/.config/job-search-agent/.env
   chmod 600 ~/.config/job-search-agent/.env
   ```
   Every checkout and worktree reads this file. The container mounts it read-only.

| Variable | Used for | Notes |
|----------|----------|-------|
| `ANTHROPIC_API_KEY` | All LLM calls, via aisuite | Paid |
| `TAVILY_API_KEY` | Web search and extraction (job ads, office addresses) | Free tier available |
| `ORS_API_KEY` | OpenRouteService geocoding and driving-time routing | Free |
| `GROQ_API_KEY` | Only `scripts/check_setup.py` for the moment | Free tier available |

   A command that reads a key missing from the file fails with:
   ```
   RuntimeError: required environment variable 'TAVILY_API_KEY' is not set: add it to ~/.config/job-search-agent/.env
   ```
   Add the key to `~/.config/job-search-agent/.env`. The next command reads it without a
   container restart.

2. Start the container and check the setup:
   ```
   podman-compose up -d
   podman-compose exec job-search python3 scripts/check_setup.py --default-profile
   ```
   `check_setup.py` lists the missing API keys and the missing `job_preferences.md`
   sections, then makes one call to each provider.

3. Find and present the best-fitting jobs for the sample candidate:
   ```
   podman-compose exec job-search python3 propose_jobs.py 3 --default-profile
   ```
   `--default-profile` selects the fictional candidate in
   [`profiles/default/resume.md`](profiles/default/resume.md) and
   [`profiles/default/job_preferences.md`](profiles/default/job_preferences.md). Its
   evaluations are stored in `profiles/default/` and do not appear in your own shortlists.

4. Create your personal profile from the sample:
   ```
   mkdir -p profiles/personal
   cp profiles/default/resume.md profiles/default/job_preferences.md profiles/personal/
   ```
   Replace their content with your own resume and preferences. Keep the `## Location`,
   `## Home Address` and `## Scoring Notes` sections of `job_preferences.md`: the pipeline
   reads them directly. `scripts/check_setup.py` without `--default-profile` reports each
   one that is missing or empty.

5. Run the search on your own profile:
   ```
   podman-compose exec job-search python3 propose_jobs.py 3
   ```
   Without `--default-profile`, every command uses `profiles/personal/`, and fails if
   `resume.md` or `job_preferences.md` is missing there. The search queries and the scoring
   rubric are built from your files on the first run. Repeat this command whenever you want
   new proposals.

## What to expect

`propose_jobs.py <n>` searches the job boards, pre-selects the most promising ads, evaluates
up to `3n` of them on fit and commute, and prints two shortlists of `n`: the best of this run,
and the best across every job evaluated so far.

Shown here with `propose_jobs.py 2`, so up to 6 ads are evaluated:

```
$ podman-compose exec job-search python3 propose_jobs.py 2

6 job ad(s) selected for evaluation:

- Senior Backend Engineer at Acme Robotics (Zurich, Switzerland)
  https://example-ats.com/acme/senior-backend-engineer
  prescore 6: role match, python, hybrid
  why: strong skills match, hybrid schedule fits stated preferences
...

11 job ad(s) dropped - not_selected:

- Support Engineer at Initech
  https://example-ats.com/initech/support-engineer
  below the top 6 by prescore and reviewer judgment
...

24 discovered -> 24 complete -> 20 fresh -> 17 distinct openings -> 13 not yet evaluated -> 6 selected (1 LLM call)

Evaluating Position: Senior Backend Engineer at Acme Robotics
Commute score: 40.0 min (2 days/week, Bahnhofstrasse 1, 8001 Zurich, Switzerland)
Compatibility score: 78/100
Works well: Backend-heavy role in robotics; Python and distributed systems match.
Does not work: Requires on-call rotation; team language is German.
Reviewed: no
Application status: new
...

=== Best overall ===

2 job(s) proposed out of 58 evaluated:

1. [89] Robotics Software Engineer at Vector Dynamics
   fit 74/100 | no commute (remote)
   https://example-ats.com/vector/robotics-software-engineer
2. [80] Staff Engineer, Perception at Northwind Labs
   fit 80/100 | commute unknown
   https://example-ats.com/northwind/staff-engineer-perception

56 evaluated but ranked below the top 2.

=== Best of this run ===

2 job(s) proposed out of 6 evaluated:

1. [77] Perception Engineer at Helios Optics
   fit 71/100 | commute 18 (weighted min)
   https://example-ats.com/helios/perception-engineer
2. [73] Senior Backend Engineer at Acme Robotics
   fit 78/100 | commute 40 (weighted min)
   https://example-ats.com/acme/senior-backend-engineer

4 evaluated but ranked below the top 2.
```

The bracketed number is the combined score: fit adjusted by commute. Helios outranks Acme
despite the lower fit, because its commute is shorter.

## Your personal profile

`profiles/personal/` holds your candidate:

| File | Content |
|------|---------|
| `resume.md` | Your resume |
| `job_preferences.md` | Your preferences |
| `evaluations.db` | Every evaluation, with its review status and notes |
| `compatibility_rubric.json`, `search_queries.json` | Rebuilt from `resume.md` and `job_preferences.md` when either changes |
| `evals/` | Your eval set, see [docs/evals.md](docs/evals.md) |

Git ignores the whole directory: `git status` does not list it and `git add -A` does not
stage it.

`git clean -x` deletes `profiles/personal/`. Back it up to a folder outside the checkout
that does not exist yet:
```
cp -r profiles/personal <folder>
```

Restore it from that folder:
```
rm -rf profiles/.personal.restore && cp -r <folder> profiles/.personal.restore && rm -rf profiles/personal && mv profiles/.personal.restore profiles/personal
```
The restore copies into an empty staging directory first. When that copy fails,
`profiles/personal/` is unchanged. After the restore, `profiles/personal/` holds the
backup's files and no others.

Back up or restore only while no pipeline command runs. A copy taken during a run can hold
an inconsistent `evaluations.db`.

## Developer notes

A command run without `--default-profile` or `--scratch` in a checkout that holds your real
personal profile writes to that profile. Three setups leave it unchanged:

- `--scratch` runs a command on a temporary copy of its profile, deleted when the command
  exits. A scratch copy lasts one command: a second command does not see the first one's
  writes. It combines with `--default-profile`.
  ```
  podman-compose exec job-search python3 evaluate_job_post.py <url> --scratch
  ```
- `scripts/profile.sh reset-default` deletes the default profile's `evaluations.db`,
  `compatibility_rubric.json` and `search_queries.json`, and keeps its resume, preferences
  and eval set. It runs on the host or in the container. The e2e tests run it in setup.
- A new git worktree has no personal profile. From a worktree under `.trees/`, copy the
  main checkout's:
  ```
  cp -r ../../profiles/personal profiles/
  ```
  Changes to the worktree's data stay in its copy and do not reach the main checkout.

## Learn more

Everything past basic use is documented separately:

| Document | Answers |
|----------|---------|
| [docs/architecture.md](docs/architecture.md) | Commands and flags, the pipeline internals, the database and how to query it, file layout, and the profiles and API key locations |
| [docs/evals.md](docs/evals.md) | How the tests and eval harness work, and what the metrics mean |
| [docs/roadmap.md](docs/roadmap.md) | Known limitations that need code changes |

## License

MIT. See [LICENSE](LICENSE).
