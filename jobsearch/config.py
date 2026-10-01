"""
Shared configuration for the pipeline: profile resolution and the filesystem paths it
yields, small helpers for reading/hashing the personalization files, a couple of
cross-cutting constants, and environment access.

A profile is one candidate's directory: resume.md, job_preferences.md, the generated
database, rubric and search queries, and the eval set. profiles/default/ holds the
committed sample candidate. profiles/personal/ holds the user's own candidate and is
gitignored. A run uses the personal profile unless --default-profile is given. The profile
is resolved on first path use, never at import time, so importing jobsearch does not depend
on the importing process's arguments.

API keys are loaded from /config/.env, the container mount of ~/.config/job-search-agent/.
Environment variables are read lazily (never at import time), so the rest of the package
can be imported - and its pure helpers unit-tested - without any keys.
Kept free of any candidate-specific content.
"""

import atexit
import hashlib
import os
import re
import shutil
import sys
import tempfile

from dotenv import load_dotenv

load_dotenv("/config/.env")

# where the user keeps the API keys, mounted at /config in the container
KEYS_FILE = "~/.config/job-search-agent/.env"

# every API key the pipeline or the SDKs it calls read from the environment. .env.example
# names each of them. Whether a key is required is checked where it is used.
API_KEYS = ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "GROQ_API_KEY", "ORS_API_KEY")

# --- profiles ---
CHECKOUT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_PROFILE_DIR = os.path.join(CHECKOUT_ROOT, "profiles", "default")
RESUME_FILE = "resume.md"
JOB_PREFERENCES_FILE = "job_preferences.md"


class ProfileError(RuntimeError):
    """ the requested profile cannot be used """


def resolve_profile(checkout_root, default_profile):
    """ return (name, directory) of the profile a run in `checkout_root` uses.

        default_profile=True selects profiles/default/. Otherwise the result is
        profiles/personal/, and ProfileError is raised naming each of its resume.md and
        job_preferences.md that is missing, and --default-profile.
    """
    profiles = os.path.join(checkout_root, "profiles")
    if default_profile:
        return "default", os.path.join(profiles, "default")
    directory = os.path.join(profiles, "personal")
    missing = [os.path.join(directory, name) for name in (RESUME_FILE, JOB_PREFERENCES_FILE)
               if not os.path.isfile(os.path.join(directory, name))]
    if missing:
        raise ProfileError(
            "the personal profile is incomplete, missing: " + ", ".join(missing) + ". "
            "Create the missing file(s), or run with --default-profile to use the sample "
            "candidate in " + os.path.join(profiles, "default")
        )
    return "personal", directory


_profile = None  # (name, directory) once resolved


def _active_profile():
    global _profile
    if _profile is None:
        _profile = resolve_profile(CHECKOUT_ROOT, False)
    return _profile


def profile_dir():
    """ directory of the active profile, or of its scratch copy under --scratch """
    return _active_profile()[1]


def profile_name():
    """ name of the active profile: "default" or "personal" """
    return _active_profile()[0]


def use_default_profile():
    """ select the default profile, for Python callers with no command line """
    global _profile
    _profile = resolve_profile(CHECKOUT_ROOT, True)


def evals_data_dir():
    """ the active profile's eval set directory: cases.json, ads/ and runs/ """
    return os.path.join(profile_dir(), "evals")


def resume_path():
    return os.path.join(profile_dir(), RESUME_FILE)


def job_preferences_path():
    return os.path.join(profile_dir(), JOB_PREFERENCES_FILE)


def add_profile_argument(parser):
    """ register --default-profile and --scratch on an argparse parser """
    parser.add_argument("--default-profile", action="store_true",
                        help="use the sample candidate in profiles/default/ instead of "
                             "profiles/personal/")
    parser.add_argument("--scratch", action="store_true",
                        help="run on a temporary copy of the profile, deleted when the "
                             "command exits; the profile's files are not changed")


def apply_profile_args(args):
    """ resolve the profile selected by parsed --default-profile/--scratch arguments, and
        print it to stderr. Exits with the ProfileError message if the profile cannot be used.
    """
    global _profile
    try:
        name, directory = resolve_profile(CHECKOUT_ROOT, args.default_profile)
    except ProfileError as e:
        sys.exit(f"error: {e}")
    if args.scratch:
        _profile = (name, _scratch_copy(directory))
        print(f"profile: {name} (scratch copy of {directory})", file=sys.stderr)
    else:
        _profile = (name, directory)
        print(f"profile: {name} ({directory})", file=sys.stderr)


def _scratch_copy(directory):
    """ copy `directory` to a new temporary directory, removed at interpreter exit. returns
        the copy's path.
    """
    scratch_root = tempfile.mkdtemp(prefix="job-search-scratch-")
    atexit.register(shutil.rmtree, scratch_root, ignore_errors=True)
    copy = os.path.join(scratch_root, os.path.basename(directory))
    if os.path.isdir(directory):
        shutil.copytree(directory, copy)
    else:
        os.makedirs(copy)
    return copy


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


def home_address(preferences=None):
    """ the candidate's home address, from the "## Home Address" section of
        job_preferences.md, which commute times are measured from. `preferences` is the
        job_preferences.md text, read from the active profile when None. Raises if the
        section is absent or still holds the "(fill in ...)" template placeholder.
    """
    source = "job_preferences.md"
    if preferences is None:
        source = job_preferences_path()
        preferences = read_job_preferences()
    section = extract_section(preferences, "Home Address")
    address = _first_content_line(section) if section else None
    if not address:
        raise RuntimeError(
            "no home address found: add a '## Home Address' section with your full street "
            f"address to {source}"
        )
    return address


# --- personalization files ---
def read_resume():
    """ return the candidate's resume/CV as markdown text """
    with open(resume_path()) as f:
        return f.read()


def read_job_preferences():
    """ return the candidate's job preferences as markdown text """
    with open(job_preferences_path()) as f:
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


# the job_preferences.md sections the pipeline reads
PREFERENCE_SECTIONS = ("Location", "Home Address", "Scoring Notes")


def missing_preference_sections(preferences):
    """ the PREFERENCE_SECTIONS that job_preferences.md text lacks, or that hold no value
        besides "(fill in ...)" placeholders
    """
    return [heading for heading in PREFERENCE_SECTIONS
            if not _first_content_line(extract_section(preferences, heading) or "")]


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
