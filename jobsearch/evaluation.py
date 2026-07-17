"""
Evaluate a job posting end to end: orchestrate scrape -> commute -> compatibility ->
summary -> persistence (evaluate_job), plus the two LLM-judgment steps it depends on
(compatibility_score turns an applied rubric into a 0-100 score; summarize_evaluation
writes the works-well / does-not-work overview).

The rubric artifact itself (drafting, caching, regex application) lives in
jobsearch.rubric; content acquisition lives in jobsearch.scrape.
"""

import json

from jobsearch import storage
from jobsearch.config import FULLY_REMOTE
from jobsearch.commute import commute_score
from jobsearch.llm import ask_json
from jobsearch.rubric import load_or_compile_rubric, evaluate_rubric, match_text
from jobsearch.scrape import scrape_post


def compatibility_score(job_title, company, location, description, rubric=None):
    """ score 0-100 how well a job posting matches the candidate, using the cached rubric.
        returns {"compatibility_score": int, "rationale": str, "criteria": [...evaluated rubric criteria]}

        If no rubric is provided, the cached rubric will be checked for staleness and recompiled if needed.
    """
    rubric = load_or_compile_rubric() if rubric is None else rubric
    evaluated_criteria = evaluate_rubric(rubric, match_text(job_title, location, description))
    scoring_guidance = rubric.get("scoring_guidance")
    guidance_block = f"\nAdditional scoring guidance from the candidate:\n{scoring_guidance}\n" if scoring_guidance else ""

    result = ask_json(
        f"Job title: {job_title}\n"
        f"Company: {company}\n"
        f"Description:\n{description}\n\n"
        "Rubric evaluation (regex-verified against the ad text above, do not contradict it). "
        "Each matched criterion carries a signed 'score': positive weights are things the "
        "candidate wants (a preferred role, skill or field), negative weights are things the "
        "candidate wants to avoid (a large negative is close to disqualifying). An unmatched "
        "criterion scores 0. 'type' (role/skill/field/location) is the category the criterion "
        "belongs to:\n"
        f"{json.dumps(evaluated_criteria, indent=2)}\n"
        f"{guidance_block}\n"
        "Using the rubric evaluation as grounding for factual claims about what the ad does "
        "or doesn't mention, produce a final compatibility judgment. Weigh criteria by their "
        "signed 'score', let negative scores pull the judgment down, note an unmatched "
        "criterion only if a strongly positive one is missing, and apply the additional "
        "scoring guidance above if any was given.\n\n"
        'Respond with only a JSON object: {"compatibility_score": <integer 0-100>, '
        '"rationale": <explanation citing which matched/unmatched criteria drove the score>}.',
        max_tokens=1024,
    )
    return {**result, "criteria": evaluated_criteria}


def summarize_evaluation(job, commute, compatibility):
    """ produce a short "what works / what doesn't" overview grounded in the commute + rubric data """
    if commute["address"] == FULLY_REMOTE:
        commute_context = "Fully remote - no commute."
    elif commute["address"] is None:
        commute_context = (
            f"Could not determine the office location from the posting "
            f"({commute['days_on_office']} required in-office days/week) - commute unknown."
        )
    else:
        commute_context = (
            f"{commute['score']:.1f}-minute weighted commute score "
            f"({commute['days_on_office']} required in-office days/week, "
            f"{commute['distance_km']:.1f} km to {commute['address']}, "
            f"{commute['raw_minutes']:.1f} min one-way)."
        )

    return ask_json(
        f"Job: {job['job_title']} at {job['company']}\n\n"
        f"Commute: {commute_context}\n\n"
        f"Compatibility score: {compatibility['compatibility_score']}/100\n"
        f"Compatibility rationale: {compatibility['rationale']}\n"
        f"Rubric criteria evaluated:\n{json.dumps(compatibility['criteria'], indent=2)}\n\n"
        "Write a concise overview of this opportunity for the candidate, covering both the "
        "commute burden and the resume/preferences fit. Ground every claim in the data "
        "above - do not speculate about anything not stated there.\n\n"
        'Respond with only a JSON object: {"works_well": <string, 1-3 short points '
        'separated by "; ">, "does_not_work": <string, same format>}',
        max_tokens=512,
    )


def _print_evaluation(evaluation, cached):
    """ print an evaluation dict (as returned by storage.get_evaluation) in a consistent
        format, whether it was just computed or served from the cache
    """
    suffix = f" (cached from {evaluation['evaluated_at']})" if cached else ""
    print(f"Evaluating Position: {evaluation['job_title']} at {evaluation['company']}{suffix}")

    if evaluation["commute_score"] is None:
        print(f"Commute score: unknown ({evaluation['days_on_office']} days/week, "
              f"address not found)")
    else:
        print(f"Commute score: {evaluation['commute_score']:.1f} min "
              f"({evaluation['days_on_office']} days/week, {evaluation['commute_address']})")

    print(f"Compatibility score: {evaluation['compatibility_score']}/100")
    print("Works well:", evaluation["works_well"])
    print("Does not work:", evaluation["does_not_work"])

    print("Reviewed:", "yes" if evaluation["reviewed"] else "no")
    status_line = f"Application status: {evaluation['application_status']}"
    if evaluation["status_reason"]:
        status_line += f" (reason: {evaluation['status_reason']})"
    print(status_line)
    if evaluation["notes"]:
        print("Notes:", evaluation["notes"])


def evaluate_job(url, force=False):
    """ scrape a job posting and produce a full evaluation: commute, compatibility, overview.
        returns a saved evaluation instead of re-running the pipeline if one already exists
        for this url and the compatibility rubric hasn't changed since, unless force=True.
    """
    rubric = load_or_compile_rubric()
    rubric_hash = storage.rubric_content_hash(rubric)

    if not force:
        existing = storage.get_evaluation(url)
        if existing is not None and existing["rubric_hash"] == rubric_hash:
            _print_evaluation(existing, cached=True)
            return existing

    job = scrape_post(url)
    commute = commute_score(job["company"], job["location"], job["description"])
    compatibility = compatibility_score(job["job_title"], job["company"], job["location"],
                                        job["description"], rubric=rubric)
    overview = summarize_evaluation(job, commute, compatibility)

    storage.save_evaluation(url, rubric_hash, job, commute, compatibility, overview)
    result = storage.get_evaluation(url)
    _print_evaluation(result, cached=False)
    return result
