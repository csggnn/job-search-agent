"""
Job-posting content acquisition: fetch a posting URL and extract its structured fields
(job_title, company, location, description).
"""

from tavily import TavilyClient

from jobsearch import config
from jobsearch.llm import ask_json, EXTRACTION_MODEL_MAX_TOKENS

POST_FIELDS = ("job_title", "company", "location", "description")


class ScrapeError(ValueError):
    """ raised when a job posting's content could not be extracted from a URL - callers with
        other metadata about the posting (e.g. discover_jobs.py) can catch this specifically to
        try an alternate source rather than a generic pipeline failure
    """


def fetch_page_text(url):
    """ return the raw text of a job posting page. raises ScrapeError if it can't be fetched. """
    tavily = TavilyClient(api_key=config.require_env("TAVILY_API_KEY"))
    result = tavily.extract(url, format="text")
    if not result["results"]:
        raise ScrapeError(f"could not extract content from: {url}")
    return result["results"][0]["raw_content"]


def validate_post(post, source):
    """ raise ScrapeError unless post holds every POST_FIELDS key with a non-blank string
        value. source is a url or an ad name, and appears in the error message.
    """
    if not isinstance(post, dict):
        raise ScrapeError(f"expected a job posting object from {source}, got {type(post).__name__}")
    for field in POST_FIELDS:
        value = post.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ScrapeError(f"job posting from {source} is missing a usable {field!r}")
    return post


def extract_post(page_text, source="page text"):
    """ extract a job posting's structured fields from its raw page text """
    post = ask_json(
        "Extract the following fields from this job posting page as JSON, "
        "with exactly these keys: job_title, company, location, description. "
        "location should contain any address/city/office info found on the page. "
        "Description should collect the full job and company description, including the remote policy information available."
        "Respond with only the JSON object, no other text.\n\n"
        f"{page_text}",
        max_tokens=EXTRACTION_MODEL_MAX_TOKENS,
    )
    return validate_post(post, source)


def scrape_post(url):
    """given a web address with a job post, extract job title, company, location relevant data and description"""
    return extract_post(fetch_page_text(url), source=url)
