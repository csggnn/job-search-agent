"""
Job-posting content acquisition: fetch a posting URL and extract its structured fields
(job_title, company, location, description). This is the seam that discovery's
company-site fallback hooks into via ScrapeError.
"""

from tavily import TavilyClient

from jobsearch import config
from jobsearch.llm import ask_json, EXTRACTION_MODEL_MAX_TOKENS


class ScrapeError(ValueError):
    """ raised when a job posting's content could not be extracted from a URL - callers with
        other metadata about the posting (e.g. discover_jobs.py) can catch this specifically to
        try an alternate source rather than a generic pipeline failure
    """


def scrape_post(url):
    """given a web address with a job post, extract job title, company, location relevant data and description"""
    tavily = TavilyClient(api_key=config.require_env("TAVILY_API_KEY"))
    result = tavily.extract(url, format="text")
    if not result["results"]:
        raise ScrapeError(f"could not extract content from: {url}")
    page_text = result["results"][0]["raw_content"]

    return ask_json(
        "Extract the following fields from this job posting page as JSON, "
        "with exactly these keys: job_title, company, location, description. "
        "location should contain any address/city/office info found on the page. "
        "Description should collect the full job and company description, including the remote policy information available."
        "Respond with only the JSON object, no other text.\n\n"
        f"{page_text}",
        max_tokens=EXTRACTION_MODEL_MAX_TOKENS,
    )
