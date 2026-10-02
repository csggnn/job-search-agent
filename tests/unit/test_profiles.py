"""
Offline tests for profile selection, --scratch copies, the .env.example template and the
job_preferences.md section check. Each test builds a checkout-like tree in a temporary
directory and passes its path to jobsearch.config.

    podman-compose exec job-search python3 -m unittest discover -s tests/unit -v
"""

import argparse
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from unittest import mock

from jobsearch import commute, config, storage

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


def _args(default=False, scratch=False):
    """ parsed --default-profile/--scratch arguments """
    return argparse.Namespace(default_profile=default, scratch=scratch)


class _CheckoutTestCase(unittest.TestCase):
    """ a temporary checkout holding the default profile's inputs and no personal profile """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.default_dir = os.path.join(self.root, "profiles", "default")
        self.personal_dir = os.path.join(self.root, "profiles", "personal")
        _write(os.path.join(self.default_dir, "resume.md"), "# Sample\n")
        _write(os.path.join(self.default_dir, "job_preferences.md"), PREFERENCES)

    def tearDown(self):
        self._tmp.cleanup()

    def add_personal(self, resume=True, preferences=True):
        if resume:
            _write(os.path.join(self.personal_dir, "resume.md"), "# Personal\n")
        if preferences:
            _write(os.path.join(self.personal_dir, "job_preferences.md"), PREFERENCES)


class ProfileSelectionTest(_CheckoutTestCase):

    def test_fresh_clone_runs_the_default_profile(self):
        self.assertEqual(config.resolve_profile(True, self.root),
                         config.Profile("default", self.default_dir))

    def test_fresh_clone_without_the_flag(self):
        with self.assertRaises(config.ProfileError) as ctx:
            config.resolve_profile(False, self.root)
        message = str(ctx.exception)
        self.assertIn(os.path.join(self.personal_dir, "resume.md"), message)
        self.assertIn(os.path.join(self.personal_dir, "job_preferences.md"), message)
        self.assertIn("--default-profile", message)

    def test_personal_files_select_the_personal_profile(self):
        self.add_personal()
        self.assertEqual(config.resolve_profile(False, self.root),
                         config.Profile("personal", self.personal_dir))

    def test_one_personal_file_is_missing(self):
        self.add_personal(preferences=False)
        with self.assertRaises(config.ProfileError) as ctx:
            config.resolve_profile(False, self.root)
        message = str(ctx.exception)
        self.assertIn(os.path.join(self.personal_dir, "job_preferences.md"), message)
        self.assertNotIn(os.path.join(self.personal_dir, "resume.md"), message)
        self.assertIn("--default-profile", message)

    def test_requesting_the_default_profile(self):
        self.add_personal()
        self.assertEqual(config.resolve_profile(True, self.root),
                         config.Profile("default", self.default_dir))

    def test_profile_from_args_selects_the_requested_profile(self):
        self.add_personal()
        with mock.patch("sys.stderr"):
            self.assertEqual(config.profile_from_args(_args(default=True), self.root),
                             config.Profile("default", self.default_dir))
            self.assertEqual(config.profile_from_args(_args(), self.root),
                             config.Profile("personal", self.personal_dir))

    def test_paths_are_built_from_the_profile_directory(self):
        profile = config.Profile("default", self.default_dir)
        self.assertEqual(profile.resume_path, os.path.join(self.default_dir, "resume.md"))
        self.assertEqual(profile.evaluations_db_path,
                         os.path.join(self.default_dir, "evaluations.db"))
        self.assertEqual(profile.runs_dir, os.path.join(self.default_dir, "evals", "runs"))

    def test_inputs_changed_since_a_cache(self):
        profile = config.Profile("default", self.default_dir)
        cache = {**profile.input_hashes(), "queries": []}
        self.assertFalse(profile.inputs_changed_since(cache))
        _write(profile.job_preferences_path, PREFERENCES + "\n## Other\nedited\n")
        self.assertTrue(profile.inputs_changed_since(cache))

    def test_incomplete_personal_profile_writes_no_database(self):
        for resume in (False, True):
            with self.subTest(personal_resume=resume):
                if resume:
                    self.add_personal(preferences=False)
                with self.assertRaises(SystemExit) as ctx:
                    config.profile_from_args(_args(), self.root)
                self.assertIn("--default-profile", str(ctx.exception))
                self.assertEqual(_databases(self.root), [])


class ScratchTest(_CheckoutTestCase):
    """ each scratch run is a separate interpreter, so the copy's removal at exit is observed """

    # selects a profile in the checkout given as argv[1] with --scratch, prints the row count
    # the run sees, then saves a row to its database
    SCRIPT = (
        "import argparse, sys\n"
        "from jobsearch import config, storage\n"
        "profile = config.profile_from_args(argparse.Namespace("
        "default_profile=sys.argv[2] == 'default', scratch=True), sys.argv[1])\n"
        "conn = storage._get_connection(profile)\n"
        "print(profile.directory)\n"
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
        storage._get_connection(config.Profile("seed", profile_dir)).close()
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


class CommuteHomeAddressTest(unittest.TestCase):
    """ commute scoring reads the home address only when it computes a route """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.profile = config.Profile("personal", self._tmp.name)
        _write(self.profile.job_preferences_path, "## Location\n- Metropolis\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _score(self, days, address):
        with mock.patch.object(commute, "figure_days_on_office", return_value=days), \
             mock.patch.object(commute, "figure_address", return_value=address):
            return commute.commute_score(self.profile, "Acme", "Metropolis", "text")

    def test_remote_job_without_a_home_address(self):
        self.assertEqual(self._score(0, None)["score"], 0)

    def test_unresolved_office_without_a_home_address(self):
        self.assertIsNone(self._score(3, None)["score"])

    def test_routed_job_without_a_home_address(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._score(3, "1 Main St, Metropolis")
        self.assertIn(self.profile.job_preferences_path, str(ctx.exception))


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
