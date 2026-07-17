"""
Discover new job ad candidates from the web: derive search queries from resume.md +
job_preferences.md (+ HOME_ADDRESS) via an LLM, search Indeed + LinkedIn (via the JobSpy
library), and surface new candidate URLs not already in the evaluations DB - optionally
running them straight through evaluate_job().

JobSpy is used instead of the SerpApi google_jobs engine because Google Jobs' index is
effectively empty for some markets (e.g. Belgium) - JobSpy scrapes job boards directly and
reliably returns results there.
"""

import json
import os
import re
from urllib.parse import urlsplit

import pandas as pd
from jobspy import scrape_jobs
from jobspy.model import Country
from tavily import TavilyClient

from jobsearch import config, storage
from jobsearch.config import (
    read_resume, read_job_preferences, file_hash, extract_section,
    RESUME_PATH, JOB_PREFERENCES_PATH, DATA_DIR,
)
from jobsearch.llm import ask_json
from jobsearch.evaluation import evaluate_job
from jobsearch.scrape import ScrapeError

QUERIES_PATH = os.path.join(DATA_DIR, "search_queries.json")
QUERY_MAX_TOKENS = 2048
DEFAULT_MAX_RESULTS = 10
DEFAULT_SITES = ["indeed", "linkedin"]
_COUNTRY_CODE_RE = re.compile(r"^[a-z]{2}$")
_COUNTRY_NAMES = {c.value[1]: c.value[0] for c in Country}  # alpha-2 -> JobSpy country name

# third-party re-posters/aggregators tend to carry a thin/stale copy of the posting (missing
# the detail an LLM needs to score it well) - excluded from the fallback search alongside
# whichever domain originally failed to scrape, so results are biased toward the company's
# own careers page
_AGGREGATOR_DOMAINS = {
    "linkedin.com", "indeed.com", "glassdoor.com", "jobleads.com", "bebee.com",
    "monster.com", "jobrapido.com", "jooble.org", "careerjet.com", "simplyhired.com",
    "ziprecruiter.com", "talent.com", "adzuna.com", "neuvoo.com", "jobsora.com",
    "trabajo.org", "whatjobs.com", "learn4good.com", "receptix.com",
}


def _resolve_target_locations(resume, preferences):
    """ return the location strings usable for non-remote search queries: job_preferences.md's
        Location section if present and filled in, else resume.md's Contact location
        (skipped if still template placeholder text), else HOME_ADDRESS
    """
    section = extract_section(preferences, "Location")
    if section:
        # only lines starting with "-" are distinct entries; wrapped continuation lines of a
        # multi-line placeholder bullet (e.g. "(fill in: ...\n  one per line, e.g. ...)") don't
        # start with "-" and must be ignored rather than treated as extra locations
        locations = [
            stripped.lstrip("-").strip()
            for stripped in (line.strip() for line in section.splitlines())
            if stripped.startswith("-") and stripped.lstrip("-").strip()
            and not stripped.lstrip("-").strip().startswith("(fill in")
        ]
        if locations:
            return locations

    match = re.search(r"^-\s*Location:\s*(.+)$", resume, re.MULTILINE)
    if match and not match.group(1).strip().startswith("["):
        return [match.group(1).strip()]

    return [config.home_address()]


def draft_queries(resume, preferences, target_locations):
    """ ask the LLM to propose job search query phrases, tagged remote vs location-bound, plus a
        primary country code (ISO 3166-1 alpha-2) to use as search context for remote queries
    """
    locations_block = "\n".join(f"- {loc}" for loc in target_locations)

    return ask_json(
        "You are proposing web-search queries to find job postings for a candidate, to be run "
        "against the Google Jobs search engine.\n\n"
        f"Candidate resume:\n{resume}\n\n"
        f"Candidate job preferences:\n{preferences}\n\n"
        f"Target locations the candidate is open to for on-site/hybrid roles:\n{locations_block}\n\n"
        "Propose 4-10 distinct search queries covering different role/title/seniority phrasings "
        "drawn from the resume and preferences above - do not build a location x title cross "
        "product, just distinct role phrasings. For each query, decide:\n"
        '- "query": ONLY the role/keyword phrase (e.g. "senior backend engineer python") - do '
        'NOT include any location or the word "remote" in this field.\n'
        '- "is_remote": true only if the candidate\'s preferences indicate they are open to fully '
        "remote roles (check Must-Haves/Nice-to-Haves/Disqualifiers); if preferences require "
        "on-site/hybrid only, produce no is_remote:true queries at all.\n"
        '- for non-remote queries only: "location" must be exactly one of the target locations '
        'above, verbatim, and "country" must be the two-letter ISO 3166-1 alpha-2 country code '
        '(lowercase) for that location (e.g. "Brussels, Belgium" -> "be"). Both must be null for '
        "remote queries.\n\n"
        'Also include a top-level "primary_country" field: the two-letter country code for the '
        "candidate's primary/home location (the first target location above), used as search "
        "context for any remote queries.\n\n"
        'Respond with only a JSON object: {"primary_country": <str>, "queries": [{"query": <str>, '
        '"is_remote": <bool>, "location": <str or null>, "country": <str or null>}, ...]}',
        max_tokens=QUERY_MAX_TOKENS,
    )


