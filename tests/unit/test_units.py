"""
Offline unit tests for the pipeline's pure functions - no LLM, no network, no env.

These cover the deterministic helpers that the package refactor isolated into importable
modules (URL normalization, rubric hashing/application, markdown section extraction,
query validation, JSON-reply parsing):

    podman-compose exec job-search python3 -m unittest discover -s tests/unit -v
"""

import unittest

from jobsearch import storage
from jobsearch.config import extract_section
from jobsearch.rubric import evaluate_rubric, test_regex
from jobsearch.discovery import _validate_queries
from jobsearch.llm import _parse_json_reply


class NormalizeUrlTest(unittest.TestCase):
    def test_strips_tracking_params_and_trailing_slash_and_lowercases_host(self):
        self.assertEqual(
            storage.normalize_url("https://Example.com/Jobs/123/?utm_source=x&trk=y"),
            "https://example.com/Jobs/123",
        )

    def test_keeps_non_tracking_query_params(self):
        # some boards encode the job id in the query, so it must survive normalization
        self.assertEqual(
            storage.normalize_url("https://boards.example.com/apply?gh_jid=456"),
            "https://boards.example.com/apply?gh_jid=456",
        )

    def test_same_posting_under_different_tracking_links_dedupes(self):
        a = storage.normalize_url("https://x.com/j/9?utm_campaign=a&ref=linkedin")
        b = storage.normalize_url("https://x.com/j/9/?trk=feed&utm_campaign=b")
        self.assertEqual(a, b)


class RubricContentHashTest(unittest.TestCase):
    def test_stable_and_ignores_fields_outside_the_payload(self):
        base = {"criteria": [{"name": "alpha", "weight": 3}], "scoring_guidance": "notes"}
        with_extra = {**base, "resume_hash": "abc", "preferences_hash": "def"}
        self.assertEqual(
            storage.rubric_content_hash(base), storage.rubric_content_hash(with_extra)
        )

    def test_changes_when_criteria_change(self):
        a = {"criteria": [{"name": "alpha", "weight": 3}], "scoring_guidance": None}
        b = {"criteria": [{"name": "alpha", "weight": 4}], "scoring_guidance": None}
        self.assertNotEqual(storage.rubric_content_hash(a), storage.rubric_content_hash(b))

    def test_changes_when_scoring_guidance_changes(self):
        a = {"criteria": [], "scoring_guidance": "one"}
        b = {"criteria": [], "scoring_guidance": "two"}
        self.assertNotEqual(storage.rubric_content_hash(a), storage.rubric_content_hash(b))


class EvaluateRubricTest(unittest.TestCase):
    RUBRIC = {
        "criteria": [
            {"name": "want", "pattern": r"widgets?", "type": "requirement_match", "weight": 3},
            {"name": "avoid", "pattern": r"night-?shift", "type": "dealbreaker", "weight": 5},
        ]
    }

    def test_matched_requirement_scores_positive_weight(self):
        [want, avoid] = evaluate_rubric(self.RUBRIC, "We build widgets, standard hours")
        self.assertTrue(want["matched"])
        self.assertEqual(want["score"], 3)
        self.assertFalse(avoid["matched"])
        self.assertEqual(avoid["score"], 0)

    def test_matched_dealbreaker_scores_negative_weight(self):
        [want, avoid] = evaluate_rubric(self.RUBRIC, "Rotating night-shift, gadgets only")
        self.assertTrue(avoid["matched"])
        self.assertEqual(avoid["score"], -5)
        self.assertFalse(want["matched"])

    def test_matching_is_case_insensitive(self):
        [want, _] = evaluate_rubric(self.RUBRIC, "We ship WIDGETS daily")
        self.assertTrue(want["matched"])


class TestRegexToolTest(unittest.TestCase):
    def test_reports_matches(self):
        self.assertEqual(
            test_regex(r"\bwidget\b", "widget and widgets"),
            {"match_count": 1, "matches": ["widget"]},
        )

    def test_returns_error_for_invalid_pattern(self):
        self.assertIn("error", test_regex(r"(unclosed", "text"))


class ExtractSectionTest(unittest.TestCase):
    DOC = "# Title\n\n## Scoring Notes\nweigh criterion A heavily\n\n## Other\nignore me\n"

    def test_extracts_named_section_up_to_next_heading(self):
        self.assertEqual(extract_section(self.DOC, "Scoring Notes"), "weigh criterion A heavily")

    def test_missing_section_returns_none(self):
        self.assertIsNone(extract_section(self.DOC, "Nonexistent"))

    def test_extracts_last_section_to_end_of_document(self):
        self.assertEqual(extract_section(self.DOC, "Other"), "ignore me")


class ValidateQueriesTest(unittest.TestCase):
    # _validate_queries checks country against ^[a-z]{2}$ and location against the target list
    TARGETS = ["Metropolis, Freedonia"]

    def test_keeps_remote_queries_untouched(self):
        q = {"query": "some role", "is_remote": True, "location": None, "country": None}
        self.assertEqual(_validate_queries([q], self.TARGETS), [q])

    def test_keeps_valid_onsite_query_and_lowercases_country(self):
        q = {"query": "some role", "is_remote": False, "location": "Metropolis, Freedonia", "country": "XY"}
        [kept] = _validate_queries([q], self.TARGETS)
        self.assertEqual(kept["country"], "xy")

    def test_drops_onsite_query_with_untargeted_location(self):
        q = {"query": "some role", "is_remote": False, "location": "Gotham, Elbonia", "country": "zz"}
        self.assertEqual(_validate_queries([q], self.TARGETS), [])

    def test_drops_onsite_query_with_invalid_country_code(self):
        q = {"query": "some role", "is_remote": False, "location": "Metropolis, Freedonia", "country": "notacode"}
        self.assertEqual(_validate_queries([q], self.TARGETS), [])


class ParseJsonReplyTest(unittest.TestCase):
    def test_parses_fenced_json(self):
        self.assertEqual(_parse_json_reply('```json\n{"a": 1}\n```'), {"a": 1})

    def test_parses_json_embedded_in_prose(self):
        self.assertEqual(_parse_json_reply('Sure, here it is: {"a": 2} — done.'), {"a": 2})

    def test_parses_bare_json(self):
        self.assertEqual(_parse_json_reply('{"a": 3}'), {"a": 3})


if __name__ == "__main__":
    unittest.main()
