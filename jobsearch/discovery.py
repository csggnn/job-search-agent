"""
Discover new job ads from the web: derive search queries from resume.md +
job_preferences.md (+ HOME_ADDRESS) via an LLM, search Indeed + LinkedIn (via the JobSpy
library), and surface new job ad URLs not already in the evaluations DB - optionally
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
from jobsearch.preselection import (
    preselect, format_preselection, DEFAULT_N, AGGREGATOR_DOMAINS as _AGGREGATOR_DOMAINS,
)
from jobsearch.rubric import load_or_compile_rubric
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
# own careers page. Defined in jobsearch.preselection, which ranks the same domains when it
# picks the surviving url of a duplicate collapse.


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
    """ normalize a pandas cell to a plain Python value, turning NaN/missing into None.
        Container cells (JobSpy returns a few list-valued columns) are passed through, since
        pd.isna() answers element-wise for those.
    """
    if isinstance(value, (list, tuple, set, dict)):
        return value or None
    return None if pd.isna(value) else value


def _clean_text(value):
    """ _clean() for a cell rendered as text (e.g. date_posted, which JobSpy returns as a
        datetime.date), so a job ad dict stays JSON-shaped
    """
    value = _clean(value)
    return None if value is None else str(value)


def _best_apply_link(record):
    """ pick the most useful URL for a JobSpy result: the direct apply link (usually the
        original job board/company posting) if JobSpy resolved one, falling back to the
        site's own job page URL
    """
    return _clean(record.get("job_url_direct")) or _clean(record.get("job_url"))


def jobspy_search(query, country, max_results=DEFAULT_MAX_RESULTS, debug=False,
                  linkedin_descriptions=True):
    """ search Indeed + LinkedIn (via JobSpy) for one query entry, returning job ad dicts
        holding the fields pre-selection judges an ad on without re-fetching it.

        linkedin_descriptions=True costs one extra HTTP request per LinkedIn result (latency
        and block risk, no API spend). Without it LinkedIn ads carry no description, so
        pre-selection judges them on their title while Indeed ads are judged on their text.
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
        linkedin_fetch_description=linkedin_descriptions,
    )
    if debug:
        print(f"[jobspy_search] params={params}")

    jobs = scrape_jobs(**params)
    records = jobs.to_dict("records")

    job_ads = [
        {
            "url": _best_apply_link(r),
            "title": _clean(r.get("title")),
            "company": _clean(r.get("company")),
            "location": _clean(r.get("location")),
            "description": _clean(r.get("description")),
            "is_remote": _clean(r.get("is_remote")),
            "date_posted": _clean_text(r.get("date_posted")),
            "job_type": _clean_text(r.get("job_type")),
            "job_level": _clean_text(r.get("job_level")),
            "min_amount": _clean(r.get("min_amount")),
            "max_amount": _clean(r.get("max_amount")),
            "currency": _clean(r.get("currency")),
            "company_industry": _clean(r.get("company_industry")),
            "work_from_home_type": _clean(r.get("work_from_home_type")),
        }
        for r in records
    ]
    job_ads = [c for c in job_ads if c["url"]]
    if debug:
        print(f"[jobspy_search] {len(job_ads)} job ad(s)")
    return job_ads


def discover_job_ads(cache, max_results_per_query=DEFAULT_MAX_RESULTS, debug=False,
                     linkedin_descriptions=True):
    """ run one JobSpy search per cached query, aggregating job ads deduped by
        normalized url (first occurrence keeps the ad's fields; matched_queries collects
        every query phrase that surfaced it)
    """
    primary_country = cache["primary_country"]
    aggregated = {}
    for q in cache["queries"]:
        country = q["country"] if not q["is_remote"] else primary_country
        results = jobspy_search(q, country, max_results_per_query, debug, linkedin_descriptions)
        for r in results:
            normalized = storage.normalize_url(r["url"])
            if normalized not in aggregated:
                aggregated[normalized] = {**r, "matched_queries": [q["query"]]}
            else:
                aggregated[normalized]["matched_queries"].append(q["query"])
    return list(aggregated.values())


def filter_new_job_ads(job_ads):
    """ drop job ads already present in storage.py's evaluations DB (by normalized url) """
    known = {normalized for _, normalized in storage.list_evaluated_urls()}
    return [c for c in job_ads if storage.normalize_url(c["url"]) not in known]


