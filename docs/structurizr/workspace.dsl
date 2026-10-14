workspace "Job Search Agent" "Container view of the job search evaluation pipeline" {

    configuration {
        scope softwaresystem
    }

    model {
        dev = person "Developer" "Changes the code, curates and runs evals"
        seeker = person "Job seeker" "Maintains the profile, runs the pipeline, reviews results"

        jsa = softwareSystem "Job Search Agent" "Scrapes, scores and ranks job postings against a candidate profile" {
            evals = container "Eval harness" "Scores stored ads against verified ground truth, per pipeline step" "Python CLI"
            engine = container "Job search engine" "Discovers, pre-selects, evaluates and ranks job postings" "Python CLI"
            ui = container "UI" "Read-only browser over saved evaluations" "Python, Flask"

            profile = container "User profile" "resume.md, job_preferences.md" "Markdown files" "Store"
            derived = container "Derived profile" "compatibility_rubric.json, search_queries.json" "JSON files" "Store"
            db = container "Evaluations DB" "Evaluations, criteria matches, review status" "SQLite" "Store"
            evalset = container "Eval dataset" "cases.json, ads/, runs/" "JSON files" "Store"
        }

        llm = softwareSystem "Anthropic" "LLM API, via aisuite" "External"
        tavily = softwareSystem "Tavily" "Web extract and search" "External"
        ors = softwareSystem "OpenRouteService" "Geocoding and routing" "External"
        boards = softwareSystem "Job boards" "Indeed, LinkedIn, Ashby" "External"

        seeker -> ui "Browses evaluations" "HTTP, localhost"
        seeker -> engine "Runs discovery, evaluation, proposals" "CLI"
        seeker -> profile "Edits resume and preferences" "Text editor"
        dev -> evals "Captures cases, drafts labels, runs evals" "CLI"
        dev -> evalset "Verifies ground truth" "Text editor"

        ui -> db "Reads" "SQLite, read-only mount"

        engine -> profile "Reads" "File read"
        engine -> derived "Compiles and reads rubric and search queries" "File I/O"
        engine -> db "Reads and writes evaluations" "SQLite"
        engine -> llm "Extraction, rubric, scoring, summary" "HTTPS"
        engine -> tavily "Posting extract (manual URL), office-address search" "HTTPS"
        engine -> ors "Geocoding, routing" "HTTPS"
        engine -> boards "Searches postings; fetches Ashby postings" "JobSpy, HTTPS"

        evals -> profile "Reads" "File read"
        evals -> derived "Reads rubric, no recompile" "File read"
        evals -> evalset "Reads cases and ads, writes runs" "File I/O"
        evals -> llm "Extraction, scoring" "HTTPS"
        evals -> tavily "Posting extract (capture), office-address search" "HTTPS"
        evals -> ors "Geocoding, routing (unless --no-commute)" "HTTPS"
    }

    views {
        container jsa "Containers" "Container diagram: Job Search Agent" {
            include *
        }

        styles {
            element "Person" {
                shape Person
                background #08427b
                color #ffffff
            }
            element "Container" {
                background #438dd5
                color #ffffff
            }
            element "Store" {
                shape Cylinder
            }
            element "External" {
                background #999999
                color #ffffff
            }
        }
    }
}
