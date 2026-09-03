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
- Storing every evaluation in a database, so no posting is scored twice.

## Default usage

- The user edits `data/resume.md` and `data/job_preferences.md`, with their own resume and
  preferences.
- At any time, the user asks the agent to find and present a set of best fitting jobs.

**Note:** The implementation of a single end-to-end CLI for selective presentation of jobs
is in progress. For the moment, ask your AI harness to "pre-select 20 job ads and evaluate
them, then report the top 5". Under the hood, your harness will run
`discover_jobs.py --evaluate --limit 20`, which will evaluate 20 job ads scoring them on
fit and commute. You may want to add extra instructions on how to combine fitness and
commute metrics in the selection of the jobs to be presented to you.

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
| `HOME_ADDRESS` | The address commute times are computed from | Not a key |

2. Edit `data/resume.md` and `data/job_preferences.md` with your own resume and
   preferences. An example is provided in each file.

3. Start the container and check the API keys are wired up:
   ```
   podman-compose up -d
   podman-compose exec job-search python3 scripts/check_setup.py
   ```

4. Ask your harness to find and present the best fitting jobs, or run it directly:
   ```
   podman-compose exec job-search python3 discover_jobs.py --evaluate --limit 3
   ```

## What to expect

`discover_jobs.py --evaluate` first reports pre-selection's own reasoning, then evaluates
each selected ad in turn. Shown here with `--limit 3` to keep the example short:

```
$ python discover_jobs.py --evaluate --limit 3

3 job ad(s) selected for evaluation:

- Senior Backend Engineer at Acme Robotics (Zurich, Switzerland)
  https://example-ats.com/acme/senior-backend-engineer
  prescore 6: role match, python, hybrid
  why: strong skills match, hybrid schedule fits stated preferences
...

8 job ad(s) dropped - not_selected:

- Support Engineer at Initech
  https://example-ats.com/initech/support-engineer
  below the top 3 by prescore and reviewer judgment
...

18 discovered -> 16 fresh -> 14 distinct openings -> 11 not yet evaluated -> 3 selected (1 LLM call)

Evaluating Position: Senior Backend Engineer at Acme Robotics
Commute score: 41.5 min (2 days/week, Bahnhofstrasse 1, 8001 Zurich, Switzerland)
Compatibility score: 78/100
Works well: Backend-heavy role in robotics; Python and distributed systems match.
Does not work: Requires on-call rotation; team language is German.
Reviewed: no
Application status: new
...
```

## Learn more

Everything past basic use is documented separately:

| Document | Answers |
|----------|---------|
| [docs/architecture.md](docs/architecture.md) | Commands and flags, the pipeline internals, the database and how to query it, file layout, and how personalization files stay out of git |
| [docs/evals.md](docs/evals.md) | How the tests and eval harness work, and what the metrics mean |
| [docs/roadmap.md](docs/roadmap.md) | Known limitations that need code changes |

## License

MIT. See [LICENSE](LICENSE).
