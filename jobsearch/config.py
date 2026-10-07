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


# the job preferences sections the pipeline reads
PREFERENCES_SECTIONS = ("Location", "Home Address", "Scoring Notes")


def missing_data_message():
    """ None if the resume and the job preferences exist; otherwise a message naming each
        missing file and how to restore it. With DATA_DIR present, the message does not
        suggest copying template files into it.
    """
    missing = [path for path in (RESUME_PATH, JOB_PREFERENCES_PATH) if not os.path.exists(path)]
    if not missing:
        return None
    fix = ("restore the missing file, or remove data/ and create it again from the template"
           if os.path.isdir(DATA_DIR) else "create data/ from the template")
    return (f"missing user data: {', '.join(missing)}. In the checkout root, {fix}: "
            "cp -r data.example data")


def require_data():
    """ raise if the resume or the job preferences is missing. Entry points call it before
        any API call or write.
    """
    message = missing_data_message()
    if message:
        raise RuntimeError(message)


def empty_preferences_sections(preferences):
    """ the headings of PREFERENCES_SECTIONS that are missing or empty in `preferences` """
    return [heading for heading in PREFERENCES_SECTIONS
            if not _section_has_content(extract_section(preferences, heading))]


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
