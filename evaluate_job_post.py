"""
Evaluate a job post for fitness to my criteria: compatibility with my experience and ambitions, commute time
"""

import hashlib
import json
import os
import re
import sys

import requests
from tavily import TavilyClient
import aisuite as ai

from dotenv import load_dotenv

load_dotenv()

ORS_API_KEY = os.environ["ORS_API_KEY"]
HOME_ADDRESS = os.environ["HOME_ADDRESS"]
ORS_BASE_URL = "https://api.openrouteservice.org"
EXTRACTION_MODEL = "anthropic:claude-haiku-4-5-20251001"
FULLY_REMOTE = "Fully Remote"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
RESUME_PATH = os.path.join(DATA_DIR, "resume.md")
JOB_PREFERENCES_PATH = os.path.join(DATA_DIR, "job_preferences.md")
RUBRIC_PATH = os.path.join(DATA_DIR, "compatibility_rubric.json")


def _parse_json_reply(content):
    """ extract JSON from a model reply that may include a code fence and/or leading prose """
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
    if fence_match:
        content = fence_match.group(1)
    else:
        brace_match = re.search(r"\{.*\}", content, re.DOTALL)
        if brace_match:
            content = brace_match.group(0)
    return json.loads(content.strip())


def _ask_json(prompt, max_tokens=1024):
    """ send a prompt to the extraction model and parse its JSON reply """
    client = ai.Client()
    messages = [{"role": "user", "content": prompt}]
    response = client.chat.completions.create(
        model=EXTRACTION_MODEL,
        messages=messages,
        max_tokens=max_tokens,
    )
    return _parse_json_reply(response.choices[0].message.content)


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


def _ask_json_with_tools(prompt, tool_names, max_tokens=1024, max_iterations=10):
    """ run an agentic tool-call loop, letting the model call the given tools before answering """
    client = ai.Client()
    tool_specs = [TOOLS[name]["spec"] for name in tool_names]
    messages = [{"role": "user", "content": prompt}]

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=EXTRACTION_MODEL,
            messages=messages,
            tools=tool_specs,
            max_tokens=max_tokens,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            return _parse_json_reply(message.content)

        messages.append({"role": "assistant", "content": message.content, "tool_calls": message.tool_calls})
        for tool_call in message.tool_calls:
            args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
            result = TOOLS[tool_call.function.name]["impl"](**args)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(result)})

    raise RuntimeError("tool-call loop did not converge within max_iterations")


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
        max_tokens=4096,
    )


def classify_location(company, location):
    """ decide whether location is already a full address, a generic place name, or remote """
    return _ask_json(
        "You are given a job posting's company name and its raw location text.\n"
        f"Company: {company}\n"
        f"Location: {location}\n\n"
        'Respond with only a JSON object with keys "status" and "address":\n'
        '"status" must hold one of the following 3 options:\n'
        '- "remote": the job is fully remote, no office attendance is required. Set "address" to null.\n'
        '- "full_address": the location text already contains a specific street-level '
        'address (street name and number), not just a city/region/country. Set '
        '"address" to that address.\n'
        '- "generic": the location text only names a city/region/country without a '
        'specific street address. Set "address" to null.\n',
        max_tokens=256,
    )


def search_office_address(company, location):
    """ search the web for the company's office address, using location as a discriminator """
    # LinkedIn appends "Metropolitan Area" to location text when it lacks a precise city;
    # it's noise for search (not a real geographic term) and dilutes results toward
    # unrelated same-named companies rather than helping narrow down the right one.
    clean_location = re.sub(r"\s*Metropolitan Area\s*$", "", location, flags=re.IGNORECASE)

    tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    results = tavily.search(f"{company} headquarters office address {clean_location}", max_results=5)
    return "\n\n".join(f"{r['title']}\n{r['content']}" for r in results["results"])


def resolve_office_address(company, location, search_context):
    """ pick the office address matching location out of the search results """
    result = _ask_json(
        f"Company: {company}\n"
        f"Known location (city/region) - use this to pick the right office if the "
        f"company has multiple locations: {location}\n\n"
        f"Search results:\n{search_context}\n\n"
        "Find the company's full street-level office address that matches the given "
        'location. Respond with only a JSON object: {"address": <full address string, '
        "or null if it can't be determined from the search results>}.",
        max_tokens=256,
    )
    return result["address"]


