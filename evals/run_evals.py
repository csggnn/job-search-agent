"""
Eval harness: runs evaluate_job_post functions against known job postings and checks
results against expected ranges/substrings. LLM outputs vary run to run, so checks use
ranges rather than exact equality wherever a score is involved - a case that only passes
under exact equality will be flaky, not correct.

Run with: python evals/run_evals.py
Add cases by appending to cases.json - see existing entries for the expected shape.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evaluate_job_post import compatibility_score, figure_address, figure_days_on_office, scrape_post

CASES_PATH = os.path.join(os.path.dirname(__file__), "cases.json")


def check_case(case):
    """ run one eval case, returning (passed, [failure messages]) """
    post = scrape_post(case["url"])
    expected = case["expected"]
    failures = []

    if "days_on_office" in expected:
        actual = int(figure_days_on_office(post["description"]))
        lo, hi = expected["days_on_office"]
        if not (lo <= actual <= hi):
            failures.append(f"days_on_office={actual}, expected {lo}-{hi}")

    if "address_contains" in expected:
        address = figure_address(post["company"], post["location"])
        if expected["address_contains"] not in (address or ""):
            failures.append(f"address={address!r}, expected to contain {expected['address_contains']!r}")

    if "compatibility_score" in expected:
        result = compatibility_score(post["job_title"], post["company"], post["description"])
        actual = result["compatibility_score"]
        lo, hi = expected["compatibility_score"]
        if not (lo <= actual <= hi):
            failures.append(f"compatibility_score={actual}, expected {lo}-{hi}")

    return not failures, failures


def main():
    with open(CASES_PATH) as f:
        cases = json.load(f)

    passed_count = 0
    for case in cases:
        passed, failures = check_case(case)
        print(f"[{'PASS' if passed else 'FAIL'}] {case['name']}")
        for failure in failures:
            print(f"       - {failure}")
        passed_count += passed

    print(f"\n{passed_count}/{len(cases)} passed")


if __name__ == "__main__":
    main()
