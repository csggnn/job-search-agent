"""
Shared configuration for the pipeline: filesystem paths to the personalization files,
small helpers for reading/hashing them, a couple of cross-cutting constants, and
environment access.

API keys are loaded from /config/.env, the container mount of ~/.config/job-search-agent/.
Environment variables are read lazily (never at import time), so the rest of the package
can be imported - and its pure helpers unit-tested - without any keys.
Kept free of any candidate-specific content.
"""

import hashlib
import os
import re

from dotenv import load_dotenv

load_dotenv("/config/.env")

# where the user keeps the API keys, mounted at /config in the container
KEYS_FILE = "~/.config/job-search-agent/.env"

# every API key the pipeline or the SDKs it calls read from the environment. .env.example
# names each of them. Whether a key is required is checked where it is used.
API_KEYS = ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "GROQ_API_KEY", "ORS_API_KEY")

# --- filesystem layout ---
# every user data path derives from DATA_DIR
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data"))
RESUME_PATH = os.path.join(DATA_DIR, "resume.md")
JOB_PREFERENCES_PATH = os.path.join(DATA_DIR, "job_preferences.md")
EVALS_DATA_DIR = os.path.join(DATA_DIR, "evals")

# the example user's data, committed. No pipeline command reads it. A user creates DATA_DIR
# from it with `cp -r data.example data`.
SAMPLE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data.example"))

# sentinel address marking a job with no commuting office, shared by commute scoring and
# storage (which turns it into the is_remote flag)
FULLY_REMOTE = "Fully Remote"


# --- environment access (read lazily, never at import time) ---
def get_env(name, default=None):
    """ return environment variable `name`, or `default` if it is unset """
    return os.environ.get(name, default)


def require_env(name):
    """ return environment variable `name`, raising a clear error if it is unset """
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(f"required environment variable {name!r} is not set: add it to "
                           f"{KEYS_FILE}")


CREATE_DATA_COMMAND = "cp -r data.example data"

# the job preferences sections the pipeline reads
PREFERENCES_SECTIONS = ("Location", "Home Address", "Scoring Notes")


def missing_data_files():
    """ the resume and job preferences paths that do not exist, in that order """
    return [path for path in (RESUME_PATH, JOB_PREFERENCES_PATH) if not os.path.exists(path)]


def require_data():
    """ raise if the resume or the job preferences is missing. Entry points call it before
        any API call or write. The template in SAMPLE_DIR is not read in their place.
    """
    missing = missing_data_files()
    if missing:
        raise RuntimeError(f"missing user data: {', '.join(missing)}. Create data/ from the "
                           f"template, in the checkout root: {CREATE_DATA_COMMAND}")


def data_problems(missing_files, preferences_text):
    """ one message per missing user data file and per section of PREFERENCES_SECTIONS that is
        missing or empty in `preferences_text`. `preferences_text` is None when the job
        preferences file is missing. An empty list means the data is complete.
    """
    problems = [f"{path} does not exist. Create data/ from the template, in the checkout "
                f"root: {CREATE_DATA_COMMAND}" for path in missing_files]
    if preferences_text is not None:
        for heading in PREFERENCES_SECTIONS:
            if not _section_has_content(extract_section(preferences_text, heading)):
                problems.append(f"## {heading} is missing or empty in {JOB_PREFERENCES_PATH}")
    return problems


def _section_has_content(section):
    """ True if `section` holds a line other than a "(fill in ...)" placeholder. A section
        whose first such line is a "## " heading is empty: extract_section() ran into the
        next section.
    """
    if not section:
        return False
    for line in section.splitlines():
        line = line.strip()
        if line and not line.startswith("(fill in"):
            return re.match(r"##\s", line) is None
    return False


def home_address(preferences=None):
    """ the candidate's home address, from the "## Home Address" section of
        job_preferences.md, which commute times are measured from. `preferences` is the job
        preferences text; when None, the file at JOB_PREFERENCES_PATH is read. Raises if the
        section is absent or still holds the "(fill in ...)" template placeholder.
    """
    if preferences is None:
        preferences = read_job_preferences()
    section = extract_section(preferences, "Home Address")
    address = _first_content_line(section) if section else None
    if not address:
        raise RuntimeError(
            "no home address found: add a '## Home Address' section with your full street "
            f"address to {JOB_PREFERENCES_PATH}"
        )
    return address


# --- personalization files ---
def read_resume():
    """ return the candidate's resume/CV as markdown text """
    with open(RESUME_PATH) as f:
        return f.read()


def read_job_preferences():
    """ return the candidate's job preferences as markdown text """
    with open(JOB_PREFERENCES_PATH) as f:
        return f.read()


def file_hash(path):
    """ sha256 hex digest of a file's contents, used to detect resume/preferences changes """
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def extract_section(markdown_text, heading):
    """ return the raw text under a "## <heading>" section of a markdown document, up to the
        next "## " heading or end of document; None if the heading isn't present. Used to carry
        free-text sections (e.g. candidate-authored scoring guidance) verbatim into the rubric,
        without any domain-specific content living in code.
    """
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s+|\Z)",
        markdown_text,
        re.DOTALL | re.MULTILINE,
    )
    return match.group(1).strip() if match else None


def _first_content_line(text):
    """ first stripped line of `text` that carries a value: non-empty and not a "(fill in
        ...)" template placeholder. Returns None if that line is a markdown heading or
        comment, which means the intended section was empty and extract_section() ran on
        into the next one.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("(fill in"):
            continue
        return None if line.startswith(("#", "<!--")) else line
    return None
