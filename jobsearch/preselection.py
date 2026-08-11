"""
Pre-selection: cut the L job ads discovery found down to the N worth fully evaluating,
using only data already available at discovery time.

Vocabulary: a *job ad* is one posting as discovery found it, a thin record keyed by url. A
*job opening* is the position an ad advertises - several ads at several urls can advertise
one job opening, which is what collapse_duplicates() reduces. "Candidate" is reserved
throughout the codebase for the person whose resume and preferences the pipeline scores
against.

Two stages, in `preselect()`:

  1. deterministic pass - staleness drop, duplicate collapse, rubric prescore. Free, no LLM,
     works at any L.

Location and work mode are deliberately absent. Remoteness reaches the score later, through
ranking's commute modifier, on a posting whose office and in-office days have been resolved
from the full ad - not through a pre-selection filter on JobSpy's is_remote flag, which
would impose a constraint the job spec does not state.
  2. one LLM call - every survivor is presented with a short integer id; the reply names the
     N selected ids.

The module opens no database and reads no files: the rubric, resume, preferences and the
set of already-evaluated job openings are all passed in. That keeps the deterministic stage
unit-testable offline, and keeps storage access owned by the caller.

Integration seams, all inside `jobsearch/discovery.py`:

  - `discover_jobs()` calls `preselect()` after `filter_new_job_ads()`, prints
    `format_preselection()` in place of `_print_job_ads()`, and evaluates
    `result["selected"]`.
  - its `except ScrapeError` block tries the survivor's `alternates` before
    `find_company_posting_url()`.
  - `discover_jobs()` resolves the rubric once, before discovery, and passes it in.
    `evaluate_job()` loads the rubric per job, so an unpinned recompile partway through a
    run would prescore against one rubric and score against another.
  - `jobspy_search()` retains the JobSpy columns it would otherwise drop, and sets
    `linkedin_fetch_description=True`; without it there is no description to prescore.
  - `jobsearch/storage.py`'s `list_evaluated_job_openings()` supplies
    `known_job_openings`; `list_evaluated_urls()` returns URLs only.

`jobsearch/evaluation.py` is untouched.
"""

import re
from datetime import date
from urllib.parse import urlsplit

from jobsearch.llm import ask_json
from jobsearch.rubric import evaluate_rubric, match_text

# stage tags recorded on every dropped job ad, so a listing can report why each one went
DROP_STALE = "stale"
DROP_DUPLICATE = "duplicate"
DROP_EVALUATED = "already_evaluated"
DROP_NOT_SELECTED = "not_selected"

# default number of job ads pre-selection hands to evaluation; each one costs a Tavily
# extract, 3-5 LLM calls and up to 3 ORS calls downstream
DEFAULT_N = 10

# description characters kept per job ad in the batch prompt, measured from the start of
# the anchored window rather than the start of the ad. The untruncated text is already
# consumed for free by the rubric prescore.
EXCERPT_CHARS = 900

# job ads older than this are dropped outright; should eventually become a user parameter
MAX_AGE_DAYS = 45

# Anchors locating the substantive middle of a job ad. Measured over evals/ads/: a
# requirements anchor appears in 7/7 ads at 21-79% of the way in, a responsibilities anchor
# in 6/7 at 11-43%, and an offer/benefits anchor in 4/7 - three of them past 76%, one false
# positive at 8% inside a company blurb, which is why TAIL_MIN_POSITION guards the tail cut.
# Headings appear in 0/7 ads and bullets in only 4/7, so neither can anchor the window.
SECTION_START_PATTERN = (
    r"responsibilit|what you.{0,5}ll do|your role|the role|your mission|missions|functie|"
    r"requirement|qualification|what we.{0,10}looking for|your profile|we expect|profiel|profil"
)
SECTION_TAIL_PATTERN = (
    r"we offer|what we offer|benefits|our offer|wij bieden|nous offrons|equal opportunit|perks"
)
TAIL_MIN_POSITION = 0.6

# Title noise the job opening key removes: gender markers boards append, and seniority
# abbreviations. Neither can merge two genuinely distinct openings. Location suffixes are
# deliberately kept - the same role in two cities is two openings with different commutes.
TITLE_NOISE_PATTERN = r"\((?:m|v|h|f|d|w|x)[/|]\S*\)"
TITLE_ABBREVIATIONS = {"sr": "senior", "snr": "senior", "jr": "junior"}
# punctuation stripped off a title word before it is looked up in TITLE_ABBREVIATIONS, so
# "Sr." and "Sr" normalize alike
TITLE_PUNCTUATION = ".,;:"