def _validate_queries(queries, target_locations):
    """ drop any non-remote query with an invalid location/country, guarding against a
        non-compliant LLM reply
    """
    valid = []
    for q in queries:
        if not q["is_remote"]:
            if q["location"] not in target_locations:
                print(f"Warning: dropping query {q['query']!r} - location {q['location']!r} not in target locations")
                continue
            if not _COUNTRY_CODE_RE.match((q["country"] or "").lower()):
                print(f"Warning: dropping query {q['query']!r} - invalid country code {q['country']!r}")
                continue
            q["country"] = q["country"].lower()
        valid.append(q)
    return valid


def compile_queries():
    """ (re)build the search query set from resume.md + job_preferences.md + HOME_ADDRESS """
    resume = read_resume()
    preferences = read_job_preferences()
    target_locations = _resolve_target_locations(resume, preferences)

    draft = draft_queries(resume, preferences, target_locations)
    queries = _validate_queries(draft["queries"], target_locations)

    primary_country = draft.get("primary_country")
    if not _COUNTRY_CODE_RE.match((primary_country or "").lower()):
        print(f"Warning: invalid primary_country {primary_country!r} - dropping remote queries")
        primary_country = None
        queries = [q for q in queries if not q["is_remote"]]
    else:
        primary_country = primary_country.lower()

    cache = {
        "resume_hash": file_hash(RESUME_PATH),
        "preferences_hash": file_hash(JOB_PREFERENCES_PATH),
        "home_address": config.home_address(),
        "primary_country": primary_country,
        "queries": queries,
    }
    with open(QUERIES_PATH, "w") as f:
        json.dump(cache, f, indent=2)
    return cache


def load_or_compile_queries():
    """ return the cached query set if resume.md/job_preferences.md/HOME_ADDRESS haven't
        changed, else recompile
    """
    if os.path.exists(QUERIES_PATH):
        with open(QUERIES_PATH) as f:
            cached = json.load(f)
        if (
            cached.get("resume_hash") == file_hash(RESUME_PATH)
            and cached.get("preferences_hash") == file_hash(JOB_PREFERENCES_PATH)
            and cached.get("home_address") == config.home_address()
        ):
            return cached
    return compile_queries()


def _clean(value):
    """ normalize a pandas cell to a plain Python value, turning NaN/missing into None """
    return None if pd.isna(value) else value


def _best_apply_link(record):
    """ pick the most useful URL for a JobSpy result: the direct apply link (usually the
        original job board/company posting) if JobSpy resolved one, falling back to the
        site's own job page URL
    """
    return _clean(record.get("job_url_direct")) or _clean(record.get("job_url"))


def jobspy_search(query, country, max_results=DEFAULT_MAX_RESULTS, debug=False):
    """ search Indeed + LinkedIn (via JobSpy) for one query entry, returning candidate job
        dicts: {url, title, company, location}
    """
    country_name = _COUNTRY_NAMES.get(country, "worldwide")
    location = query["location"] if not query["is_remote"] else _COUNTRY_NAMES.get(country)

    params = dict(
        site_name=DEFAULT_SITES,
        search_term=query["query"],
        location=location,
        is_remote=query["is_remote"],
        country_indeed=country_name,
        results_wanted=max_results,
    )
    if debug:
        print(f"[jobspy_search] params={params}")

    jobs = scrape_jobs(**params)
    records = jobs.to_dict("records")

    candidates = [
        {
            "url": _best_apply_link(r),
            "title": _clean(r.get("title")),
            "company": _clean(r.get("company")),
            "location": _clean(r.get("location")),
        }
        for r in records
    ]
    candidates = [c for c in candidates if c["url"]]
    if debug:
        print(f"[jobspy_search] {len(candidates)} candidate(s)")
    return candidates


def discover_candidates(cache, max_results_per_query=DEFAULT_MAX_RESULTS, debug=False):
    """ run one JobSpy search per cached query, aggregating candidates deduped by
        normalized url (first occurrence keeps title/company/location; matched_queries collects
        every query phrase that surfaced it)
    """
    primary_country = cache["primary_country"]
    aggregated = {}
    for q in cache["queries"]:
        country = q["country"] if not q["is_remote"] else primary_country
        results = jobspy_search(q, country, max_results_per_query, debug)
        for r in results:
            normalized = storage.normalize_url(r["url"])
            if normalized not in aggregated:
                aggregated[normalized] = {**r, "matched_queries": [q["query"]]}
            else:
                aggregated[normalized]["matched_queries"].append(q["query"])
    return list(aggregated.values())


