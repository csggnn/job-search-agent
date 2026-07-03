"""
Eval harness: runs evaluate_job_post functions against known job postings and checks
results against expected ranges/substrings. LLM outputs vary run to run, so checks use
ranges rather than exact equality wherever a score is involved - a case that only passes
under exact equality will be flaky, not correct.

Results are aggregated by pipeline step (days_on_office / address / compatibility_score),
not just by case, so the step causing the most failures across all cases is obvious - that's
the function to spend time on next, rather than chasing one case at a time.

Run with: python evals/run_evals.py
Add cases by appending to cases.json - see existing entries for the expected shape.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evaluate_job_post import compatibility_score, scrape_post
from commute import figure_address, figure_days_on_office

CASES_PATH = os.path.join(os.path.dirname(__file__), "cases.json")


def check_case(case):
    """ run one eval case, returning per-step results: [{"step", "passed", "detail"}] """
    post = scrape_post(case["url"])
    expected = case["expected"]
    results = []

    if "days_on_office" in expected:
        actual = int(figure_days_on_office(post["description"]))
        lo, hi = expected["days_on_office"]
        passed = lo <= actual <= hi
        results.append({
            "step": "days_on_office",
            "passed": passed,
            "detail": None if passed else f"got {actual}, expected {lo}-{hi}",
        })

    if "address_contains" in expected:
        address = figure_address(post["company"], post["location"])
        passed = expected["address_contains"] in (address or "")
        results.append({
            "step": "address",
            "passed": passed,
            "detail": None if passed else f"got {address!r}, expected to contain {expected['address_contains']!r}",
        })

    if "compatibility_score" in expected:
        result = compatibility_score(post["job_title"], post["company"], post["description"])
        actual = result["compatibility_score"]
        lo, hi = expected["compatibility_score"]
        passed = lo <= actual <= hi
        results.append({
            "step": "compatibility_score",
            "passed": passed,
            "detail": None if passed else f"got {actual}, expected {lo}-{hi}",
        })

    return results


def main():
    with open(CASES_PATH) as f:
        cases = json.load(f)

    per_case = []
    step_stats = {}
    for case in cases:
        name = case.get("name", case["url"])
        results = check_case(case)
        per_case.append((name, results))
        for r in results:
            stats = step_stats.setdefault(r["step"], {"passed": 0, "failed": 0, "failures": []})
            if r["passed"]:
                stats["passed"] += 1
            else:
                stats["failed"] += 1
                stats["failures"].append((name, r["detail"]))

    print("=== Case results ===")
    for name, results in per_case:
        case_passed = all(r["passed"] for r in results)
        print(f"[{'PASS' if case_passed else 'FAIL'}] {name}")
        for r in results:
            if not r["passed"]:
                print(f"       - {r['step']}: {r['detail']}")

    print("\n=== Step summary (worst first) ===")
    ranked = sorted(step_stats.items(), key=lambda kv: kv[1]["failed"], reverse=True)
    for step, stats in ranked:
        total = stats["passed"] + stats["failed"]
        rate = stats["failed"] / total * 100
        print(f"  {step:<20} {stats['passed']}/{total} passed  ({rate:.0f}% failing)")

    worst_step, worst_stats = ranked[0] if ranked else (None, None)
    if worst_stats and worst_stats["failed"] > 0:
        total = worst_stats["passed"] + worst_stats["failed"]
        print(f"\n>>> Optimize next: '{worst_step}' ({worst_stats['failed']}/{total} cases failing here)")
        for case_name, detail in worst_stats["failures"]:
            print(f"      {case_name}: {detail}")
    else:
        print("\nAll steps passing.")

    passed_cases = sum(1 for _, results in per_case if all(r["passed"] for r in results))
    print(f"\n{passed_cases}/{len(cases)} cases fully passed")


if __name__ == "__main__":
    main()