def _print_job_ads(job_ads):
    """ print newly discovered job ad urls for manual review """
    print(f"\n{len(job_ads)} new job ad(s):\n")
    for c in job_ads:
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
    result_urls = [
        r["url"] for r in results["results"]
        if urlsplit(r["url"]).netloc != excluded_domain
        and not any(d in urlsplit(r["url"]).netloc for d in _AGGREGATOR_DOMAINS)
    ][:3]
    if debug:
        print(f"[find_company_posting_url] query={query!r} results={result_urls}")
    if not result_urls:
        return None

    extracted = tavily.extract(result_urls, format="text")
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
        "It is common and expected for NONE of these results to qualify (e.g. the only "
        "results are re-posters, unrelated companies, or listing pages) - in that case you "
        "must respond with null rather than picking the closest/least-bad option. Respond "
        'with only a JSON object: {"url": <the matching url, or null if none of these pages '
        "satisfies all three conditions above>}.",
        max_tokens=256,
    )
    if debug:
        print(f"[find_company_posting_url] -> {result}")
    return result.get("url")


def _evaluate_job_ad(job_ad, debug=False):
    """ evaluate one pre-selected job ad, returning the evaluation or None if no url for it
        could be scraped.

        The urls pre-selection collapsed into this one as "alternates" are tried before
        find_company_posting_url(), which pays a Tavily search plus an LLM call to rediscover
        a url this run already had.
    """
    for url in [job_ad["url"], *(job_ad.get("alternates") or [])]:
        try:
            return evaluate_job(url)
        except ScrapeError as e:
            print(f"  could not scrape {url} ({e})")

    print(f"  searching {job_ad['company']}'s site directly")
    alt_url = find_company_posting_url(
        job_ad["company"], job_ad["title"], urlsplit(job_ad["url"]).netloc, debug=debug,
    )
    if not alt_url:
        print(f"  skipping {job_ad['url']}: no matching posting found on {job_ad['company']}'s site")
        return None
    try:
        return evaluate_job(alt_url)
    except Exception as e:
        print(f"  skipping {job_ad['url']}: fallback {alt_url} also failed: {e}")
        return None


def discover_jobs(evaluate=False, limit=None, max_results_per_query=DEFAULT_MAX_RESULTS,
                   force_queries=False, preselect_job_ads=True, linkedin_descriptions=True,
                   debug=False):
    """ full discovery pipeline: compile/reuse search queries, search the job boards, dedupe
        within-run and against storage, pre-select the job ads worth evaluating, then either
        list them or run evaluate_job() on them.

        limit is pre-selection's N - the number of job ads handed to evaluation - not a
        truncation of the tail. preselect_job_ads=False restores the pre-selection-free
        behaviour (evaluate the first `limit` job ads in discovery order), so the two are
        comparable on one job ad set.
    """
    cache = compile_queries() if force_queries else load_or_compile_queries()

    # resolved before discovery so a recompile cannot land partway through a run:
    # evaluate_job() loads the rubric per job, and prescoring against one rubric while
    # scoring against another makes the two stages disagree
    rubric = load_or_compile_rubric() if preselect_job_ads else None

    job_ads = discover_job_ads(cache, max_results_per_query, debug, linkedin_descriptions)
    new_job_ads = filter_new_job_ads(job_ads)

    if not new_job_ads:
        print("No new job ads found.")
        return []

    if preselect_job_ads:
        result = preselect(
            new_job_ads,
            n=limit or DEFAULT_N,
            rubric=rubric,
            resume=read_resume(),
            preferences=read_job_preferences(),
            known_job_openings=storage.list_evaluated_job_openings(),
        )
        print(format_preselection(result))
        to_run = result["selected"]
    else:
        _print_job_ads(new_job_ads)
        to_run = new_job_ads[:limit] if limit else new_job_ads

    if not evaluate:
        print("\nRun with --evaluate to score these (costs LLM/Tavily-extract/ORS calls per url).")
        return to_run

    results = []
    for job_ad in to_run:
        try:
            evaluation = _evaluate_job_ad(job_ad, debug)
        except Exception as e:
            print(f"  skipping {job_ad['url']}: {e}")
            continue
        if evaluation is not None:
            results.append(evaluation)
    return results
