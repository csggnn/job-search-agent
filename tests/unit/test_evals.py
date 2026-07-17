"""
Offline unit tests for the eval harness's pure functions - no LLM, no network, no env, no
ads on disk:

    podman-compose exec job-search python3 -m unittest discover -s tests/unit -v

The rubric and criteria below are invented (widgets/night-shift), per the convention in
test_units.py: test code holds no candidate- or domain-specific content.
"""

import unittest
from unittest import mock

from evals import capture
from evals.capture import looks_truncated, upsert_case
from evals.dataset import usable_expected, validate_expected
from evals.scoring import (
    aggregate, compare_runs, score_address, score_criteria, score_scalar,
)
from jobsearch.config import FULLY_REMOTE


def _evaluated(**matched):
    """ evaluate_rubric()-shaped output: {name: matched} -> [{"name", "matched"}] """
    return [{"name": name, "matched": value} for name, value in matched.items()]


class ScoreCriteriaTest(unittest.TestCase):
    def test_splits_correct_from_wrong(self):
        result = score_criteria(
            {"widgets": True, "night-shift": False},
            _evaluated(widgets=True, **{"night-shift": True}),
        )
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["labeled"], 2)
        self.assertEqual(
            result["wrong"],
            [{"name": "night-shift", "expected": False, "actual": True}],
        )

    def test_stale_label_neither_passes_nor_counts(self):
        # the previous check tested for the absence of a name among the matched criteria, so a
        # label naming an absent criterion passed
        result = score_criteria(
            {"renamed-away": False, "widgets": True},
            _evaluated(widgets=True),
        )
        self.assertEqual(result["stale_labels"], ["renamed-away"])
        self.assertEqual(result["labeled"], 1, "a stale label is excluded from accuracy")
        self.assertEqual(result["correct"], 1)
        self.assertEqual(result["wrong"], [])

    def test_reports_rubric_criteria_with_no_label(self):
        result = score_criteria({"widgets": True}, _evaluated(widgets=True, gadgets=False))
        self.assertEqual(result["unlabeled"], ["gadgets"])
        self.assertEqual(result["labeled"], 1, "an unlabeled criterion is excluded from accuracy")

    def test_confusion_matrix(self):
        # widgets: want match, got match          -> tp
        # gadgets: want match, got none           -> fn
        # night-shift: want none, got match       -> fp
        # relocation: want none, got none         -> tn
        result = score_criteria(
            {"widgets": True, "gadgets": True, "night-shift": False, "relocation": False},
            _evaluated(widgets=True, gadgets=False, **{"night-shift": True, "relocation": False}),
        )
        self.assertEqual(
            (result["tp"], result["fp"], result["fn"], result["tn"]), (1, 1, 1, 1)
        )
        self.assertEqual(result["correct"], 2)

    def test_empty_ground_truth_scores_nothing(self):
        result = score_criteria({}, _evaluated(widgets=True))
        self.assertEqual(result["labeled"], 0)
        self.assertEqual(result["unlabeled"], ["widgets"])


class LooksTruncatedTest(unittest.TestCase):
    def test_flags_a_login_wall_teaser(self):
        # a login wall returns a post that validate_post() accepts, with the wall's teaser as
        # the description
        self.assertTrue(looks_truncated({
            "description": "Join or sign in to find your next job. Join to apply for the "
                           "Widget Inspector role at Acme.",
        }))

    def test_accepts_a_real_ad(self):
        self.assertFalse(looks_truncated({"description": "x" * 2000}))


class UpsertCaseTest(unittest.TestCase):
    """ the ad filename derives from the case name, so a blank name writes ".json" """

    def _upsert(self, cases, name, url):
        with mock.patch.object(capture.dataset, "save_ad", lambda n, ad: f"{n}.json"):
            return upsert_case(cases, name, url, {"post": {}})

    def test_blank_name_falls_back_to_the_captured_name(self):
        cases = [{"name": "", "url": "https://example.com/job/1", "ad": "", "expected": {}}]
        name, added = self._upsert(cases, "acme-widget-inspector", "https://example.com/job/1")
        self.assertFalse(added)
        self.assertEqual(name, "acme-widget-inspector")
        self.assertEqual(cases[0]["name"], "acme-widget-inspector")
        self.assertEqual(cases[0]["ad"], "acme-widget-inspector.json")

    def test_recorded_name_and_ground_truth_survive_recapture(self):
        cases = [{"name": "old-name", "url": "https://example.com/job/1",
                  "ad": "old-name.json", "expected": {"days_on_office": 3}}]
        name, added = self._upsert(cases, "new-slug", "https://example.com/job/1?trk=share")
        self.assertFalse(added)
        self.assertEqual(name, "old-name")
        self.assertEqual(cases[0]["expected"], {"days_on_office": 3})

    def test_unmatched_url_appends_a_case(self):
        cases = []
        name, added = self._upsert(cases, "acme-widget-inspector", "https://example.com/job/9")
        self.assertTrue(added)
        self.assertEqual(cases[0]["name"], "acme-widget-inspector")
        self.assertFalse(cases[0]["verified"])
        self.assertEqual(cases[0]["expected"], {})


