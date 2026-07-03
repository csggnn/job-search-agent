"""
Generate a draft eval case for cases.json from a job link, using whatever the pipeline
already computed and saved for that job (via storage.py's SQLite DB) as a starting point for
the case's "expected" ground truth. The draft is not meant to be trusted blindly - review and
hand-correct it (tighten/widen ranges, fix a wrong criterion substring, etc.) before relying
on it in run_evals.py. Every generated case is written with "verified": false; once you've
reviewed and, if needed, corrected a case's "expected" values by hand, flip that to true
yourself - it's how run_evals.py tells hand-verified ground truth apart from an unreviewed
draft.

Run with: python evals/add_case.py <url> [--name NAME] [--force]
Re-running against a url already present in cases.json updates that case's "expected"/"notes"
in place instead of creating a duplicate.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evaluate_job_post import evaluate_job
import storage

CASES_PATH = os.path.join(os.path.dirname(__file__), "cases.json")
SCORE_PADDING = 15
COMMUTE_SCORE_PADDING = 10  # minutes; absorbs routing-time variance, not just LLM score noise


def _slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_case(url, name):
    """ build a draft case dict for url from its already-saved evaluation + criteria (the
        caller must ensure url has been evaluated, e.g. via evaluate_job(), before calling this)
    """
    evaluation = storage.get_evaluation(url)
    criteria = storage.get_evaluation_criteria(url)

    expected = {
        "days_on_office": [evaluation["days_on_office"], evaluation["days_on_office"]],
    }
    if evaluation["commute_address"] not in (None, "Fully Remote"):
        expected["address_contains"] = evaluation["commute_address"]

    if evaluation["commute_score"] is not None:
        commute_score = evaluation["commute_score"]
        expected["commute_score"] = [
            max(0, round(commute_score - COMMUTE_SCORE_PADDING, 1)),
            round(commute_score + COMMUTE_SCORE_PADDING, 1),
        ]

    score = evaluation["compatibility_score"]
    expected["compatibility_score"] = [max(0, score - SCORE_PADDING), min(100, score + SCORE_PADDING)]

    matched = [c["name"] for c in criteria if c["matched"]]
    unmatched = [c["name"] for c in criteria if not c["matched"]]
    if matched:
        expected["criteria_matched_contains"] = matched
    if unmatched:
        expected["criteria_unmatched_contains"] = unmatched

    return {
        "name": name,
        "url": url,
        "verified": False,
        "notes": f"Draft generated from evaluate_job() on {evaluation['evaluated_at']}. "
                 "Review and adjust ground truth by hand.",
        "expected": expected,
    }


def find_case_index(cases, url):
    """ index of the case matching url (by normalized url) in cases, else None """
    normalized = storage.normalize_url(url)
    for i, case in enumerate(cases):
        if storage.normalize_url(case["url"]) == normalized:
            return i
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--name", help="case name for a NEW case; ignored when updating an "
                                        "existing case, which keeps its current name")
    parser.add_argument("--force", action="store_true", help="force a fresh evaluate_job() run")
    args = parser.parse_args()

    evaluate_job(args.url, force=args.force)  # ensures a saved evaluation (+ criteria) exists

    with open(CASES_PATH) as f:
        cases = json.load(f)

    existing_index = find_case_index(cases, args.url)
    if existing_index is not None:
        name = cases[existing_index]["name"]
        if args.name and args.name != name:
            print(f"Note: url already exists as case {name!r}; ignoring --name {args.name!r} "
                  "and keeping the existing name.")
    else:
        evaluation = storage.get_evaluation(args.url)
        name = args.name or _slugify(f"{evaluation['company']}-{evaluation['job_title']}")

    new_case = build_case(args.url, name)

    if existing_index is not None:
        cases[existing_index] = new_case
    else:
        cases.append(new_case)

    with open(CASES_PATH, "w") as f:
        json.dump(cases, f, indent=2)
        f.write("\n")

    print(f"{'Updated' if existing_index is not None else 'Added'} case {name!r} in {CASES_PATH}:")
    print(json.dumps(new_case, indent=2))


if __name__ == "__main__":
    main()
