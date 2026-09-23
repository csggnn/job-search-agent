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

- The user edits `data/resume.md` and `data/job_preferences.md`, with their own resume and
  preferences.
- At any time, the user runs `propose_jobs.py <n>` to get the `n` best-fitting newly-discovered jobs and the `n` overall best-fitting jobs in their job database

## Setup

job-search-agent runs inside a container and relies on your own accounts for LLM, web
search and commute-routing calls; it is currently configured to work with Anthropic, but can be edited to use other providers.

1. Clone the repo and fill in `.env`, which is present as a template.

| Variable | Used for | Notes |
|----------|----------|-------|
| `ANTHROPIC_API_KEY` | All LLM calls, via aisuite | Paid |
| `TAVILY_API_KEY` | Web search and extraction (job ads, office addresses) | Free tier available |
| `ORS_API_KEY` | OpenRouteService geocoding and driving-time routing | Free |
| `GROQ_API_KEY` | Only `scripts/check_setup.py` for the moment | Free tier available |

2. Edit `data/resume.md` and `data/job_preferences.md` with your own resume and
   preferences. An example is provided in each file.

3. Start the container and check the API keys are wired up:
   ```
   podman-compose up -d
   podman-compose exec job-search python3 scripts/check_setup.py
   ```

4. Find and present the best-fitting jobs:
   ```
   podman-compose exec job-search python3 propose_jobs.py 3
   ```

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

## Learn more

Everything past basic use is documented separately:

| Document | Answers |
|----------|---------|
| [docs/architecture.md](docs/architecture.md) | Commands and flags, the pipeline internals, the database and how to query it, file layout, and how personalization files stay out of git |
| [docs/evals.md](docs/evals.md) | How the tests and eval harness work, and what the metrics mean |
| [docs/roadmap.md](docs/roadmap.md) | Known limitations that need code changes |

## License

MIT. See [LICENSE](LICENSE).
