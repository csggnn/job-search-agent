"""
Offline tests for profile selection, --scratch copies, the .env.example template and the
job_preferences.md section check. Each test builds a checkout-like tree in a temporary
directory and points jobsearch.config at it.

    podman-compose exec job-search python3 -m unittest discover -s tests/unit -v
"""

import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from jobsearch import config, storage

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

PREFERENCES = ("## Location\n- Metropolis, Freedonia\n\n"
               "## Home Address\n1 Riverside Dr, Metropolis\n\n"
               "## Scoring Notes\nweigh A\n")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _databases(root):
    return [os.path.join(d, f) for d, _, files in os.walk(root) for f in files
            if f == "evaluations.db"]


class _CheckoutTestCase(unittest.TestCase):
    """ a temporary checkout holding the default profile's inputs and no personal profile.
        config's checkout root and active profile are restored after each test.
    """

    def setUp(self):
        self._saved = (config.CHECKOUT_ROOT, config._profile)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.default_dir = os.path.join(self.root, "profiles", "default")
        self.personal_dir = os.path.join(self.root, "profiles", "personal")
        _write(os.path.join(self.default_dir, "resume.md"), "# Sample\n")
        _write(os.path.join(self.default_dir, "job_preferences.md"), PREFERENCES)
        config.CHECKOUT_ROOT = self.root
        config._profile = None

    def tearDown(self):
        config.CHECKOUT_ROOT, config._profile = self._saved
        self._tmp.cleanup()

    def add_personal(self, resume=True, preferences=True):
        if resume:
            _write(os.path.join(self.personal_dir, "resume.md"), "# Personal\n")
        if preferences:
            _write(os.path.join(self.personal_dir, "job_preferences.md"), PREFERENCES)


class ProfileSelectionTest(_CheckoutTestCase):

    def test_fresh_clone_runs_the_default_profile(self):
        self.assertEqual(config.resolve_profile(self.root, True), ("default", self.default_dir))

    def test_fresh_clone_without_the_flag(self):
        with self.assertRaises(config.ProfileError) as ctx:
            config.resolve_profile(self.root, False)
        message = str(ctx.exception)
        self.assertIn(os.path.join(self.personal_dir, "resume.md"), message)
        self.assertIn(os.path.join(self.personal_dir, "job_preferences.md"), message)
        self.assertIn("--default-profile", message)

    def test_personal_files_select_the_personal_profile(self):
        self.add_personal()
        self.assertEqual(config.resolve_profile(self.root, False),
                         ("personal", self.personal_dir))

    def test_one_personal_file_is_missing(self):
        self.add_personal(preferences=False)
        with self.assertRaises(config.ProfileError) as ctx:
            config.resolve_profile(self.root, False)
        message = str(ctx.exception)
        self.assertIn(os.path.join(self.personal_dir, "job_preferences.md"), message)
        self.assertNotIn(os.path.join(self.personal_dir, "resume.md"), message)
        self.assertIn("--default-profile", message)

    def test_requesting_the_default_profile(self):
        self.add_personal()
        self.assertEqual(config.resolve_profile(self.root, True), ("default", self.default_dir))

    def test_paths_resolve_under_the_active_profile(self):
        config.use_default_profile()
        self.assertEqual(config.profile_name(), "default")
        self.assertEqual(config.resume_path(), os.path.join(self.default_dir, "resume.md"))
        self.assertEqual(config.evals_data_dir(), os.path.join(self.default_dir, "evals"))
        self.assertEqual(storage.db_path(), os.path.join(self.default_dir, "evaluations.db"))

    def test_incomplete_personal_profile_writes_no_database(self):
        for resume in (False, True):
            with self.subTest(personal_resume=resume):
                if resume:
                    self.add_personal(preferences=False)
                config._profile = None
                with self.assertRaises(config.ProfileError):
                    storage._get_connection()
                self.assertEqual(_databases(self.root), [])


