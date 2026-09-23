"""
Job-posting content acquisition: fetch a posting URL and extract its structured fields
(job_title, company, location, description).
"""

import re
from urllib.parse import parse_qs, urlsplit

from tavily import TavilyClient

from jobsearch import config
from jobsearch.llm import ask_json, EXTRACTION_MODEL_MAX_TOKENS

POST_FIELDS = ("job_title", "company", "location", "description")

# LinkedIn's public job-posting endpoint. To clients without a session, the /jobs/view/ page
# serves either the posting or a sign-in page with no description; this endpoint serves the
# posting.
LINKEDIN_GUEST_POSTING_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
# /jobs/view/<id> or /jobs/view/<title-slug>-<id>
_LINKEDIN_VIEW_PATH_RE = re.compile(r"^/jobs/view/(?:[^/]*-)?(\d+)/?$")


class ScrapeError(ValueError):
    """ raised when a job posting's content could not be extracted from a URL """


def public_posting_url(url):
    """ the no-login address of the posting at url, for a job board whose posting page
        can serve a sign-in page in place of the posting; None for any other url.

        Handled boards: LinkedIn. A LinkedIn url naming a job id, in its path
        (/jobs/view/<id>, /jobs/view/<slug>-<id>) or its currentJobId query parameter,
        maps to LINKEDIN_GUEST_POSTING_URL for that id.
    """
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None
    match = _LINKEDIN_VIEW_PATH_RE.match(parts.path)
    job_id = match.group(1) if match else parse_qs(parts.query).get("currentJobId", [None])[0]
    if job_id is None or not job_id.isdigit():
        return None
    return LINKEDIN_GUEST_POSTING_URL.format(job_id)


def fetch_page_text(url):
    """ return the raw text of a job posting page. raises ScrapeError if it can't be fetched. """
    tavily = TavilyClient(api_key=config.require_env("TAVILY_API_KEY"))
    result = tavily.extract(public_posting_url(url) or url, format="text")
    if not result["results"]:
        raise ScrapeError(f"could not extract content from: {url}")
    return result["results"][0]["raw_content"]


def blank_post_fields(post):
    """ the POST_FIELDS keys of post whose value is missing or not a non-blank string, in
        POST_FIELDS order
    """
    return [field for field in POST_FIELDS
            if not isinstance(post.get(field), str) or not post[field].strip()]


def validate_post(post, source):
    """ raise ScrapeError unless post holds every POST_FIELDS key with a non-blank string
        value. Other keys are allowed and returned unchanged. source is a url or an ad
        name, and appears in the error message.
    """
    if not isinstance(post, dict):
        raise ScrapeError(f"expected a job posting object from {source}, got {type(post).__name__}")
    blank = blank_post_fields(post)
    if blank:
        raise ScrapeError(f"job posting from {source} is missing a usable {blank[0]!r}")
    return post


def extract_post(page_text, source="page text"):
    """ extract a job posting's structured fields from its raw page text. raises ScrapeError
        when the page holds no job description, e.g. a login wall showing only the title.
    """
    post = ask_json(
        "Extract the following fields from this job posting page as JSON, "
        "with exactly these keys: job_title, company, location, description. "
        "location should contain any address/city/office info found on the page. "
        "Description should collect the full job and company description, including the remote policy information available. "
        "Set description to an empty string only if the page contains no text describing the job's "
        "responsibilities, requirements or company, e.g. a page showing only the job title and location. "
        "Sign-in or cookie prompts elsewhere on the page do not affect this. "
        "Respond with only the JSON object, no other text.\n\n"
        f"{page_text}",
        max_tokens=EXTRACTION_MODEL_MAX_TOKENS,
    )
    return validate_post(post, source)


def scrape_post(url):
    """given a web address with a job post, extract job title, company, location relevant data and description"""
    return extract_post(fetch_page_text(url), source=url)
