"""
Evaluate a job post for fitness to my criteria: compatibility with my experience and ambitions, commute time
"""

import hashlib
import json
import os
import re
import sys

from tavily import TavilyClient
from dotenv import load_dotenv

from llm import _ask_json, _ask_json_with_tools
from commute import commute_score, FULLY_REMOTE

load_dotenv()

EXTRACTION_MODEL_MAX_TOKENS = 4096
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
RESUME_PATH = os.path.join(DATA_DIR, "resume.md")
JOB_PREFERENCES_PATH = os.path.join(DATA_DIR, "job_preferences.md")
RUBRIC_PATH = os.path.join(DATA_DIR, "compatibility_rubric.json")


def read_resume():
    """ return the candidate's resume/CV as markdown text """
    with open(RESUME_PATH) as f:
        return f.read()


def read_job_preferences():
    """ return the candidate's job preferences as markdown text """
    with open(JOB_PREFERENCES_PATH) as f:
        return f.read()


def _file_hash(path):
    """ sha256 hex digest of a file's contents, used to detect resume/preferences changes """
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


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


def scrape_post(url):
    """given a web address with a job post, extract job title, company, location relevant data and description"""
    tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    result = tavily.extract(url, format="text")
    if not result["results"]:
        raise ValueError(f"could not extract content from: {url}")
    page_text = result["results"][0]["raw_content"]

    return _ask_json(
        "Extract the following fields from this job posting page as JSON, "
        "with exactly these keys: job_title, company, location, description. "
        "location should contain any address/city/office info found on the page. "
        "Description should collect the full job and company description, including the remote policy information available."
        "Respond with only the JSON object, no other text.\n\n"
        f"{page_text}",
        max_tokens=EXTRACTION_MODEL_MAX_TOKENS,
    )


def draft_rubric(resume, preferences):
    """ agentically propose + regex-test criteria that detect resume/preference matches in a job ad """
    return _ask_json_with_tools(
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
    )


def reflect_on_rubric(resume, preferences, draft):
    """ single-shot critique/revision pass over the drafted rubric, before it gets cached """
    return _ask_json(
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
    )


def compile_rubric():
    """ agentically (re)build the compatibility rubric from resume.md + job_preferences.md """
    resume = read_resume()
    preferences = read_job_preferences()

    draft = draft_rubric(resume, preferences)
    reviewed = reflect_on_rubric(resume, preferences, draft)

    rubric = {
        "resume_hash": _file_hash(RESUME_PATH),
        "preferences_hash": _file_hash(JOB_PREFERENCES_PATH),
        "criteria": reviewed["criteria"],
    }
    with open(RUBRIC_PATH, "w") as f:
        json.dump(rubric, f, indent=2)
    return rubric


def load_or_compile_rubric():
    """ return the cached rubric if resume.md/job_preferences.md haven't changed, else recompile """
    if os.path.exists(RUBRIC_PATH):
        with open(RUBRIC_PATH) as f:
            cached = json.load(f)
        if (
            cached.get("resume_hash") == _file_hash(RESUME_PATH)
            and cached.get("preferences_hash") == _file_hash(JOB_PREFERENCES_PATH)
        ):
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


def compatibility_score(job_title, company, description):
    """ score 0-100 how well a job posting matches the candidate, using the cached rubric.
        returns {"compatibility_score": int, "rationale": str, "criteria": [...evaluated rubric criteria]}
    """
    rubric = load_or_compile_rubric()
    evaluated_criteria = evaluate_rubric(rubric, description)

    result = _ask_json(
        f"Job title: {job_title}\n"
        f"Company: {company}\n"
        f"Description:\n{description}\n\n"
        "Rubric evaluation (regex-verified against the ad text above, do not contradict it). "
        "Each criterion carries a 'score': positive (its weight) if a matched "
        "requirement_match/candidate_strength, negative (its weight) if a matched dealbreaker, "
        "0 if unmatched:\n"
        f"{json.dumps(evaluated_criteria, indent=2)}\n\n"
        "Using the rubric evaluation as grounding for factual claims about what the ad does "
        "or doesn't mention, produce a final compatibility judgment. Weigh criteria by their "
        "'score', and note unmatched criteria only if they were important (high weight) "
        "requirement_matches.\n\n"
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

    return _ask_json(
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


def evaluate_job(url):
    """ scrape a job posting and produce a full evaluation: commute, compatibility, overview """
    job = scrape_post(url)
    print(f"Evaluating Position: {job['job_title']} at {job['company']}")

    commute = commute_score(job["company"], job["location"], job["description"])
    if commute["score"] is None:
        print(f"Commute score: unknown ({commute['days_on_office']} days/week, address not found)")
    else:
        print(f"Commute score: {commute['score']:.1f} min "
              f"({commute['days_on_office']} days/week, {commute['address']})")

    compatibility = compatibility_score(job["job_title"], job["company"], job["description"])
    print(f"Compatibility score: {compatibility['compatibility_score']}/100")

    overview = summarize_evaluation(job, commute, compatibility)
    print("Works well:", overview["works_well"])
    print("Does not work:", overview["does_not_work"])

    return {
        "job_title": job["job_title"],
        "company": job["company"],
        "commute_score": commute["score"],
        "compatibility_score": compatibility["compatibility_score"],
        "works_well": overview["works_well"],
        "does_not_work": overview["does_not_work"],
    }


if __name__ == "__main__":
    evaluate_job(sys.argv[1])