class ScratchTest(_CheckoutTestCase):
    """ each scratch run is a separate interpreter, so the copy's removal at exit is observed """

    # selects a profile in the checkout given as argv[1] with --scratch, prints the row count
    # the run sees, then saves a row to its database
    SCRIPT = (
        "import argparse, sys\n"
        "from jobsearch import config, storage\n"
        "config.CHECKOUT_ROOT = sys.argv[1]\n"
        "config.apply_profile_args(argparse.Namespace(default_profile=sys.argv[2] == 'default',"
        " scratch=True))\n"
        "conn = storage._get_connection()\n"
        "print(config.profile_dir())\n"
        "print(conn.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0])\n"
        "conn.execute(\"INSERT INTO evaluations (url, normalized_url, is_remote,"
        " compatibility_score, rubric_hash, evaluated_at) VALUES ('u', 'u', 0, 50, 'h', 't')\")\n"
        "conn.commit()\n"
    )

    def _scratch_run(self, profile):
        result = subprocess.run([sys.executable, "-c", self.SCRIPT, self.root, profile],
                                cwd=REPO_ROOT, capture_output=True, text=True, check=True)
        copy, rows = result.stdout.split()
        return copy, int(rows)

    def _seed_database(self, profile_dir):
        storage_path = os.path.join(profile_dir, "evaluations.db")
        config._profile = ("seed", profile_dir)
        storage._get_connection().close()
        conn = sqlite3.connect(storage_path)
        conn.execute("INSERT INTO evaluations (url, normalized_url, is_remote, "
                     "compatibility_score, rubric_hash, evaluated_at) "
                     "VALUES ('s', 's', 0, 50, 'h', 't')")
        conn.commit()
        conn.close()
        _write(os.path.join(profile_dir, "compatibility_rubric.json"), "{}")
        _write(os.path.join(profile_dir, "search_queries.json"), "{}")
        return {name: _sha256(os.path.join(profile_dir, name))
                for name in ("evaluations.db", "compatibility_rubric.json", "search_queries.json",
                             "resume.md", "job_preferences.md")}

    def _assert_unchanged(self, profile_dir, hashes):
        self.assertEqual({name: _sha256(os.path.join(profile_dir, name)) for name in hashes},
                         hashes)

    def test_scratch_run_on_the_personal_profile(self):
        self.add_personal()
        hashes = self._seed_database(self.personal_dir)
        copy, rows = self._scratch_run("personal")
        self.assertEqual(rows, 1, "the scratch copy holds the personal profile's rows")
        self.assertFalse(copy.startswith(self.root))
        self._assert_unchanged(self.personal_dir, hashes)
        self.assertFalse(os.path.exists(copy), "the scratch copy remains after exit")

    def test_scratch_run_on_the_default_profile(self):
        hashes = self._seed_database(self.default_dir)
        copy, _ = self._scratch_run("default")
        self._assert_unchanged(self.default_dir, hashes)
        self.assertFalse(os.path.exists(copy))

    def test_a_scratch_copy_lasts_one_command(self):
        self.add_personal()
        _, first = self._scratch_run("personal")
        _, second = self._scratch_run("personal")
        self.assertEqual((first, second), (0, 0))
        self.assertEqual(_databases(self.root), [])


class EnvExampleTest(unittest.TestCase):

    def test_env_example_names_every_api_key(self):
        with open(os.path.join(REPO_ROOT, ".env.example")) as f:
            named = set(re.findall(r"^([A-Z0-9_]+)=", f.read(), re.MULTILINE))
        missing = [key for key in config.API_KEYS if key not in named]
        self.assertEqual(missing, [], f".env.example does not name: {', '.join(missing)}")


class PreferenceSectionsTest(unittest.TestCase):

    def test_complete_preferences(self):
        self.assertEqual(config.missing_preference_sections(PREFERENCES), [])

    def test_personal_preferences_lack_a_section(self):
        preferences = "## Location\n- Metropolis\n\n## Scoring Notes\nweigh A\n"
        self.assertEqual(config.missing_preference_sections(preferences), ["Home Address"])

    def test_empty_and_placeholder_sections(self):
        preferences = ("## Location\n\n## Home Address\n(fill in: street address)\n\n"
                       "## Scoring Notes\nweigh A\n")
        self.assertEqual(config.missing_preference_sections(preferences),
                         ["Location", "Home Address"])


if __name__ == "__main__":
    unittest.main()
