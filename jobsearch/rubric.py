"""
The compatibility rubric: a set of weighted, regex-checkable criteria derived once from
the candidate's resume + job preferences, then applied deterministically to many job
descriptions.

This module owns the rubric as an artifact end to end: drafting it (an agentic LLM loop
that validates each regex via the test_regex tool), a one-shot reflection/revision pass,
caching it to disk keyed by the resume/preferences content hashes, and applying it to a
job description with pure regex (no LLM). The LLM judgment that turns an applied rubric
into a 0-100 score lives in jobsearch.evaluation, not here.
"""

import json
import os
import re

from jobsearch.config import (
    read_resume, read_job_preferences, file_hash, extract_section,
    RESUME_PATH, JOB_PREFERENCES_PATH, DATA_DIR,
)
from jobsearch.llm import ask_json, ask_json_with_tools, EXTRACTION_MODEL_MAX_TOKENS, RUBRIC_MODEL

RUBRIC_PATH = os.path.join(DATA_DIR, "compatibility_rubric.json")


def test_regex(pattern, test_text):
    """ tool: test a regex pattern (case-insensitive) against a piece of sample text """
    try:
        matches = re.findall(pattern, test_text, re.IGNORECASE)
    except re.error as e:
        return {"error": str(e)}
    return {"match_count": len(matches), "matches": matches}


TOOLS = {
    "test_regex": {
        "spec": {
            "type": "function",
            "function": {
                "name": "test_regex",
                "description": (
                    "Test a case-insensitive regex pattern against a sample piece of text. "
                    "Use this to validate that a candidate pattern matches text it should "
                    "match and does not match text it shouldn't, before finalizing it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "the regex pattern to test"},
                        "test_text": {"type": "string", "description": "sample text to test the pattern against"},
                    },
                    "required": ["pattern", "test_text"],
                },
            },
        },
        "impl": test_regex,
    },
}


def draft_rubric(resume, preferences):
    """ agentically propose + regex-test criteria that detect resume/preference matches in a job ad """
    return ask_json_with_tools(
        "You are building a reusable scoring rubric to evaluate future job postings against "
        "a specific candidate's resume and job preferences. This rubric will be applied to "
        "many job descriptions later using only regex matching, with no further LLM "
        "involvement, so patterns must be well-tested and precise.\n\n"
        f"Candidate resume:\n{resume}\n\n"
        f"Candidate job preferences:\n{preferences}\n\n"
        "Identify the 6-10 most impactful, concrete, checkable criteria (skills, "
        "technologies, role types, dealbreakers, must-haves) that indicate whether a job "
        "posting matches this candidate - prioritize the ones explicitly called out in the "
        "preferences over minor resume details. Every criterion must be directly traceable "
        "to specific text in the resume or preferences above - do not invent domains, "
        "technologies, or preferences that are not explicitly present in that text, even if "
        "they seem like a plausible fit. For each criterion, write a regex pattern "
        "that will reliably detect mentions of it in a job posting's free-text description. "
        "Use the test_regex tool to validate each pattern with a single test call per "
        "pattern, passing one short piece of sample text that contains both a phrasing that "
        "SHOULD match and a superficially similar phrasing that should NOT match, so you can "
        "confirm precision in one call instead of two.\n\n"
        "When you are done testing, respond with only a JSON object:\n"
        '{"criteria": [{"name": <short label>, "pattern": <regex pattern string, no inline '
        'flags needed - matching is case-insensitive>, "type": "requirement_match" | '
        '"candidate_strength" | "dealbreaker", "weight": <integer 1-5 importance>, '
        '"rationale": <why this criterion matters, one sentence>}, ...]}',
        tools=TOOLS,
        tool_names=["test_regex"],
        max_tokens=EXTRACTION_MODEL_MAX_TOKENS,
        max_iterations=30,
        model=RUBRIC_MODEL,
    )


def reflect_on_rubric(resume, preferences, draft):
    """ single-shot critique/revision pass over the drafted rubric, before it gets cached """
    return ask_json(
        "You are reviewing a draft scoring rubric for quality before it gets cached and used "
        "to evaluate many future job postings via regex matching alone.\n\n"
        f"Candidate resume:\n{resume}\n\n"
        f"Candidate job preferences:\n{preferences}\n\n"
        f"Draft rubric:\n{json.dumps(draft, indent=2)}\n\n"
        "Check for, in this order of priority:\n"
        "1. Hallucinated criteria: for each criterion, find the specific phrase in the "
        "resume or preferences text above that justifies it. If you cannot point to such a "
        "phrase, DELETE the criterion, even if it seems like a reasonable inference.\n"
        "2. Redundant/overlapping criteria - merge them.\n"
        "3. Missing criteria that are explicitly stated in the resume/preferences but not "
        "yet covered.\n"
        "4. Regex patterns that are too broad (would match unrelated text) or too narrow "
        "(would miss common phrasings) - you cannot test patterns here, so fix anything "
        "that looks wrong by inspection.\n"
        "5. Incorrect weight/type assignments.\n\n"
        "Respond with only a JSON object in the exact same schema as the draft rubric, "
        'containing your revised, final criteria list: {"criteria": [...]}',
        max_tokens=EXTRACTION_MODEL_MAX_TOKENS,
        model=RUBRIC_MODEL,
    )


def compile_rubric():
    """ agentically (re)build the compatibility rubric from resume.md + job_preferences.md """
    resume = read_resume()
    preferences = read_job_preferences()

    draft = draft_rubric(resume, preferences)
    reviewed = reflect_on_rubric(resume, preferences, draft)

    rubric = {
        "resume_hash": file_hash(RESUME_PATH),
        "preferences_hash": file_hash(JOB_PREFERENCES_PATH),
        "criteria": reviewed["criteria"],
        "scoring_guidance": extract_section(preferences, "Scoring Notes"),
    }
    with open(RUBRIC_PATH, "w") as f:
        json.dump(rubric, f, indent=2)
    return rubric


def load_rubric():
    """ return the rubric cached on disk, or None if RUBRIC_PATH is absent.

        Callers that require one fixed rubric for a sequence of evaluations, such as the eval
        harness, use this with rubric_is_stale() in place of load_or_compile_rubric().
    """
    if not os.path.exists(RUBRIC_PATH):
        return None
    with open(RUBRIC_PATH) as f:
        return json.load(f)


def rubric_is_stale(rubric):
    """ True if resume.md/job_preferences.md have changed since rubric was compiled """
    return (
        rubric.get("resume_hash") != file_hash(RESUME_PATH)
        or rubric.get("preferences_hash") != file_hash(JOB_PREFERENCES_PATH)
    )


def load_or_compile_rubric():
    """ return the cached rubric if resume.md/job_preferences.md haven't changed, else recompile """
    cached = load_rubric()
    if cached is not None and not rubric_is_stale(cached):
        return cached
    return compile_rubric()


def evaluate_rubric(rubric, description):
    """ deterministically check which rubric criteria match a job description, via regex.
        each criterion gets a "score": +weight if a requirement_match/candidate_strength
        criterion matched, -weight if a dealbreaker matched, 0 otherwise (unmet requirement
        or dealbreaker correctly absent).
    """
    evaluated = []
    for criterion in rubric["criteria"]:
        matched = bool(re.search(criterion["pattern"], description, re.IGNORECASE))
        if matched:
            score = -criterion["weight"] if criterion["type"] == "dealbreaker" else criterion["weight"]
        else:
            score = 0
        evaluated.append({**criterion, "matched": matched, "score": score})
    return evaluated
