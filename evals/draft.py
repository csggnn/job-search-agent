"""
Pre-fill a case's ground truth with the values the current pipeline computes for its ad.

A drafted value reproduces current pipeline output, which is the subject of the evaluation.
Drafting writes "verified": false on every case it fills. run_evals.py --verified-only
excludes those cases until the field is set to true by hand.

A re-draft retains existing values for criteria present in the rubric and fills the rest. A
rubric recompile that adds criteria therefore leaves reviewed values intact. --force
discards existing values.

Drafting reads ads and writes cases.json. It calls no storage function and does not
open data/evaluations.db.

Run with:
    python evals/draft.py <url|NAME>   # captures an ad if the url has none
    python evals/draft.py --all        # every case with incomplete ground truth
    python evals/draft.py --force ...  # re-draft, discarding existing values
"""

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals import capture, dataset
from jobsearch.commute import commute_score
from jobsearch.config import FULLY_REMOTE
from jobsearch.evaluation import compatibility_score
from jobsearch.rubric import evaluate_rubric, load_rubric, rubric_is_stale


def draft_criteria(rubric, description, previous=None):
    """ pre-fill name -> bool criteria labels by applying the rubric to a description.

        a name present in `previous` keeps its value; the remaining names are filled from
        evaluate_rubric(). returns (criteria_map, filled_names). Pure: regex only.
    """
    previous = previous or {}
    criteria, filled = {}, []
    for evaluated in evaluate_rubric(rubric, description):
        name = evaluated["name"]
        if name in previous:
            criteria[name] = previous[name]
        else:
            criteria[name] = bool(evaluated["matched"])
            filled.append(name)
    return criteria, filled


def draft_expected(post, rubric, previous=None):
    """ pre-fill a case's "expected" block from its ad's post.

        issues one commute_score() call, supplying days_on_office, address_contains and
        commute_score, and one compatibility_score() call. The criteria labels use regex
        alone. returns (expected, filled_names).
    """
    previous = previous or {}
    expected = {}
    filled = []

    criteria, criteria_filled = draft_criteria(rubric, post["description"],
                                               previous=previous.get("criteria"))
    expected["criteria"] = criteria
    filled.extend(criteria_filled)

    commute = commute_score(post["company"], post["location"], post["description"])
    if "days_on_office" in previous:
        expected["days_on_office"] = previous["days_on_office"]
    else:
        expected["days_on_office"] = commute["days_on_office"]
        filled.append("days_on_office")

    if commute["address"] == FULLY_REMOTE:
        # score_address() compares the FULLY_REMOTE sentinel by equality
        expected["address_contains"] = previous.get("address_contains", FULLY_REMOTE)
        expected["commute_score"] = previous.get("commute_score", 0)
        if "address_contains" not in previous:
            filled.extend(["address_contains", "commute_score"])
    elif commute["address"] is None:
        # the address did not resolve. address_contains and commute_score stay unset rather
        # than recording the unresolved result as ground truth.
        pass
    else:
        if "address_contains" in previous:
            expected["address_contains"] = previous["address_contains"]
        else:
            expected["address_contains"] = commute["address"]
            filled.append("address_contains")
        if "commute_score" in previous:
            expected["commute_score"] = previous["commute_score"]
        else:
            expected["commute_score"] = round(commute["score"], 1)
            filled.append("commute_score")

    if "compatibility_score" in previous:
        expected["compatibility_score"] = previous["compatibility_score"]
    else:
        compatibility = compatibility_score(post["job_title"], post["company"],
                                            post["description"], rubric=rubric)
        expected["compatibility_score"] = compatibility["compatibility_score"]
        filled.append("compatibility_score")

    return expected, filled


def _is_incomplete(case, rubric):
    """ True if the case is missing ground truth that drafting could fill """
    expected = case.get("expected") or {}
    if not expected:
        return True
    if dataset.usable_expected(expected) != expected:
        return True
    labeled = expected.get("criteria") or {}
    return any(c["name"] not in labeled for c in rubric["criteria"])


def _note_for(case, filled):
    today = datetime.date.today().isoformat()
    hints = []
    if "address_contains" in filled and case["expected"].get("address_contains") != FULLY_REMOTE:
        # draft.py fills address_contains with the full resolved address
        hints.append("reduce address_contains to a distinctive substring")
    hint = f" Review: {', '.join(hints)}." if hints else ""
    return (f"Drafted {today}: {len(filled)} pre-filled value(s), not reviewed.{hint}")


def _draft_case(case, rubric, force):
    """ draft one case in place; returns the list of pre-filled keys """
    post = dataset.case_post(case)
    # usable_expected() omits values outside EXPECTED_TYPES, so a [lo, hi] range from the
    # previous case format is refilled rather than carried forward
    previous = None if force else dataset.usable_expected(case.get("expected"))
    expected, filled = draft_expected(post, rubric, previous=previous)
    case["expected"] = expected
    if filled:
        # the case holds pre-filled values, so its reviewed state no longer applies
        case["verified"] = False
        case["notes"] = _note_for(case, filled)
    return filled


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", help="a case NAME, or a posting url to capture")
    parser.add_argument("--all", action="store_true",
                        help="draft every case with incomplete ground truth")
    parser.add_argument("--force", action="store_true",
                        help="re-draft from scratch, discarding human labels")
    args = parser.parse_args()

    if not args.target and not args.all:
        parser.error("give a case NAME, a url, or --all")

    rubric = load_rubric()
    if rubric is None:
        sys.exit("no compiled rubric - build one with: python scripts/recompile_rubric.py")
    if rubric_is_stale(rubric):
        print("WARNING: the rubric is stale (resume.md/job_preferences.md changed since it was "
              "compiled).\n         Drafting against the old rubric; recompile first with "
              "scripts/recompile_rubric.py\n")

    cases = dataset.load_cases()

    if args.all:
        targets = [c for c in cases if dataset.has_ad(c)
                   and (args.force or _is_incomplete(c, rubric))]
        no_ad = [c["name"] for c in cases if not dataset.has_ad(c)]
        if no_ad:
            print(f"Skipping {len(no_ad)} case(s) with no ad: {no_ad}\n")
        if not targets:
            print("Every case with an ad already has complete ground truth. "
                  "Use --force to re-draft.")
            return
    else:
        index = dataset.find_case(cases, name=args.target, url=args.target)
        if index is None:
            if not args.target.startswith("http"):
                sys.exit(f"no case named {args.target!r} - capture one with: "
                         f"python evals/capture.py <url>")
            print(f"No case for {args.target} yet - capturing it first ...")
            name, ad = capture.capture(args.target)
            name, _ = capture.upsert_case(cases, name, args.target, ad)
            index = dataset.find_case(cases, name=name, url=args.target)
        targets = [cases[index]]

    drafted = 0
    for case in targets:
        print(f"Drafting {case['name']} ...")
        try:
            filled = _draft_case(case, rubric, args.force)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            continue
        drafted += 1
        print(f"  pre-filled {len(filled)}: {filled}" if filled else "  nothing to fill")
        dataset.save_cases(cases)

    print(f"\nDrafted {drafted} case(s) into {dataset.CASES_PATH}, all \"verified\": false.\n"
          "Next: review the expected values by hand, then set \"verified\": true on the ones "
          "you trust.\nOnly verified cases count under: python evals/run_evals.py --verified-only")


if __name__ == "__main__":
    main()