def filter_new_candidates(candidates):
    """ drop candidates already present in storage.py's evaluations DB (by normalized url) """
    known = {normalized for _, normalized in storage.list_evaluated_urls()}
    return [c for c in candidates if storage.normalize_url(c["url"]) not in known]


def _print_candidates(candidates):
    """ print newly discovered candidate job urls for manual review """
    print(f"\n{len(candidates)} new job candidate(s):\n")
    for c in candidates:
        print(f"- {c['title'] or '(untitled)'} at {c['company'] or '(unknown company)'} "
              f"({c['location'] or 'location unknown'})")
        print(f"  {c['url']}")
        print(f"  matched: {', '.join(c['matched_queries'])}")


def find_company_posting_url(company, title, excluded_domain, debug=False):
    """ when a discovered posting's URL couldn't be scraped (e.g. a JS-heavy aggregator page
        like LinkedIn/Ashby), search the web for the company's own careers page for the same
        role and return its URL - None if no matching posting is found there. Deliberately
        does not fall back to third-party re-poster sites (jobleads, bebee, ...): those tend to
        carry a thin/stale copy of the posting that scores worse than having no posting at all.
    """
    query = f"{company} careers {title}"
    tavily = TavilyClient(api_key=config.require_env("TAVILY_API_KEY"))
    results = tavily.search(query, max_results=5)
    # skip the domain that already failed to extract (retrying there just reproduces the
    # original failure) and known aggregators/re-posters, biasing toward the company's own site
    candidate_urls = [
        r["url"] for r in results["results"]
        if urlsplit(r["url"]).netloc != excluded_domain
        and not any(d in urlsplit(r["url"]).netloc for d in _AGGREGATOR_DOMAINS)
    ][:3]
    if debug:
        print(f"[find_company_posting_url] query={query!r} candidates={candidate_urls}")
    if not candidate_urls:
        return None

    extracted = tavily.extract(candidate_urls, format="text")
    if not extracted["results"]:
        return None

    context = "\n\n---\n\n".join(
        f"{r['url']}\n{r['raw_content'][:3000]}" for r in extracted["results"]
    )
    result = ask_json(
        f"Company being searched for: {company}\nJob title being searched for: {title}\n\n"
        f"Search results (url + page content):\n{context}\n\n"
        "Identify which URL, if any, is a page containing this specific job posting's own "
        "full requirements/responsibilities text - not just its title - published by this "
        f"exact company ({company}). A page qualifies only if ALL of the following are true:\n"
        "1. It shows this role's own requirements/responsibilities, not just its title inside "
        "a list of the company's other open positions or a company profile summary.\n"
        "2. It's this exact role, not a different one.\n"
        f"3. The page's own content identifies the employer as {company} - this is critical, "
        "since job titles repeat across many unrelated employers, so a title/seniority match "
        "alone is not enough.\n\n"
        "It is common and expected for NONE of the candidates to qualify (e.g. the only "
        "results are re-posters, unrelated companies, or listing pages) - in that case you "
        "must respond with null rather than picking the closest/least-bad option. Respond "
        'with only a JSON object: {"url": <the matching url, or null if none of these pages '
        "satisfies all three conditions above>}.",
        max_tokens=256,
    )
    if debug:
        print(f"[find_company_posting_url] -> {result}")
    return result.get("url")


def discover_jobs(evaluate=False, limit=None, max_results_per_query=DEFAULT_MAX_RESULTS,
                   force_queries=False, debug=False):
    """ full discovery pipeline: compile/reuse search queries, search Google Jobs, dedupe
        within-run and against storage, then either list new candidates or run evaluate_job()
        on them
    """
    cache = compile_queries() if force_queries else load_or_compile_queries()
    candidates = discover_candidates(cache, max_results_per_query, debug)
    new_candidates = filter_new_candidates(candidates)

    if not new_candidates:
        print("No new job candidates found.")
        return []

    _print_candidates(new_candidates)

    if not evaluate:
        print("\nRun with --evaluate to score these (costs LLM/Tavily-extract/ORS calls per url).")
        return new_candidates

    to_run = new_candidates[:limit] if limit else new_candidates
    results = []
    for c in to_run:
        try:
            results.append(evaluate_job(c["url"]))
        except ScrapeError as e:
            print(f"  could not scrape {c['url']} ({e}) - searching {c['company']}'s site directly")
            alt_url = find_company_posting_url(
                c["company"], c["title"], urlsplit(c["url"]).netloc, debug=debug,
            )
            if not alt_url:
                print(f"  skipping {c['url']}: no matching posting found on {c['company']}'s site")
                continue
            try:
                results.append(evaluate_job(alt_url))
            except Exception as e2:
                print(f"  skipping {c['url']}: fallback {alt_url} also failed: {e2}")
        except Exception as e:
            print(f"  skipping {c['url']}: {e}")
    return results