class UsableExpectedTest(unittest.TestCase):
    def test_keeps_well_typed_ground_truth(self):
        expected = {
            "compatibility_score": 72,
            "days_on_office": 4,
            "commute_score": 41.2,
            "address_contains": "Metropolis",
            "criteria": {"widgets": True},
        }
        self.assertEqual(usable_expected(expected), expected)

    def test_drops_a_leftover_range(self):
        # the previous case format stored [lo, hi]. score_scalar() raises TypeError on
        # abs(actual - [0, 17]).
        self.assertEqual(usable_expected({"compatibility_score": [0, 17], "days_on_office": 4}),
                         {"days_on_office": 4})

    def test_drops_unknown_keys(self):
        self.assertEqual(usable_expected({"criteria_matched_contains": ["widgets"]}), {})

    def test_none_is_not_ground_truth(self):
        self.assertEqual(usable_expected({"commute_score": None}), {})

    def test_validate_names_the_unusable_keys(self):
        with self.assertRaises(ValueError) as caught:
            validate_expected({"name": "acme", "expected": {"compatibility_score": [0, 17]}})
        self.assertIn("compatibility_score", str(caught.exception))

    def test_validate_accepts_a_clean_case(self):
        validate_expected({"name": "acme", "expected": {"compatibility_score": 72}})


class ScoreScalarTest(unittest.TestCase):
    def test_passes_at_exactly_the_tolerance(self):
        self.assertTrue(score_scalar(70, 80, 10)["passed"])

    def test_fails_just_outside_the_tolerance(self):
        result = score_scalar(70, 81, 10)
        self.assertFalse(result["passed"])
        self.assertEqual(result["abs_error"], 11)

    def test_error_is_absolute_in_both_directions(self):
        self.assertEqual(score_scalar(70, 60, 10)["abs_error"], 10)

    def test_missing_actual_fails_with_no_error(self):
        # aggregate() excludes an abs_error of None from the MAE
        result = score_scalar(40, None, 5)
        self.assertFalse(result["passed"])
        self.assertIsNone(result["abs_error"])


class ScoreAddressTest(unittest.TestCase):
    def test_substring_matches_case_insensitively(self):
        self.assertTrue(score_address("metropolis", "12 Main St, Metropolis, Freedonia")["passed"])

    def test_substring_miss_fails(self):
        self.assertFalse(score_address("Gotham", "12 Main St, Metropolis, Freedonia")["passed"])

    def test_unresolved_address_fails(self):
        self.assertFalse(score_address("Metropolis", None)["passed"])

    def test_remote_is_equality_not_substring(self):
        self.assertTrue(score_address(FULLY_REMOTE, FULLY_REMOTE)["passed"])
        self.assertFalse(score_address(FULLY_REMOTE, "12 Main St, Metropolis")["passed"])


