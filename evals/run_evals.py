"""
Eval harness: runs evaluate_job_post functions against known job postings and checks
results against expected ranges/substrings. LLM outputs vary run to run, so checks use
ranges rather than exact equality wherever a score is involved - a case that only passes
under exact equality will be flaky, not correct.

Results are aggregated by pipeline step (days_on_office / address / commute_score /
compatibility_score / criteria_matched / criteria_unmatched), not just by case, so the step
causing the most failures across all cases is obvious - that's the function to spend time on
next, rather than chasing one case at a time. criteria_matched/criteria_unmatched check
substrings against the names of matched rubric criteria, separately from the final
compatibility_score, so a regex-detection regression can be told apart from a final-scoring
regression. commute_score is checked separately from days_on_office/address so a bug in the
weighted-commute-time arithmetic itself (commute.commute_score's 1.5x/3-4-day/prorated
formula) can be told apart from a bad days_on_office or address extraction feeding into it.

Run with: python evals/run_evals.py
Add cases with: python evals/add_case.py <url> - generates a draft case from what the
pipeline actually computed for that job (via storage.py), for you to review/correct by hand.
See existing entries in cases.json for the expected shape.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evaluate_job_post import compatibility_score, scrape_post
from commute import commute_score as commute_score_fn

CASES_PATH = os.path.join(os.path.dirname(__file__), "cases.json")


def check_case(case):
    """ run one eval case, returning per-step results: [{"step", "passed", "detail"}] """
    post = scrape_post(case["url"])
    expected = case["expected"]
    results = []

    needs_commute = any(
        key in expected for key in ("days_on_office", "address_contains", "commute_score")
    )
    if needs_commute:
        commute = commute_score_fn(post["company"], post["location"], post["description"])

        if "days_on_office" in expected:
            actual = commute["days_on_office"]
            lo, hi = expected["days_on_office"]
            passed = lo <= actual <= hi
            results.append({
                "step": "days_on_office",
                "passed": passed,
                "detail": None if passed else f"got {actual}, expected {lo}-{hi}",
            })

        if "address_contains" in expected:
            address = commute["address"]
            passed = expected["address_contains"] in (address or "")
            results.append({
                "step": "address",
                "passed": passed,
                "detail": None if passed else f"got {address!r}, expected to contain {expected['address_contains']!r}",
            })

        if "commute_score" in expected:
            actual = commute["score"]
            lo, hi = expected["commute_score"]
            passed = actual is not None and lo <= actual <= hi
            results.append({
                "step": "commute_score",
                "passed": passed,
                "detail": None if passed else f"got {actual}, expected {lo}-{hi}",
            })

    needs_compatibility = any(
        key in expected
        for key in ("compatibility_score", "criteria_matched_contains", "criteria_unmatched_contains")
    )
    if needs_compatibility:
        result = compatibility_score(post["job_title"], post["company"], post["description"])

        if "compatibility_score" in expected:
            actual = result["compatibility_score"]
            lo, hi = expected["compatibility_score"]
            passed = lo <= actual <= hi
            results.append({
                "step": "compatibility_score",
                "passed": passed,
                "detail": None if passed else f"got {actual}, expected {lo}-{hi}",
            })

        matched_names = [c["name"] for c in result["criteria"] if c["matched"]]

        for substring in expected.get("criteria_matched_contains", []):
            passed = any(substring.lower() in name.lower() for name in matched_names)
            results.append({
                "step": "criteria_matched",
                "passed": passed,
                "detail": None if passed else
                    f"expected a matched criterion containing {substring!r}, matched criteria were {matched_names}",
            })

        for substring in expected.get("criteria_unmatched_contains", []):
            passed = not any(substring.lower() in name.lower() for name in matched_names)
            results.append({
                "step": "criteria_unmatched",
                "passed": passed,
                "detail": None if passed else
                    f"expected no matched criterion containing {substring!r}, but found one in {matched_names}",
            })

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verified-only", action="store_true",
                         help="only run cases with \"verified\": true")
    args = parser.parse_args()

    with open(CASES_PATH) as f:
        cases = json.load(f)

    if args.verified_only:
        cases = [c for c in cases if c.get("verified", False)]

    per_case = []
    step_stats = {}
    for case in cases:
        name = case.get("name", case["url"])
        verified = case.get("verified", False)
        results = check_case(case)
        per_case.append((name, verified, results))
        for r in results:
            stats = step_stats.setdefault(r["step"], {"passed": 0, "failed": 0, "failures": []})
            if r["passed"]:
                stats["passed"] += 1
            else:
                stats["failed"] += 1
                stats["failures"].append((name, r["detail"]))

    print("=== Case results ===")
    for name, verified, results in per_case:
        case_passed = all(r["passed"] for r in results)
        suffix = "" if verified else " (unverified)"
        print(f"[{'PASS' if case_passed else 'FAIL'}] {name}{suffix}")
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

    passed_cases = sum(1 for _, _, results in per_case if all(r["passed"] for r in results))
    unverified_cases = sum(1 for _, verified, _ in per_case if not verified)
    print(f"\n{passed_cases}/{len(cases)} cases fully passed ({unverified_cases} unverified)")


if __name__ == "__main__":
    main()
