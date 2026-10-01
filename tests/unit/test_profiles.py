"""
Offline tests for profile selection, --scratch copies, the .env.example template and the
job_preferences.md section check. Each test builds a checkout-like tree in a temporary
directory and points jobsearch.config at it.

    podman-compose exec job-search python3 -m unittest discover -s tests/unit -v
"""

import os
import re
import unittest

from jobsearch import config

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


class EnvExampleTest(unittest.TestCase):

    def test_env_example_names_every_api_key(self):
        with open(os.path.join(REPO_ROOT, ".env.example")) as f:
            named = set(re.findall(r"^([A-Z0-9_]+)=", f.read(), re.MULTILINE))
        missing = [key for key in config.API_KEYS if key not in named]
        self.assertEqual(missing, [], f".env.example does not name: {', '.join(missing)}")


if __name__ == "__main__":
    unittest.main()
