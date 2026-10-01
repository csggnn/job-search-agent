"""
Shared configuration for the pipeline: profile resolution and the filesystem paths it
yields, small helpers for reading/hashing the personalization files, a couple of
cross-cutting constants, and environment access.

A profile is one candidate's directory: resume.md, job_preferences.md, the generated
database, rubric and search queries, and the eval set. profiles/default/ holds the
committed sample candidate. profiles/personal/ holds the user's own candidate and is
gitignored. A run uses the personal profile unless --default-profile is given. An entry
point resolves the profile with profile_from_args() and passes its directory to every
function that reads or writes profile data. No module holds the active profile, and nothing
is resolved at import time.

API keys are loaded from /config/.env, the container mount of ~/.config/job-search-agent/.
Environment variables are read lazily (never at import time), so the rest of the package
can be imported - and its pure helpers unit-tested - without any keys.
Kept free of any candidate-specific content.
"""

import atexit
import dataclasses
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


@dataclasses.dataclass(frozen=True)
class Profile:
    """ the profile a run uses: its name ("default" or "personal") and the directory holding
        its files, which is a temporary copy under --scratch. Every path inside a profile is
        derived here.
    """
    name: str
    directory: str

    @property
    def resume_path(self):
        return os.path.join(self.directory, RESUME_FILE)

    @property
    def job_preferences_path(self):
        return os.path.join(self.directory, JOB_PREFERENCES_FILE)

    @property
    def evaluations_db_path(self):
        return os.path.join(self.directory, "evaluations.db")

    @property
    def rubric_path(self):
        return os.path.join(self.directory, "compatibility_rubric.json")

    @property
    def search_queries_path(self):
        return os.path.join(self.directory, "search_queries.json")

    @property
    def evals_dir(self):
        """ the eval set: cases.json, ads/ and runs/ """
        return os.path.join(self.directory, "evals")

    @property
    def runs_dir(self):
        """ one snapshot per evals/run_evals.py run """
        return os.path.join(self.evals_dir, "runs")

    def read_resume(self):
        """ the resume/CV as markdown text """
        with open(self.resume_path) as f:
            return f.read()

    def read_job_preferences(self):
        """ the job preferences as markdown text """
        with open(self.job_preferences_path) as f:
            return f.read()

    def home_address(self):
        """ home_address() of job_preferences.md, naming the file on error """
        return home_address(self.read_job_preferences(), self.job_preferences_path)

    def input_hashes(self):
        """ content hashes of resume.md and job_preferences.md. The rubric and search query
            caches store them and are stale when they differ.
        """
        return {"resume_hash": file_hash(self.resume_path),
                "preferences_hash": file_hash(self.job_preferences_path)}

    def inputs_changed_since(self, cache):
        """ True if resume.md/job_preferences.md differ from the content `cache` was built from """
        return any(cache.get(key) != value for key, value in self.input_hashes().items())


class ProfileError(RuntimeError):
    """ the requested profile cannot be used """


def resolve_profile(default_profile=False, checkout_root=CHECKOUT_ROOT):
    """ return the Profile a run in `checkout_root` uses: profiles/personal/ unless
        default_profile is True, which selects profiles/default/.

        ProfileError is raised for the personal profile naming each of its resume.md and
        job_preferences.md that is missing, and --default-profile.
    """
    profiles = os.path.join(checkout_root, "profiles")
    if default_profile:
        return Profile("default", os.path.join(profiles, "default"))
    profile = Profile("personal", os.path.join(profiles, "personal"))
    missing = [path for path in (profile.resume_path, profile.job_preferences_path)
               if not os.path.isfile(path)]
    if missing:
        raise ProfileError(
            "the personal profile is incomplete, missing: " + ", ".join(missing) + ". "
            "Create the missing file(s), or run with --default-profile to use the sample "
            "candidate in " + os.path.join(profiles, "default")
        )
    return profile


def add_profile_argument(parser):
    """ register --default-profile and --scratch on an argparse parser """
    parser.add_argument("--default-profile", action="store_true",
                        help="use the sample candidate in profiles/default/ instead of "
                             "profiles/personal/")
    parser.add_argument("--scratch", action="store_true",
                        help="run on a temporary copy of the profile, deleted when the "
                             "command exits; the profile's files are not changed")


def profile_from_args(args, checkout_root=CHECKOUT_ROOT):
    """ return the Profile selected by parsed --default-profile/--scratch arguments, and
        print it to stderr. Under --scratch, the directory is a temporary copy removed at
        interpreter exit. Exits with the ProfileError message if the profile cannot be used.
    """
    try:
        profile = resolve_profile(args.default_profile, checkout_root)
    except ProfileError as e:
        sys.exit(f"error: {e}")
    if args.scratch:
        print(f"profile: {profile.name} (scratch copy of {profile.directory})", file=sys.stderr)
        return Profile(profile.name, _scratch_copy(profile.directory))
    print(f"profile: {profile.name} ({profile.directory})", file=sys.stderr)
    return profile


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


def home_address(preferences, source=JOB_PREFERENCES_FILE):
    """ the candidate's home address, from the "## Home Address" section of the
        job_preferences.md text `preferences`, which commute times are measured from.
        Raises naming `source` if the section is absent or still holds the "(fill in ...)"
        template placeholder.
    """
    section = extract_section(preferences, "Home Address")
    address = _first_content_line(section) if section else None
    if not address:
        raise RuntimeError(
            "no home address found: add a '## Home Address' section with your full street "
            f"address to {source}"
        )
    return address


# --- personalization files ---
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
