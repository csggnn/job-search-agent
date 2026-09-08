This project is about using what i have learned from the agentic coding course while building a tool for web search. The tool should:

- Search for local jobs with valid prompts — To do
- Parse job pages for location, description, compatibility with my resume and job preferences — Done (`scrape_post`, `figure_address`, `figure_days_on_office`, `compatibility_score`)
- Score and propose a subset — Done: `evaluate_job` scores one job, `jobsearch/ranking.py` combines fit and commute into one score, and `propose_jobs.py <n>` evaluates 3n job ads and proposes the top n
- Store jobs and evaluations in a database — Done: SQLite storage caches evaluations by normalized URL and preserves user review fields across re-evaluation
- Version my resume and job_preferences so that a job post could be evaluated again if those change — Needs improvement: the compatibility rubric is already hash-cached against resume/job_preferences changes, but this needs rework once the jobs database exists, so past evaluations stay tied to the resume/preferences version that produced them

4 main learning items:
- programmatic use of LLMs through aisuite (OK)
- reflection for better results (OK) - `reflect_on_rubric`
- tools and MCP (OK) - `test_regex` tool fed to the LLM via aisuite `tools=`
- evals (To do)

Other optional learning items:
- multiagent
- planning