# job ad count past which the batch prompt approaches the model's input window
BUDGET_WARN_JOB_ADS = 250

# domain preference when collapsing duplicates: the company's own careers page carries the
# full ad, a source board is usually scrapeable, a re-poster carries a thin copy
SOURCE_BOARDS = {"linkedin.com", "indeed.com"}

# Third-party re-posters and aggregators, which tend to carry a thin or stale copy of a
# posting. Owned here because this module ranks a duplicate collapse's urls by source;
# jobsearch/discovery.py imports it for the same reason in its scrape fallback search.
AGGREGATOR_DOMAINS = SOURCE_BOARDS | {
    "glassdoor.com", "jobleads.com", "bebee.com", "monster.com", "jobrapido.com",
    "jooble.org", "careerjet.com", "simplyhired.com", "ziprecruiter.com", "talent.com",
    "adzuna.com", "neuvoo.com", "jobsora.com", "trabajo.org", "whatjobs.com",
    "learn4good.com", "receptix.com",
}

# max_tokens for the batch call: one id + one short reason per selected job ad
SELECTION_MAX_TOKENS = 2048


# ---------------------------------------------------------------------------
# shapes
# ---------------------------------------------------------------------------

# INPUT - one job ad as discovery produces it, from the JobSpy columns jobspy_search()
# retains:
#
#   {"url": str, "title": str|None, "company": str|None, "location": str|None,
#    "matched_queries": [str], "description": str|None, "is_remote": bool|None,
#    "date_posted": str|None, "job_type": str|None, "job_level": str|None,
#    "min_amount": float|None, "max_amount": float|None, "currency": str|None,
#    "company_industry": str|None, "work_from_home_type": str|None}
#
# Stage 1 adds: "job_opening_key" (normalized company+title), "alternates" ([url]),
# "prescore" (int), "matched_criteria" ([str]). Stage 2 adds "selection_reason" (str) to
# the selected.
#
# OUTPUT - see preselect().


def _dropped(job_ad, stage, reason):
    """ the record kept for every job ad that does not reach evaluation """
    return {"job_ad": job_ad, "stage": stage, "reason": reason}


# ---------------------------------------------------------------------------
# stage 1: deterministic pass
# ---------------------------------------------------------------------------

def job_opening_key(company, title):
    """ the normalized (company, title) identity of the job opening an ad advertises, used to
        collapse the several ads advertising one opening. returns a single string key.

        Lowercases, collapses whitespace, strips TITLE_NOISE_PATTERN and expands
        TITLE_ABBREVIATIONS. Location suffixes are left in place: the same role advertised
        in two cities is two openings with different commutes, not a duplicate.
    """
    text = re.sub(TITLE_NOISE_PATTERN, " ", f"{company or ''} {title or ''}", flags=re.IGNORECASE)
    words = []
    for word in text.lower().split():
        stripped = word.strip(TITLE_PUNCTUATION)
        if stripped:
            words.append(TITLE_ABBREVIATIONS.get(stripped, stripped))
    return " ".join(words)


def _parse_date(value):
    """ the date part of a JobSpy date_posted cell (a date object or an ISO string), or None
        when it is absent or unparseable
    """
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def drop_stale(job_ads, max_age_days):
    """ drop job ads whose date_posted is older than max_age_days.
        returns (kept, dropped) where dropped holds _dropped() records.

        The only unconditional drop. Location and work mode play no part in pre-selection:
        remoteness is scored later by the commute modifier, on a posting whose days_on_office
        has been read from the full ad, rather than filtered here on JobSpy's is_remote flag.

        Domain is not grounds for a drop either - AGGREGATOR_DOMAINS contains the boards
        discovery searches. Domain is used only to pick a duplicate collapse's survivor.
    """
    today = date.today()
    kept, dropped = [], []
    for job_ad in job_ads:
        posted = _parse_date(job_ad.get("date_posted"))
        age_days = (today - posted).days if posted else None
        if age_days is not None and age_days > max_age_days:
            dropped.append(_dropped(
                job_ad, DROP_STALE,
                f"posted {age_days} days ago, past the {max_age_days}-day cutoff",
            ))
        else:
            kept.append(job_ad)
    return kept, dropped


