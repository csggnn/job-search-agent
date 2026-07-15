"""
Shared configuration for the pipeline: filesystem paths to the personalization files,
small helpers for reading/hashing them, a couple of cross-cutting constants, and
environment access.

Environment variables are read lazily (never at import time), so the rest of the
package can be imported - and its pure helpers unit-tested - without a populated .env.
Kept free of any candidate-specific content.
"""

import hashlib
import os
import re

from dotenv import load_dotenv

load_dotenv()

# --- filesystem layout ---
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data"))
RESUME_PATH = os.path.join(DATA_DIR, "resume.md")
JOB_PREFERENCES_PATH = os.path.join(DATA_DIR, "job_preferences.md")

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
        raise RuntimeError(f"required environment variable {name!r} is not set")


def home_address():
    """ the candidate's home address, which commute times are measured from """
    return require_env("HOME_ADDRESS")


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
