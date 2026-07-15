"""
End-to-end smoke test for the job-evaluation pipeline.

This test is deliberately a BLACK BOX: it drives the pipeline only through the stable
public seams that survive the planned package refactor -

  * the CLI entrypoints  `evaluate_job_post.py` / `discover_jobs.py`  (invoked as
    subprocesses), and
  * the on-disk SQLite database `data/evaluations.db` (inspected with the stdlib
    sqlite3 module).

It imports nothing from the project's own modules, so moving/renaming functions into a
`jobsearch/` package does not touch it. Run it BEFORE the refactor to capture a green
baseline, then again AFTER to confirm nothing regressed.

Run (inside the container):

    podman-compose exec notebook python3 -m unittest tests.test_e2e_pipeline -v
    # or, equivalently:
    podman-compose exec notebook python3 tests/test_e2e_pipeline.py

What it exercises, end to end:
    scrape_post -> commute_score -> compatibility_score (rubric compile+apply) ->
    summarize_evaluation -> storage.save_evaluation -> cache-hit read.

Configuration lives in the constants near the top of this file: set TARGET_URL to a
currently-live job posting (the pipeline really scrapes it) and flip RUN_DISCOVERY_SMOKE
to include the discovery test. If TARGET_URL stops resolving, the test FAILS with a
clear message so you can swap in a fresh posting.
"""

import os
import sqlite3
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "evaluations.db"
ENV_PATH = REPO_ROOT / ".env"

# env keys the pipeline needs to run for real; GROQ_API_KEY is only used by check_setup.py
REQUIRED_ENV = ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "ORS_API_KEY", "HOME_ADDRESS")

# the full pipeline can additionally (re)compile the rubric via an agentic LLM loop the
# first time it runs, so give it a generous ceiling
PIPELINE_TIMEOUT_S = 600

# --- test configuration ---

# Job posting the pipeline is exercised against. A live URL is required, since the
# pipeline really scrapes it; if it stops resolving, the test FAILS with a clear message
# so you can replace it with a currently-live posting.
TARGET_URL = "https://canonical.com/careers/6707824"

# The discovery smoke test scrapes live job boards (slow and flaky); flip to True to run it.
RUN_DISCOVERY_SMOKE = False


def _dotenv_values():
    """ best-effort parse of .env (KEY=value, ignoring blank/comment lines and trailing
        inline comments) - only used to decide whether the required keys are available to
        the child process, so we can skip cleanly instead of failing when they're absent
    """
    values = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        # strip a trailing inline comment (the template ships `KEY=   # explanation`)
        value = raw.split("#", 1)[0].strip()
        values[key.strip()] = value
    return values


def _env_available(key, dotenv):
    """ True if `key` has a non-empty value in the process env or in .env """
    return bool(os.environ.get(key) or dotenv.get(key))


def _log(msg):
    """ print a progress/summary line (unittest is silent on success, and this is a slow
        end-to-end run, so report what was actually exercised). Goes to stderr - the same
        stream unittest writes its own status to - so the lines stay in chronological order.
    """
    print(f"[e2e] {msg}", file=sys.stderr, flush=True)


class PipelineEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dotenv = _dotenv_values()
        missing = [k for k in REQUIRED_ENV if not _env_available(k, dotenv)]
        if missing:
            raise unittest.SkipTest(
                f"missing required config for an end-to-end run: {', '.join(missing)} "
                f"(set them in {ENV_PATH} or the environment)"
            )
        if not TARGET_URL:
            raise ValueError(
                "TARGET_URL is empty — set it to a currently-live job posting URL near "
                "the top of this file"
            )
        cls.url = TARGET_URL

    def _run_evaluate(self, args):
        """ invoke the evaluate entrypoint as a subprocess from the repo root """
        return subprocess.run(
            [sys.executable, "evaluate_job_post.py", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=PIPELINE_TIMEOUT_S,
        )

    @staticmethod
    def _looks_like_scrape_failure(result):
        """ recognize the ScrapeError path so a dead/unreachable target URL fails with a
            pointed "replace TARGET_URL" message instead of a raw stack trace
        """
        blob = (result.stdout + result.stderr).lower()
        return "scrapeerror" in blob or "could not extract content" in blob

    def _fetch_row(self, url):
        """ read the saved evaluation row for `url` straight from SQLite (column names are
            part of the persisted schema, which the refactor does not change)
        """
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(
                "SELECT job_title, company, is_remote, commute_score, commute_address, "
                "days_on_office, compatibility_score, works_well, does_not_work, rubric_hash "
                "FROM evaluations WHERE url = ?",
                (url,),
            ).fetchone()
        finally:
            conn.close()

    def _count_criteria(self, url):
        conn = sqlite3.connect(DB_PATH)
        try:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM evaluation_criteria WHERE evaluation_id = "
                "(SELECT id FROM evaluations WHERE url = ?)",
                (url,),
            ).fetchone()
        finally:
            conn.close()
        return count

    def test_evaluate_pipeline_end_to_end(self):
        """ run one live posting through the full pipeline, verify the persisted row, then
            confirm a second run is served from cache
        """
        _log(f"target URL: {self.url}")

        # 1. force a full, uncached run: scrape -> commute -> compatibility -> summary -> save
        _log("running full pipeline (--force): scrape -> commute -> compatibility -> summary -> save ...")
        start = time.monotonic()
        result = self._run_evaluate([self.url, "--force"])
        force_secs = time.monotonic() - start
        if result.returncode != 0:
            hint = ""
            if self._looks_like_scrape_failure(result):
                hint = (
                    f"\n\nThe target posting is no longer reachable/scrapeable:\n  {self.url}\n"
                    "Replace TARGET_URL near the top of this file with a currently-live posting."
                )
            self.fail(
                f"evaluate_job_post.py exited {result.returncode}{hint}\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        _log(f"full pipeline run OK in {force_secs:.1f}s")

        # 2. the printed evaluation carries every stage's output
        for label in (
            "Evaluating Position:",
            "Commute score:",
            "Compatibility score:",
            "Works well:",
            "Does not work:",
        ):
            self.assertIn(label, result.stdout, f"missing {label!r} in output:\n{result.stdout}")

        # 3. a well-formed row was persisted (assert shape/ranges, never exact LLM values)
        row = self._fetch_row(self.url)
        self.assertIsNotNone(row, "no evaluation row was saved for the target URL")
        self.assertTrue(row["job_title"], "job_title should be populated")
        self.assertIn(row["is_remote"], (0, 1))

        score = row["compatibility_score"]
        self.assertIsNotNone(score, "compatibility_score is NOT NULL in the schema")
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

        self.assertTrue(row["works_well"], "works_well summary should be populated")
        self.assertTrue(row["does_not_work"], "does_not_work summary should be populated")
        self.assertTrue(row["rubric_hash"], "rubric_hash should be populated")

        # commute only resolves to a score for a non-remote job whose office was located
        if not row["is_remote"] and row["commute_address"]:
            self.assertIsNotNone(row["commute_score"])
            self.assertGreater(row["commute_score"], 0)

        # 4. the rubric was compiled, applied, and its per-criterion breakdown saved
        n_criteria = self._count_criteria(self.url)
        self.assertGreater(n_criteria, 0, "expected saved rubric criteria rows")

        # 5. a second, non-forced run is served from the cache (no re-scrape / no LLM)
        start = time.monotonic()
        cached = self._run_evaluate([self.url])
        cache_secs = time.monotonic() - start
        self.assertEqual(cached.returncode, 0, cached.stderr)
        self.assertIn("cached from", cached.stdout, cached.stdout)

        # report what was verified (unittest itself prints only "ok" on success)
        if row["is_remote"]:
            commute = "n/a (remote)"
        elif row["commute_score"] is not None:
            commute = f"{row['commute_score']:.1f} min ({row['commute_address']})"
        else:
            commute = "office address not found"
        _log("verified persisted evaluation:")
        _log(f"    job_title      : {row['job_title']}")
        _log(f"    company        : {row['company']}")
        _log(f"    is_remote      : {bool(row['is_remote'])}")
        _log(f"    commute_score  : {commute}")
        _log(f"    compatibility  : {score}/100")
        _log(f"    criteria saved : {n_criteria}")
        _log(f"cache-hit run OK in {cache_secs:.1f}s (served from cache, no re-scrape/LLM)")

    def test_discover_smoke(self):
        """ run discover_jobs.py end to end and confirm it produces a candidate listing """
        if not RUN_DISCOVERY_SMOKE:
            self.skipTest(
                "discovery smoke test is opt-in (slow, scrapes live job boards): set "
                "RUN_DISCOVERY_SMOKE = True near the top of this file to run it"
            )
        result = subprocess.run(
            [sys.executable, "discover_jobs.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=PIPELINE_TIMEOUT_S,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # both the "N new job candidate(s):" and "No new job candidates found." paths match
        self.assertIn("job candidate", result.stdout.lower(), result.stdout)


if __name__ == "__main__":
    unittest.main()