def _source_rank(url):
    """ how likely a url is to scrape into a full ad: 0 for a domain no board is known to
        own (the company's own careers page), 1 for a source board, 2 for a re-poster
    """
    host = urlsplit(url or "").netloc.lower()

    def owned_by(domains):
        return any(host == domain or host.endswith("." + domain) for domain in domains)

    if owned_by(SOURCE_BOARDS):
        return 1
    if owned_by(AGGREGATOR_DOMAINS):
        return 2
    return 0


def collapse_duplicates(job_ads):
    """ collapse job ads sharing a job_opening_key() to one, so a single opening at a single
        company appears once. The survivor is the url most likely to scrape into a full ad
        (own careers page > source board > re-poster); the losers' urls are attached to it as
        "alternates" for evaluate_job()'s ScrapeError fallback.
        returns (kept, dropped).
    """
    groups = {}
    for job_ad in job_ads:
        groups.setdefault(job_opening_key(job_ad.get("company"), job_ad.get("title")),
                          []).append(job_ad)

    kept, dropped = [], []
    for key, group in groups.items():
        # min() is stable, so an equally ranked url loses to the one discovery found first
        survivor = min(group, key=lambda job_ad: _source_rank(job_ad.get("url")))
        losers = [job_ad for job_ad in group if job_ad is not survivor]
        kept.append({**survivor,
                     "job_opening_key": key,
                     "alternates": [job_ad["url"] for job_ad in losers]})
        dropped += [
            _dropped(job_ad, DROP_DUPLICATE, f"same job opening as {survivor['url']}")
            for job_ad in losers
        ]
    return kept, dropped


def drop_already_evaluated(job_ads, known_job_openings):
    """ drop job ads whose job_opening_key() was already evaluated. known_job_openings is the
        storage accessor's output: [(normalized_url, company, job_title, application_status)].
        returns (kept, dropped).

        application_status is ignored: having been evaluated is itself the drop rule, and a
        discarded opening says nothing about a different opening at the same company, so a
        discard never suppresses the employer.
    """
    known = {job_opening_key(company, title) for _, company, title, _ in known_job_openings}
    kept, dropped = [], []
    for job_ad in job_ads:
        key = job_opening_key(job_ad.get("company"), job_ad.get("title"))
        if key in known:
            dropped.append(_dropped(job_ad, DROP_EVALUATED,
                                    "this job opening already has a saved evaluation"))
        else:
            kept.append(job_ad)
    return kept, dropped


def prescore_job_ads(job_ads, rubric):
    """ annotate each job ad with the rubric's verdict on its full text, via
        rubric.evaluate_rubric(rubric, match_text(title, location, description)) - pure
        regex, no token budget, so the untruncated description is used.

        Adds "prescore" (signed sum of matched criterion weights) and "matched_criteria"
        ([name]). An annotation, never a filter: an unmatched criterion on thin ad text is
        evidence of thin text, not of a bad job.
    """
    scored = []
    for job_ad in job_ads:
        criteria = evaluate_rubric(rubric, match_text(job_ad.get("title"),
                                                      job_ad.get("location"),
                                                      job_ad.get("description")))
        scored.append({
            **job_ad,
            "prescore": sum(criterion["score"] for criterion in criteria),
            "matched_criteria": [c["name"] for c in criteria if c["matched"]],
        })
    return scored


# ---------------------------------------------------------------------------
# stage 2: one LLM call
# ---------------------------------------------------------------------------

def description_excerpt(description):
    """ the slice of a description worth spending prompt tokens on: the responsibilities and
        requirements middle, without the company blurb that opens an ad or the benefits
        boilerplate that closes it.

        Starts at the first SECTION_START_PATTERN match, or 0 when none matches. Ends at the
        last SECTION_TAIL_PATTERN match occurring past TAIL_MIN_POSITION of the text, or at
        the end. Caps the result at EXCERPT_CHARS.
    """
    text = description or ""
    head = re.search(SECTION_START_PATTERN, text, re.IGNORECASE)
    start = head.start() if head else 0

    end = len(text)
    tail_guard = TAIL_MIN_POSITION * len(text)
    for match in re.finditer(SECTION_TAIL_PATTERN, text, re.IGNORECASE):
        if match.start() >= tail_guard and match.start() > start:
            end = match.start()

    return text[start:end][:EXCERPT_CHARS]