def figure_address(company, location):
    """ return a full street address for company/location, or FULLY_REMOTE if no office applies """
    classification = classify_location(company, location)

    if classification["status"] == "remote":
        return FULLY_REMOTE
    if classification["status"] == "full_address" and classification["address"]:
        return classification["address"]

    search_context = search_office_address(company, location)
    return resolve_office_address(company, location, search_context)


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
        tool_names=["test_regex"],
        max_tokens=4096,
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
        max_tokens=4096,
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
    """ deterministically check which rubric criteria match a job description, via regex """
    evaluated = []
    for criterion in rubric["criteria"]:
        matched = bool(re.search(criterion["pattern"], description, re.IGNORECASE))
        evaluated.append({**criterion, "matched": matched})
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
        "Rubric evaluation (regex-verified against the ad text above, do not contradict it):\n"
        f"{json.dumps(evaluated_criteria, indent=2)}\n\n"
        "Using the rubric evaluation as grounding for factual claims about what the ad does "
        "or doesn't mention, produce a final compatibility judgment. Weigh matched "
        "requirement_match/candidate_strength criteria positively (scaled by weight), "
        "matched dealbreaker criteria very negatively, and note unmatched criteria only if "
        "they were important (high weight) requirement_matches.\n\n"
        'Respond with only a JSON object: {"compatibility_score": <integer 0-100>, '
        '"rationale": <explanation citing which matched/unmatched criteria drove the score>}.',
        max_tokens=1024,
    )
    return {**result, "criteria": evaluated_criteria}


def figure_days_on_office(description):
    """ return the required number of on-site office days per week (0-5) """
    result = _ask_json(
        "You are given a job posting's location text and full description. Determine "
        "how many days per week on-site office attendance is required.\n"
        f"Description:\n{description}\n\n"
        'Respond with only text representing a single integer 0-5.\n'
        "- 0 means fully remote, no office attendance required.\n"
        "- 5 means fully in-office / on-site every day.\n"
        "- For hybrid roles, use the number of required in-office days per week explicitly "
        'stated (e.g. "3 days a week", "hybrid 2 days/week").\n'
        "- if the job location is hybrid but no specific number of days is stated, use 4.\n"
        "- If nothing about remote/hybrid/on-site policy is mentioned at all, use 5 as the "
        "conservative default."
        "double check that your reply is text representing a single integer with no other added comment",
        max_tokens=256,
    )
    return result


def geocode_address(address):
    """ return (longitude, latitude) for a free-form address string """
    response = requests.get(
        f"{ORS_BASE_URL}/geocode/search",
        params={"api_key": ORS_API_KEY, "text": address, "size": 1},
        timeout=10,
    )
    response.raise_for_status()
    features = response.json()["features"]
    if not features:
        raise ValueError(f"could not geocode address: {address}")
    return features[0]["geometry"]["coordinates"]


def commute_route(address, profile="driving-car"):
    """ return (duration_minutes, distance_km) from HOME_ADDRESS to address """
    origin = geocode_address(HOME_ADDRESS)
    destination = geocode_address(address)

    response = requests.get(
        f"{ORS_BASE_URL}/v2/directions/{profile}",
        params={
            "api_key": ORS_API_KEY,
            "start": f"{origin[0]},{origin[1]}",
            "end": f"{destination[0]},{destination[1]}",
        },
        timeout=10,
    )
    response.raise_for_status()
    segment = response.json()["features"][0]["properties"]["segments"][0]
    return segment["duration"] / 60, segment["distance"] / 1000


def commute_time(address, profile="driving-car"):
    """ return commute time in minutes """
    duration, _ = commute_route(address, profile)
    return duration


def commute_score(company, location, description):
    """commute_score is the commute time for companies requiring 3 or 4 days from office.
       for fully in office, multiply by 1.5
       for <3 days on office, commute score is commute_time * days-on-office / 3.
       fully remote jobs have no commute, so their score is 0.
       returns {"score": float, "days_on_office": int, "address": str,
                "raw_minutes": float|None, "distance_km": float|None}
    """
    days_on_office = int(figure_days_on_office(description))

    if days_on_office <= 0:
        return {"score": 0, "days_on_office": days_on_office, "address": FULLY_REMOTE,
                "raw_minutes": None, "distance_km": None}

    address = figure_address(company, location)
    if address == FULLY_REMOTE:
        return {"score": 0, "days_on_office": days_on_office, "address": FULLY_REMOTE,
                "raw_minutes": None, "distance_km": None}
    if not address:
        return {"score": None, "days_on_office": days_on_office, "address": None,
                "raw_minutes": None, "distance_km": None}

    time, distance = commute_route(address)

    if days_on_office >= 5:
        score = time * 1.5
    elif days_on_office in (3, 4):
        score = time
    else:
        score = time * days_on_office / 3

    return {"score": score, "days_on_office": days_on_office, "address": address,
            "raw_minutes": time, "distance_km": distance}


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
