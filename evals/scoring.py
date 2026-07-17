"""
Eval scoring: per-case comparison against ground truth, aggregation into run metrics, and
diffs between two runs.

Criterion labels are classified into four disjoint sets: correct, wrong, stale_label (a
labeled name absent from the rubric), and unlabeled (a rubric name absent from ground
truth). Accuracy counts correct and wrong. A rubric rename moves labels into stale_label
and unlabeled, which are reported and excluded from accuracy.

Each scalar step reports an absolute error alongside its pass/fail result; aggregation
averages those into MAE. Pass-rate is constant for any result inside the tolerance band,
while absolute error varies across it.

The functions here are pure: no I/O, no network, no LLM calls.
"""

from jobsearch.config import FULLY_REMOTE


def score_criteria(expected_criteria, evaluated_criteria):
    """ compare name -> bool ground truth against evaluate_rubric() output.

        returns {"correct", "labeled", "wrong": [{name, expected, actual}],
                 "stale_labels": [...], "unlabeled": [...], "tp", "fp", "fn", "tn"}.
        "labeled" counts correct plus wrong. The positive class is a matched criterion.
    """
    actual = {c["name"]: bool(c["matched"]) for c in evaluated_criteria}
    expected = dict(expected_criteria or {})

    stale_labels = sorted(name for name in expected if name not in actual)
    unlabeled = sorted(name for name in actual if name not in expected)

    correct, wrong = 0, []
    tp = fp = fn = tn = 0
    for name, want in expected.items():
        if name in stale_labels:
            continue
        got = actual[name]
        if got == want:
            correct += 1
            tp += 1 if want else 0
            tn += 0 if want else 1
        else:
            wrong.append({"name": name, "expected": want, "actual": got})
            fp += 1 if got else 0
            fn += 1 if want else 0

    return {
        "correct": correct,
        "labeled": correct + len(wrong),
        "wrong": wrong,
        "stale_labels": stale_labels,
        "unlabeled": unlabeled,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def score_scalar(expected, actual, tolerance):
    """ compare a numeric result against ground truth within tolerance.

        an actual of None (e.g. a commute score for an unresolved address) fails with an
        abs_error of None, which aggregate() excludes from the MAE.
    """
    if actual is None:
        return {"expected": expected, "actual": None, "abs_error": None, "passed": False}
    abs_error = abs(actual - expected)
    return {
        "expected": expected,
        "actual": actual,
        "abs_error": abs_error,
        "passed": abs_error <= tolerance,
    }


def score_address(expected_contains, actual):
    """ check a resolved office address against ground truth.

        expected_contains is a substring, matched case-insensitively. The FULLY_REMOTE
        sentinel is compared by equality instead.
    """
    if expected_contains == FULLY_REMOTE:
        passed = actual == FULLY_REMOTE
    else:
        passed = actual is not None and expected_contains.lower() in actual.lower()
    return {"expected_contains": expected_contains, "actual": actual, "passed": passed}


def _scalar_metrics(results, extra_unresolved=False):
    """ pass-rate + MAE over the scored cases for one scalar step """
    scored = [r for r in results if r is not None]
    if not scored:
        return None
    errors = [r["abs_error"] for r in scored if r["abs_error"] is not None]
    metrics = {
        "n": len(scored),
        "mae": round(sum(errors) / len(errors), 2) if errors else None,
        "within_tolerance": sum(1 for r in scored if r["passed"]),
        "pass_rate": round(sum(1 for r in scored if r["passed"]) / len(scored), 2),
    }
    if extra_unresolved:
        metrics["unresolved"] = sum(1 for r in scored if r["actual"] is None)
    return metrics


def aggregate(case_results):
    """ turn per-case results into a run's "metrics" block """
    metrics = {
        "cases_total": len(case_results),
        "cases_scored": sum(1 for c in case_results if c.get("scored")),
        "cases_no_ad": sum(1 for c in case_results if c.get("skipped") == "no_ad"),
        "cases_undrafted": sum(1 for c in case_results if c.get("skipped") == "undrafted"),
        "cases_truncated": sum(1 for c in case_results
                               if c.get("skipped") == "truncated_ad"),
    }

    compat = _scalar_metrics([c.get("compatibility_score") for c in case_results])
    if compat:
        metrics["compatibility_score"] = compat

    commute = _scalar_metrics([c.get("commute_score") for c in case_results],
                              extra_unresolved=True)
    if commute:
        metrics["commute_score"] = commute

    days = [c["days_on_office"] for c in case_results if c.get("days_on_office")]
    if days:
        metrics["days_on_office"] = {
            "n": len(days),
            "exact": sum(1 for d in days if d["passed"]),
            "pass_rate": round(sum(1 for d in days if d["passed"]) / len(days), 2),
        }

    addresses = [c["address"] for c in case_results if c.get("address")]
    if addresses:
        metrics["address"] = {
            "n": len(addresses),
            "pass_rate": round(sum(1 for a in addresses if a["passed"]) / len(addresses), 2),
        }

    criteria = [c["criteria"] for c in case_results if c.get("criteria")]
    if criteria:
        tp = sum(c["tp"] for c in criteria)
        fp = sum(c["fp"] for c in criteria)
        fn = sum(c["fn"] for c in criteria)
        labeled = sum(c["labeled"] for c in criteria)
        correct = sum(c["correct"] for c in criteria)
        metrics["criteria"] = {
            "n_labels": labeled,
            "accuracy": round(correct / labeled, 3) if labeled else None,
            "precision": round(tp / (tp + fp), 3) if (tp + fp) else None,
            "recall": round(tp / (tp + fn), 3) if (tp + fn) else None,
            "tp": tp, "fp": fp, "fn": fn,
            "tn": sum(c["tn"] for c in criteria),
            "stale_labels": sum(len(c["stale_labels"]) for c in criteria),
            "unlabeled": sum(len(c["unlabeled"]) for c in criteria),
        }

    return metrics


# metric keys whose increase indicates improvement. Remaining numeric keys (MAE, error
# counts) indicate improvement when they decrease.
_HIGHER_IS_BETTER = ("accuracy", "precision", "recall", "pass_rate", "exact", "within_tolerance")


def _case_score(case):
    """ (passed_checks, total_checks) for one case's snapshot entry """
    passed = total = 0
    for step in ("compatibility_score", "commute_score", "days_on_office", "address"):
        if case.get(step):
            total += 1
            passed += 1 if case[step]["passed"] else 0
    if case.get("criteria"):
        total += case["criteria"]["labeled"]
        passed += case["criteria"]["correct"]
    return passed, total


def compare_runs(previous, current):
    """ diff two run snapshots.

        returns {"metrics_delta", "regressed", "improved", "only_in_previous",
        "only_in_current"}. Cases present in one run are reported under only_in_previous or
        only_in_current and excluded from the regressed/improved lists.
    """
    prev_cases = {c["name"]: c for c in previous.get("cases", [])}
    curr_cases = {c["name"]: c for c in current.get("cases", [])}

    regressed, improved = [], []
    for name in sorted(set(prev_cases) & set(curr_cases)):
        was_passed, was_total = _case_score(prev_cases[name])
        now_passed, now_total = _case_score(curr_cases[name])
        if was_total != now_total:
            # the case's check count changed, so the two pass counts are not comparable
            continue
        if now_passed < was_passed:
            regressed.append({"name": name, "was": was_passed, "now": now_passed, "of": now_total})
        elif now_passed > was_passed:
            improved.append({"name": name, "was": was_passed, "now": now_passed, "of": now_total})

    metrics_delta = {}
    for step, curr_metrics in (current.get("metrics") or {}).items():
        prev_metrics = (previous.get("metrics") or {}).get(step)
        if not isinstance(curr_metrics, dict) or not isinstance(prev_metrics, dict):
            continue
        for key, now in curr_metrics.items():
            was = prev_metrics.get(key)
            if not isinstance(now, (int, float)) or not isinstance(was, (int, float)):
                continue
            if now == was:
                continue
            metrics_delta[f"{step}.{key}"] = {
                "was": was,
                "now": now,
                "delta": round(now - was, 3),
                "better": (now > was) if key in _HIGHER_IS_BETTER else (now < was),
            }

    return {
        "metrics_delta": metrics_delta,
        "regressed": regressed,
        "improved": improved,
        "only_in_previous": sorted(set(prev_cases) - set(curr_cases)),
        "only_in_current": sorted(set(curr_cases) - set(prev_cases)),
    }
