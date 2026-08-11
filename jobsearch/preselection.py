"""
Pre-selection: cut the L job ads discovery found down to the N worth fully evaluating,
using only data already available at discovery time.

MOCK MODULE. Every function below has its final signature and returns correctly shaped
output, but no real logic: deterministic steps are stubbed to trivial behaviour and the one
LLM call returns a fabricated reply. Each stub carries a "MOCK:" note stating what the real
implementation does.

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

Integration seams (not implemented here), all inside `jobsearch/discovery.py`:

  - `discover_jobs()` calls `preselect()` after `filter_new_job_ads()`, prints
    `format_preselection()` in place of `_print_job_ads()`, and evaluates
    `result["selected"]`.
  - its `except ScrapeError` block tries the survivor's `alternates` before
    `find_company_posting_url()`.
  - `discover_jobs()` resolves the rubric once, before discovery, and passes it in.
    `evaluate_job()` loads the rubric per job, so an unpinned recompile partway through a
    run would prescore against one rubric and score against another.
  - `jobspy_search()` retains the JobSpy columns it currently drops, and sets
    `linkedin_fetch_description=True`; without it there is no description to prescore.
  - `jobsearch/storage.py` needs a new read-only accessor supplying `known_job_openings`:
    `list_evaluated_job_openings() -> [(normalized_url, company, job_title,
    application_status)]`. `list_evaluated_urls()` returns URLs only.

`jobsearch/evaluation.py` is untouched.
"""

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

# job ad count past which the batch prompt approaches the model's input window
BUDGET_WARN_JOB_ADS = 250

# domain preference when collapsing duplicates: the company's own careers page carries the
# full ad, a source board is usually scrapeable, a re-poster carries a thin copy
SOURCE_BOARDS = {"linkedin.com", "indeed.com"}


# ---------------------------------------------------------------------------
# shapes
# ---------------------------------------------------------------------------

# INPUT - one job ad as discovery produces it, after jobspy_search() is widened to retain
# the JobSpy columns it currently discards:
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

_MOCK_JOB_AD = {
    "url": "https://example.invalid/jobs/1",
    "title": "Example Position",
    "company": "Example Company",
    "location": "Example City",
    "matched_queries": ["example query"],
    "description": "Example posting body.",
    "is_remote": False,
    "date_posted": "2026-01-01",
    "job_type": None,
    "job_level": None,
    "min_amount": None,
    "max_amount": None,
    "currency": None,
    "company_industry": None,
    "work_from_home_type": None,
}


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

        MOCK: lowercase + whitespace collapse only; the noise and abbreviation passes are
        not applied yet.
    """
    return " ".join(f"{company or ''} {title or ''}".lower().split())


def drop_stale(job_ads, max_age_days):
    """ drop job ads whose date_posted is older than max_age_days.
        returns (kept, dropped) where dropped holds _dropped() records.

        The only unconditional drop. Location and work mode play no part in pre-selection:
        remoteness is scored later by the commute modifier, on a posting whose days_on_office
        has been read from the full ad, rather than filtered here on JobSpy's is_remote flag.

        Domain is not grounds for a drop either - _AGGREGATOR_DOMAINS contains the boards
        discovery searches. Domain is used only to pick a duplicate collapse's survivor.

        MOCK: keeps everything.
    """
    return list(job_ads), []


def collapse_duplicates(job_ads):
    """ collapse job ads sharing a job_opening_key() to one, so a single opening at a single
        company appears once. The survivor is the url most likely to scrape into a full ad
        (own careers page > source board > re-poster); the losers' urls are attached to it as
        "alternates" for evaluate_job()'s ScrapeError fallback.
        returns (kept, dropped).

        MOCK: attaches a key and an empty alternates list, collapses nothing.
    """
    kept = [{**ad, "job_opening_key": job_opening_key(ad.get("company"), ad.get("title")),
             "alternates": []}
            for ad in job_ads]
    return kept, []


def drop_already_evaluated(job_ads, known_job_openings):
    """ drop job ads whose job_opening_key() was already evaluated. known_job_openings is the
        storage accessor's output: [(normalized_url, company, job_title, application_status)].
        returns (kept, dropped).

        application_status is ignored: having been evaluated is itself the drop rule, and a
        discarded opening says nothing about a different opening at the same company, so a
        discard never suppresses the employer.

        MOCK: keeps everything.
    """
    return list(job_ads), []


def prescore_job_ads(job_ads, rubric):
    """ annotate each job ad with the rubric's verdict on its full text, via
        rubric.evaluate_rubric(rubric, match_text(title, location, description)) - pure
        regex, no token budget, so the untruncated description is used.

        Adds "prescore" (signed sum of matched criterion weights) and "matched_criteria"
        ([name]). An annotation, never a filter: an unmatched criterion on thin ad text is
        evidence of thin text, not of a bad job.

        MOCK: zero score, no matched criteria.
    """
    return [{**ad, "prescore": 0, "matched_criteria": []} for ad in job_ads]


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

        MOCK: head truncation, the fallback path.
    """
    return (description or "")[:EXCERPT_CHARS]


def summarize_job_ad(job_ad, index):
    """ render one job ad as a prompt line: its integer id, the structured fields, the
        prescore annotation, and description_excerpt() of its description.

        MOCK: id and title only.
    """
    return f"[{index}] {job_ad.get('title')}"


def check_budget(job_ads):
    """ warn when the job ad count approaches the batch prompt's input window. Past this
        point the whole set no longer fits in one call and a ranked cut becomes necessary,
        which reintroduces ordering as a load-bearing step.

        MOCK: prints nothing.
    """
    return len(job_ads) <= BUDGET_WARN_JOB_ADS


def select_batch(job_ads, n, resume, preferences):
    """ the one LLM call: every job ad is presented with an integer id, alongside the resume
        and preferences; the reply names the N ids most likely to evaluate well.
        returns the raw reply: {"selected": [{"id": int, "reason": str}, ...]}.

        Not chunked - chunking makes the call count O(L).

        MOCK: picks the first n ids in order, which is exactly the behaviour pre-selection
        exists to replace.
    """
    return {"selected": [{"id": i, "reason": "mock selection"} for i in range(min(n, len(job_ads)))]}


def validate_selection(reply, job_ads, n):
    """ turn a raw select_batch() reply into exactly n job ads: drop ids outside the input
        range with a warning, collapse repeats, and backfill any shortfall by descending
        prescore. Mirrors discovery._validate_queries()'s guard against a non-compliant reply.
        returns (selected, dropped) where selected carries "selection_reason".

        MOCK: trusts the reply, no validation or backfill.
    """
    chosen = {entry["id"]: entry["reason"] for entry in reply["selected"]}
    selected = [{**job_ads[i], "selection_reason": reason} for i, reason in chosen.items()]
    dropped = [_dropped(ad, DROP_NOT_SELECTED, "not among the selected ids")
               for i, ad in enumerate(job_ads) if i not in chosen]
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

        MOCK: wires the stubs together; the shape is real, the selection is not.
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

        MOCK: stats line only.
    """
    return str(result["stats"])
