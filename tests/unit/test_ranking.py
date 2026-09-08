"""
Offline unit tests for jobsearch.ranking - the combined score, the ordering, and the
proposal cut. No LLM, no network, no database.

    podman-compose exec job-search python3 -m unittest discover -s tests/unit -v
"""

import unittest

from jobsearch.ranking import (
    commute_modifier, combined_score, rank_evaluations, propose, format_proposal,
    COMMUTE_NEUTRAL, COMMUTE_CUTOFF,
)


class CommuteModifierTest(unittest.TestCase):
    def test_anchors(self):
        # colinear at -0.5 points per weighted minute; float arithmetic, so compare loosely
        self.assertAlmostEqual(commute_modifier(0), 15)
        self.assertAlmostEqual(commute_modifier(COMMUTE_NEUTRAL), 0)
        self.assertAlmostEqual(commute_modifier(60), -15)
        self.assertAlmostEqual(commute_modifier(COMMUTE_CUTOFF), -25)

    def test_beyond_cutoff_is_none(self):
        self.assertIsNone(commute_modifier(COMMUTE_CUTOFF + 0.01))
        self.assertIsNone(commute_modifier(120))


class CombinedScoreTest(unittest.TestCase):
    def test_reproduces_the_four_anchors(self):
        self.assertEqual(combined_score(80, 0), 95)
        self.assertEqual(combined_score(80, 30), 80)
        self.assertEqual(combined_score(80, 60), 65)
        self.assertEqual(combined_score(80, 80), 55)

    def test_clamps_high(self):
        self.assertEqual(combined_score(95, 0), 100)

    def test_clamps_low(self):
        # modifier at 75 weighted min is 15 * (1 - 75/30) = -22.5
        self.assertEqual(combined_score(10, 75), 0)

    def test_cutoff_is_strict(self):
        self.assertEqual(combined_score(90, COMMUTE_CUTOFF), 65)
        self.assertEqual(combined_score(90, COMMUTE_CUTOFF + 1), 0)

    def test_missing_commute_passes_compatibility_through(self):
        self.assertEqual(combined_score(70, None), 70)


class RankEvaluationsTest(unittest.TestCase):
    def _row(self, compatibility, commute, **extra):
        return {"compatibility_score": compatibility, "commute_score": commute, **extra}

    def test_orders_by_descending_combined_score(self):
        rows = [
            self._row(70, 0, url="a"),    # 85
            self._row(90, 60, url="b"),   # 75
            self._row(80, 30, url="c"),   # 80
        ]
        self.assertEqual([e["url"] for e in rank_evaluations(rows)], ["a", "c", "b"])

    def test_computes_combined_score_ignoring_any_key_already_on_the_row(self):
        [ranked] = rank_evaluations([self._row(80, 30, combined_score=1)])
        self.assertEqual(ranked["combined_score"], 80)

    def test_flags_unknown_commute(self):
        [known, unknown] = rank_evaluations([self._row(80, 12), self._row(80, None)])
        self.assertTrue(known["commute_known"])
        self.assertFalse(unknown["commute_known"])

    def test_ties_break_on_compatibility_score(self):
        rows = [
            self._row(60, None, url="low"),   # 60
            self._row(75, 60, url="high"),    # 60
        ]
        self.assertEqual([e["url"] for e in rank_evaluations(rows)], ["high", "low"])


class ProposeTest(unittest.TestCase):
    def _row(self, compatibility, commute, status="new", **extra):
        return {"compatibility_score": compatibility, "commute_score": commute,
                "application_status": status, **extra}

    def test_returns_the_top_m_eligible_in_rank_order(self):
        rows = [
            self._row(90, 0, url="a"),
            self._row(50, 0, url="b"),
            self._row(70, 0, url="c"),
        ]
        result = propose(rows, 2)
        self.assertEqual([e["url"] for e in result["proposed"]], ["a", "c"])
        self.assertEqual(result["excluded"][0]["evaluation"]["url"], "b")
        self.assertEqual(result["excluded"][0]["reason"], "ranked below the top 2")

    def test_excludes_applied_and_discarded_with_the_status_as_reason(self):
        rows = [
            self._row(95, 0, status="applied", url="done"),
            self._row(40, 0, status="discarded", url="dropped"),
            self._row(60, 0, url="live"),
        ]
        result = propose(rows, 5)
        self.assertEqual([e["url"] for e in result["proposed"]], ["live"])
        reasons = {x["evaluation"]["url"]: x["reason"] for x in result["excluded"]}
        self.assertEqual(reasons, {"done": "applied", "dropped": "discarded"})

    def test_every_row_appears_exactly_once(self):
        rows = [self._row(i, 0, url=str(i)) for i in range(10)]
        result = propose(rows, 3)
        seen = [e["url"] for e in result["proposed"]] + \
               [x["evaluation"]["url"] for x in result["excluded"]]
        self.assertCountEqual(seen, [str(i) for i in range(10)])

    def test_proposes_fewer_than_m_when_too_few_are_eligible(self):
        result = propose([self._row(80, 0), self._row(70, 0, status="applied")], 5)
        self.assertEqual(len(result["proposed"]), 1)


class FormatProposalTest(unittest.TestCase):
    def test_renders_counts_and_reasons(self):
        rows = [
            {"compatibility_score": 90, "commute_score": 0, "application_status": "new",
             "job_title": "A", "company": "Co", "url": "u1"},
            {"compatibility_score": 60, "commute_score": None, "application_status": "new",
             "job_title": "B", "company": "Co", "url": "u2"},
            {"compatibility_score": 80, "commute_score": 0, "application_status": "applied",
             "job_title": "C", "company": "Co", "url": "u3"},
        ]
        text = format_proposal(propose(rows, 1), 1)
        self.assertIn("1 job(s) proposed out of 3 evaluated", text)
        self.assertIn("1 excluded as already applied to or discarded", text)
        self.assertIn("1 evaluated but ranked below the top 1", text)

    def test_omits_the_heading_line_when_no_heading_is_given(self):
        text = format_proposal(propose([], 3), 3)
        self.assertNotIn("===", text)

    def test_renders_the_heading_when_given(self):
        text = format_proposal(propose([], 3), 3, "Best of this run")
        self.assertIn("=== Best of this run ===", text)


if __name__ == "__main__":
    unittest.main()
