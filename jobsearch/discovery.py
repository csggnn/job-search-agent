"""
Discover new job ads from the web: derive search queries from resume.md +
job_preferences.md via an LLM, search Indeed + LinkedIn (via the JobSpy library), and
surface new job ad URLs not already in the evaluations DB - optionally running them
through evaluate_job() on the text JobSpy returned.

JobSpy is used instead of the SerpApi google_jobs engine because Google Jobs' index is
effectively empty for some markets (e.g. Belgium) - JobSpy scrapes job boards directly and
reliably returns results there.
"""

import json
import os
import re

import pandas as pd
from jobspy import scrape_jobs
from jobspy.model import Country

from jobsearch import config, storage
from jobsearch.config import (
    read_resume, read_job_preferences, file_hash, extract_section,
    RESUME_PATH, JOB_PREFERENCES_PATH, DATA_DIR,
)
from jobsearch.llm import ask_json
from jobsearch.evaluation import evaluate_job
from jobsearch.preselection import preselect, format_preselection, DEFAULT_N
from jobsearch.rubric import load_or_compile_rubric
from jobsearch.scrape import ScrapeError, validate_post

QUERIES_PATH = os.path.join(DATA_DIR, "search_queries.json")
QUERY_MAX_TOKENS = 2048
DEFAULT_MAX_RESULTS = 10
DEFAULT_SITES = ["indeed", "linkedin"]
_COUNTRY_CODE_RE = re.compile(r"^[a-z]{2}$")
_COUNTRY_NAMES = {c.value[1]: c.value[0] for c in Country}  # alpha-2 -> JobSpy country name


def _resolve_target_locations(resume, preferences):
    """ return the location strings usable for non-remote search queries: job_preferences.md's
        Location section if present and filled in, else resume.md's Contact location
        (skipped if still template placeholder text), else the home address from
        job_preferences.md
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
    """ (re)build the search query set from resume.md + job_preferences.md """
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
        "primary_country": primary_country,
        "queries": queries,
    }
    with open(QUERIES_PATH, "w") as f:
        json.dump(cache, f, indent=2)
    return cache


def load_or_compile_queries():
    """ return the cached query set if resume.md/job_preferences.md haven't changed, else
        recompile
    """
    if os.path.exists(QUERIES_PATH):
        with open(QUERIES_PATH) as f:
            cached = json.load(f)
        if (
            cached.get("resume_hash") == file_hash(RESUME_PATH)
            and cached.get("preferences_hash") == file_hash(JOB_PREFERENCES_PATH)
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


def jobspy_search(query, country, max_results=DEFAULT_MAX_RESULTS, debug=False):
    """ search Indeed + LinkedIn (via JobSpy) for one query entry, returning one job ad dict
        per result that has a url.

        Main fields of each dict:
        - url: the direct apply link if JobSpy resolved one, else the job board's page URL.
          Never None.
        - job_title, company: the posting's job title and employer name.
        - location: the posting's location string, or the generic search location when
          JobSpy returned none. None when neither is available.
        - description: the full ad text.

        job_title, company and description are None when JobSpy returned no value. The
        other keys (is_remote, date_posted, job_type, job_level, min_amount, max_amount,
        currency, company_industry, work_from_home_type) carry JobSpy's metadata as plain
        values, None when missing.

        JobSpy fetches each LinkedIn description with one extra HTTP request per result
        (latency and block risk, no API spend).
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
        linkedin_fetch_description=True,
    )
    if debug:
        print(f"[jobspy_search] params={params}")

    jobs = scrape_jobs(**params)
    records = jobs.to_dict("records")

    job_ads = [
        {
            "url": _best_apply_link(r),
            "job_title": _clean(r.get("title")),
            "company": _clean(r.get("company")),
            "location": _clean(r.get("location")) or location,
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


def discover_job_ads(cache, max_results_per_query=DEFAULT_MAX_RESULTS, debug=False):
    """ run one JobSpy search per cached query, aggregating job ads deduped by
        normalized url (first occurrence keeps the ad's fields; matched_queries collects
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


def filter_new_job_ads(job_ads):
    """ drop job ads already present in storage.py's evaluations DB (by normalized url) """
    known = {normalized for _, normalized in storage.list_evaluated_urls()}
    return [c for c in job_ads if storage.normalize_url(c["url"]) not in known]


def _print_job_ads(job_ads):
    """ print newly discovered job ad urls for manual review """
    print(f"\n{len(job_ads)} new job ad(s):\n")
    for c in job_ads:
        print(f"- {c['job_title'] or '(untitled)'} at {c['company'] or '(unknown company)'} "
              f"({c['location'] or 'location unknown'})")
        print(f"  {c['url']}")
        print(f"  matched: {', '.join(c['matched_queries'])}")


def _evaluate_job_ad(job_ad):
    """ evaluate one pre-selected job ad on its JobSpy fields, returning the evaluation, or
        None when a scrape.POST_FIELDS value is blank. The job ad is passed as the post, so
        no page is fetched.
    """
    try:
        validate_post(job_ad, job_ad["url"])
    except ScrapeError:
        print(f"  skipping {job_ad['url']}: JobSpy returned no usable title, company, "
              "location or description")
        return None
    return evaluate_job(job_ad["url"], post=job_ad)


def add_discovery_arguments(parser):
    """ register the discovery-pipeline flags shared by discover_jobs.py and propose_jobs.py
        on an argparse parser. Defined here, next to discover_jobs(), so a new pipeline knob
        reaches both entrypoints from one edit.
    """
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS,
                        help="max JobSpy results to keep per query")
    parser.add_argument("--force", action="store_true",
                        help="ignore the cached search queries and recompile them")
    parser.add_argument("--debug", action="store_true", help="print intermediate search details")


def discover_jobs(evaluate=False, limit=None, max_results_per_query=DEFAULT_MAX_RESULTS,
                   force_queries=False, preselect_job_ads=True, debug=False):
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

    job_ads = discover_job_ads(cache, max_results_per_query, debug)
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
        print("\nRun with --evaluate to score these (costs LLM, Tavily address-search and ORS calls per url).")
        return to_run

    results = []
    for job_ad in to_run:
        try:
            evaluation = _evaluate_job_ad(job_ad)
        except Exception as e:
            print(f"  skipping {job_ad['url']}: {e}")
            continue
        if evaluation is not None:
            results.append(evaluation)
    return results
