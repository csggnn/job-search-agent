"""
Offline tests for scripts/profile.sh. The script is copied into a temporary checkout-like
tree and run with bash, so it acts on that tree's profiles/.

    podman-compose exec job-search python3 -m unittest discover -s tests/unit -v
"""

import os
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts",
                                       "profile.sh"))

GENERATED = ("evaluations.db", "compatibility_rubric.json", "search_queries.json")
INPUTS = ("resume.md", "job_preferences.md", os.path.join("evals", "cases.json"))


def _snapshot(root):
    """ {relative path: content} of every file under root """
    files = {}
    for directory, _, names in os.walk(root):
        for name in names:
            path = os.path.join(directory, name)
            with open(path, "rb") as f:
                files[os.path.relpath(path, root)] = f.read()
    return files


class ProfileShTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        os.makedirs(os.path.join(self.root, "scripts"))
        shutil.copy(SCRIPT, os.path.join(self.root, "scripts", "profile.sh"))
        for profile in ("default", "personal"):
            for name in GENERATED + INPUTS:
                path = os.path.join(self.root, "profiles", profile, name)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(f"{profile} {name}\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(["bash", os.path.join(self.root, "scripts", "profile.sh"), *args],
                              capture_output=True, text=True)

    def test_reset_the_default_profile(self):
        default_dir = os.path.join(self.root, "profiles", "default")
        personal_dir = os.path.join(self.root, "profiles", "personal")
        inputs_before = {name: _snapshot(default_dir)[name] for name in INPUTS}
        personal_before = _snapshot(personal_dir)

        result = self._run("reset-default")

        self.assertEqual(result.returncode, 0, result.stderr)
        after = _snapshot(default_dir)
        for name in GENERATED:
            self.assertNotIn(name, after)
        self.assertEqual({name: after[name] for name in INPUTS}, inputs_before)
        self.assertEqual(_snapshot(personal_dir), personal_before)

    def test_unknown_command_fails(self):
        result = self._run("reset-personal")
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr)


if __name__ == "__main__":
    unittest.main()