class AggregateTest(unittest.TestCase):
    def test_empty_run_does_not_divide_by_zero(self):
        metrics = aggregate([])
        self.assertEqual(metrics["cases_total"], 0)
        self.assertNotIn("criteria", metrics)

    def test_mae_averages_absolute_errors(self):
        metrics = aggregate([
            {"scored": True, "compatibility_score": score_scalar(70, 76, 10)},   # 6
            {"scored": True, "compatibility_score": score_scalar(50, 46, 10)},   # 4
        ])
        self.assertEqual(metrics["compatibility_score"]["mae"], 5.0)
        self.assertEqual(metrics["compatibility_score"]["pass_rate"], 1.0)

    def test_mae_excludes_unresolved_but_pass_rate_counts_it(self):
        metrics = aggregate([
            {"scored": True, "commute_score": score_scalar(40, 44, 5)},    # 4, passes
            {"scored": True, "commute_score": score_scalar(40, None, 5)},  # unresolved, fails
        ])
        self.assertEqual(metrics["commute_score"]["mae"], 4.0)
        self.assertEqual(metrics["commute_score"]["unresolved"], 1)
        self.assertEqual(metrics["commute_score"]["pass_rate"], 0.5)

    def test_criteria_precision_and_recall(self):
        # 2 cases, each tp=1 fp=1 fn=1 tn=1: precision 2/4, recall 2/4, accuracy 4/8
        case = {"scored": True, "criteria": score_criteria(
            {"widgets": True, "gadgets": True, "night-shift": False, "relocation": False},
            _evaluated(widgets=True, gadgets=False, **{"night-shift": True, "relocation": False}),
        )}
        metrics = aggregate([dict(case), dict(case)])
        self.assertEqual(metrics["criteria"]["n_labels"], 8)
        self.assertEqual(metrics["criteria"]["accuracy"], 0.5)
        self.assertEqual(metrics["criteria"]["precision"], 0.5)
        self.assertEqual(metrics["criteria"]["recall"], 0.5)

    def test_counts_skipped_cases_by_reason(self):
        metrics = aggregate([
            {"scored": True, "compatibility_score": score_scalar(70, 70, 10)},
            {"skipped": "no_ad"},
            {"skipped": "undrafted"},
        ])
        self.assertEqual(metrics["cases_scored"], 1)
        self.assertEqual(metrics["cases_no_ad"], 1)
        self.assertEqual(metrics["cases_undrafted"], 1)


class CompareRunsTest(unittest.TestCase):
    def _run(self, name, expected, actual, metrics=None):
        return {
            "cases": [{"name": name, "compatibility_score": score_scalar(expected, actual, 10)}],
            "metrics": metrics or {},
        }

    def test_detects_a_regression(self):
        result = compare_runs(self._run("acme", 70, 72), self._run("acme", 70, 95))
        self.assertEqual(result["regressed"], [{"name": "acme", "was": 1, "now": 0, "of": 1}])
        self.assertEqual(result["improved"], [])

    def test_detects_an_improvement(self):
        result = compare_runs(self._run("acme", 70, 95), self._run("acme", 70, 72))
        self.assertEqual(result["improved"], [{"name": "acme", "was": 0, "now": 1, "of": 1}])
        self.assertEqual(result["regressed"], [])

    def test_identical_runs_show_no_change(self):
        result = compare_runs(self._run("acme", 70, 72), self._run("acme", 70, 72))
        self.assertEqual(result["regressed"], [])
        self.assertEqual(result["improved"], [])
        self.assertEqual(result["metrics_delta"], {})

    def test_cases_in_only_one_run_are_listed_not_dropped(self):
        result = compare_runs(self._run("gone", 70, 72), self._run("added", 70, 72))
        self.assertEqual(result["only_in_previous"], ["gone"])
        self.assertEqual(result["only_in_current"], ["added"])
        self.assertEqual(result["regressed"], [])

    def test_metrics_delta_reports_direction_per_key(self):
        previous = self._run("acme", 70, 72, {"criteria": {"accuracy": 0.8},
                                              "compatibility_score": {"mae": 6.0}})
        current = self._run("acme", 70, 72, {"criteria": {"accuracy": 0.9},
                                             "compatibility_score": {"mae": 8.0}})
        delta = compare_runs(previous, current)["metrics_delta"]
        self.assertTrue(delta["criteria.accuracy"]["better"], "accuracy improves upward")
        self.assertFalse(delta["compatibility_score.mae"]["better"], "MAE improves downward")

    def test_ground_truth_shape_change_is_not_reported_as_a_regression(self):
        previous = {"cases": [{"name": "acme", "criteria": score_criteria(
            {"widgets": True}, _evaluated(widgets=True))}]}
        current = {"cases": [{"name": "acme", "criteria": score_criteria(
            {"widgets": True, "gadgets": True}, _evaluated(widgets=True, gadgets=True))}]}
        result = compare_runs(previous, current)
        self.assertEqual(result["regressed"], [])
        self.assertEqual(result["improved"], [])


if __name__ == "__main__":
    unittest.main()