def summarize_job_ad(job_ad, index):
    """ render one job ad as a prompt line: its integer id, the structured fields, the
        prescore annotation, and description_excerpt() of its description.
    """
    matched = job_ad.get("matched_criteria") or []
    details = [
        f"work mode: {'remote' if job_ad.get('is_remote') else 'on-site/hybrid'}",
        f"posted: {job_ad.get('date_posted') or 'unknown'}",
    ]
    for field in ("job_type", "job_level", "company_industry"):
        if job_ad.get(field):
            details.append(f"{field.replace('_', ' ')}: {job_ad[field]}")
    if job_ad.get("min_amount") or job_ad.get("max_amount"):
        details.append(f"salary: {job_ad.get('min_amount')}-{job_ad.get('max_amount')} "
                       f"{job_ad.get('currency') or ''}".strip())

    return "\n".join([
        f"[{index}] {job_ad.get('title') or '(untitled)'} "
        f"at {job_ad.get('company') or '(unknown company)'} "
        f"({job_ad.get('location') or 'location unknown'})",
        f"  {' | '.join(details)}",
        f"  rubric prescore: {job_ad.get('prescore', 0)}; "
        f"matched criteria: {', '.join(matched) if matched else 'none'}",
        f"  {description_excerpt(job_ad.get('description'))}",
    ])


def check_budget(job_ads):
    """ warn when the job ad count approaches the batch prompt's input window. Past this
        point the whole set no longer fits in one call and a ranked cut becomes necessary,
        which reintroduces ordering as a load-bearing step.
    """
    if len(job_ads) > BUDGET_WARN_JOB_ADS:
        print(f"Warning: {len(job_ads)} job ads exceeds the {BUDGET_WARN_JOB_ADS} the batch "
              "prompt is budgeted for - the selection call may exceed the model's input window")
        return False
    return True


def select_batch(job_ads, n, resume, preferences):
    """ the one LLM call: every job ad is presented with an integer id, alongside the resume
        and preferences; the reply names the N ids most likely to evaluate well.
        returns the raw reply: {"selected": [{"id": int, "reason": str}, ...]}.

        Not chunked - chunking makes the call count O(L).
    """
    listing = "\n\n".join(summarize_job_ad(job_ad, i) for i, job_ad in enumerate(job_ads))

    return ask_json(
        "You are pre-selecting which job ads a candidate should spend a full, expensive "
        "evaluation on. Every ad below was found by a job-board search, and only some of "
        "them are worth reading in depth.\n\n"
        f"Candidate resume:\n{resume}\n\n"
        f"Candidate job preferences:\n{preferences}\n\n"
        f"Job ads, each with an integer id, its structured fields, the score a regex rubric "
        f"derived from the resume and preferences already gave it, and an excerpt of its "
        f"description:\n{listing}\n\n"
        f"Select the ids of the {n} job ads most likely to score well once fully evaluated "
        f"against the resume and preferences above. If fewer than {n} ads are listed, select "
        "all of them. Judge each ad on its own merit - the order they are listed in carries no "
        "meaning. The rubric prescore is evidence, not a verdict: a thin ad matches few "
        "criteria because it says little, not because the job is a poor fit. Do not select "
        "an ad that contradicts a stated disqualifier.\n\n"
        'Respond with only a JSON object: {"selected": [{"id": <int>, "reason": <one short '
        'sentence on why this ad is worth evaluating>}, ...]}',
        max_tokens=SELECTION_MAX_TOKENS,
    )


def validate_selection(reply, job_ads, n):
    """ turn a raw select_batch() reply into exactly n job ads: drop ids outside the input
        range with a warning, collapse repeats, and backfill any shortfall by descending
        prescore. Mirrors discovery._validate_queries()'s guard against a non-compliant reply.
        returns (selected, dropped) where selected carries "selection_reason".
    """
    if not job_ads:
        return [], []

    target = min(n, len(job_ads))
    chosen = {}
    for entry in (reply or {}).get("selected") or []:
        job_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(job_id, int) or isinstance(job_id, bool) \
                or not 0 <= job_id < len(job_ads):
            print(f"Warning: dropping selected id {job_id!r} - outside the "
                  f"0-{len(job_ads) - 1} range of job ads presented")
            continue
        if job_id in chosen or len(chosen) >= target:
            continue
        chosen[job_id] = entry.get("reason") or "selected by the batch pass"

    # a reply naming fewer ids than asked for still has to fill the evaluation budget; the
    # prescore is the only ordering available at this point that is not the discovery order
    # pre-selection exists to replace
    if len(chosen) < target:
        by_prescore = sorted((i for i in range(len(job_ads)) if i not in chosen),
                             key=lambda i: (-job_ads[i].get("prescore", 0), i))
        for i in by_prescore[:target - len(chosen)]:
            chosen[i] = "backfilled by rubric prescore: the batch pass named too few ids"

    selected = [{**job_ads[i], "selection_reason": reason} for i, reason in chosen.items()]
    dropped = [_dropped(job_ad, DROP_NOT_SELECTED, "not among the selected ids")
               for i, job_ad in enumerate(job_ads) if i not in chosen]
    return selected, dropped


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def preselect(job_ads, n=DEFAULT_N, rubric=None, resume=None, preferences=None,
              known_job_openings=()):
    """ run both stages and return

        {"selected": [job_ad + selection_reason, ...],   # <= n, in evaluation order
         "dropped":  [{"job_ad": {...}, "stage": <DROP_*>, "reason": str}, ...],
         "stats":    {"discovered": int, "after_stale": int, "after_dedup": int,
                      "after_known": int, "selected": int, "llm_calls": int}}

        Every discovered job ad appears exactly once across "selected" and "dropped", so a
        listing can account for all of them.
    """
    dropped = []

    kept, stale = drop_stale(job_ads, MAX_AGE_DAYS)
    dropped += stale
    after_stale = len(kept)

    kept, duplicates = collapse_duplicates(kept)
    dropped += duplicates
    after_dedup = len(kept)

    kept, known = drop_already_evaluated(kept, known_job_openings)
    dropped += known
    after_known = len(kept)

    kept = prescore_job_ads(kept, rubric)
    check_budget(kept)

    reply = select_batch(kept, n, resume, preferences)
    selected, not_selected = validate_selection(reply, kept, n)
    dropped += not_selected

    return {
        "selected": selected,
        "dropped": dropped,
        "stats": {
            "discovered": len(job_ads),
            "after_stale": after_stale,
            "after_dedup": after_dedup,
            "after_known": after_known,
            "selected": len(selected),
            "llm_calls": 1,
        },
    }


def format_preselection(result):
    """ render a preselect() result for the terminal: the selected N with their reason, then
        the dropped job ads grouped by stage, then the stats line. This is what makes the
        stage inspectable without paying for evaluation.
    """
    stats = result["stats"]
    lines = [f"\n{len(result['selected'])} job ad(s) selected for evaluation:\n"]
    for job_ad in result["selected"]:
        lines.append(f"- {job_ad.get('title') or '(untitled)'} "
                     f"at {job_ad.get('company') or '(unknown company)'} "
                     f"({job_ad.get('location') or 'location unknown'})")
        lines.append(f"  {job_ad['url']}")
        lines.append(f"  prescore {job_ad.get('prescore', 0)}: "
                     f"{', '.join(job_ad.get('matched_criteria') or []) or 'no criteria matched'}")
        lines.append(f"  why: {job_ad.get('selection_reason', '')}")
        if job_ad.get("alternates"):
            lines.append(f"  alternates: {', '.join(job_ad['alternates'])}")

    for stage in (DROP_STALE, DROP_DUPLICATE, DROP_EVALUATED, DROP_NOT_SELECTED):
        records = [r for r in result["dropped"] if r["stage"] == stage]
        if not records:
            continue
        lines.append(f"\n{len(records)} job ad(s) dropped - {stage}:\n")
        for record in records:
            job_ad = record["job_ad"]
            lines.append(f"- {job_ad.get('title') or '(untitled)'} "
                         f"at {job_ad.get('company') or '(unknown company)'}")
            lines.append(f"  {job_ad['url']}")
            lines.append(f"  {record['reason']}")

    lines.append(
        f"\n{stats['discovered']} discovered -> {stats['after_stale']} fresh -> "
        f"{stats['after_dedup']} distinct openings -> {stats['after_known']} not yet evaluated "
        f"-> {stats['selected']} selected ({stats['llm_calls']} LLM call)"
    )
    return "\n".join(lines)
