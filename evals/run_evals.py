"""
Run the evals against the current pipeline and report per-step results.

Cases replay against stored ads rather than posting URLs. Three tiers select how much
of the pipeline runs:

    --criteria-only   regex over the stored description. No network, no LLM call.
    --no-commute      adds days_on_office and the compatibility judgment. 2 LLM calls/case.
    (default)         adds the address search and ORS routing.

Each run is written to evals/runs/ with the rubric hash and both model ids. --compare
diffs against an earlier one.

resolve_rubric() loads one rubric per run and does not compile. Compiling mid-run would
score cases in the same run against two rubrics.

Run with:
    python evals/run_evals.py [--criteria-only|--no-commute] [--verified-only] [--compare [PATH]]
"""

import argparse
import datetime
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals import dataset, scoring
from evals.capture import looks_truncated
from jobsearch import storage
from jobsearch.commute import commute_score as commute_score_fn, figure_days_on_office
from jobsearch.evaluation import compatibility_score
from jobsearch.llm import EXTRACTION_MODEL, RUBRIC_MODEL
from jobsearch.rubric import evaluate_rubric, load_rubric, match_text, rubric_is_stale

DEFAULT_TOLERANCE_SCORE = 10
# in weighted minutes. The commute accept/reject boundary spans roughly 10 minutes, so this
# band is narrower than the boundary it discriminates.
DEFAULT_TOLERANCE_COMMUTE = 5


def resolve_rubric():
    """ return (rubric, stale) for the run. exits if no rubric has been compiled. """
    rubric = load_rubric()
    if rubric is None:
        sys.exit("no compiled rubric - build one with: python scripts/recompile_rubric.py")
    stale = rubric_is_stale(rubric)
    if stale:
        print("WARNING: the rubric is stale - resume.md or job_preferences.md changed after it "
              "was compiled.\n         Scoring against the compiled rubric. Run "
              "scripts/recompile_rubric.py to score against the current files.\n")
    return rubric, stale


def run_case(case, rubric, tolerances, tier):
    """ replay one case against its ad and score it -> a run snapshot "cases" entry """
    result = {"name": case["name"], "verified": bool(case.get("verified"))}
    expected = case.get("expected") or {}

    if not dataset.has_ad(case):
        return {**result, "skipped": "no_ad"}
    if not expected:
        return {**result, "skipped": "undrafted"}
    dataset.validate_expected(case)

    post = dataset.case_post(case)
    if looks_truncated(post):
        # a login-wall ad matches no criteria and lowers every metric independently of
        # pipeline behavior
        return {**result, "skipped": "truncated_ad"}

    if "criteria" in expected:
        result["criteria"] = scoring.score_criteria(
            expected["criteria"],
            evaluate_rubric(rubric, match_text(post["job_title"], post["location"],
                                               post["description"])),
        )

    if tier == "criteria-only":
        result["scored"] = "criteria" in result
        return result

    if "compatibility_score" in expected:
        actual = compatibility_score(post["job_title"], post["company"], post["location"],
                                     post["description"], rubric=rubric)
        result["compatibility_score"] = scoring.score_scalar(
            expected["compatibility_score"], actual["compatibility_score"], tolerances["score"]
        )

    wants_commute = any(k in expected for k in ("address_contains", "commute_score"))
    if tier == "full" and wants_commute:
        commute = commute_score_fn(post["company"], post["location"], post["description"])
        if "days_on_office" in expected:
            result["days_on_office"] = scoring.score_scalar(
                expected["days_on_office"], commute["days_on_office"], 0
            )
        if "address_contains" in expected:
            result["address"] = scoring.score_address(expected["address_contains"],
                                                      commute["address"])
        if "commute_score" in expected:
            result["commute_score"] = scoring.score_scalar(
                expected["commute_score"], commute["score"], tolerances["commute"]
            )
    elif "days_on_office" in expected:
        # figure_days_on_office() reads the stored description alone, so it runs in tiers that
        # skip commute_score() and its address lookup
        result["days_on_office"] = scoring.score_scalar(
            expected["days_on_office"], int(figure_days_on_office(post["description"])), 0
        )

    result["scored"] = True
    return result


def write_snapshot(snapshot):
    """ write a run to evals/runs/<run_id>.json and return the path """
    os.makedirs(dataset.RUNS_DIR, exist_ok=True)
    path = os.path.join(dataset.RUNS_DIR, f"{snapshot['run_id']}.json")
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)
        f.write("\n")
    return path


def latest_run(exclude=None):
    """ (snapshot, path) of the most recent run in evals/runs/, or None. Ordered by filename,
        which is the run_id timestamp.
    """
    paths = sorted(glob.glob(os.path.join(dataset.RUNS_DIR, "*.json")))
    paths = [p for p in paths if p != exclude]
    if not paths:
        return None
    with open(paths[-1]) as f:
        return json.load(f), paths[-1]


def _print_case(case):
    if case.get("skipped"):
        reason = {
            "no_ad": "no ad captured",
            "undrafted": "no ground truth yet",
            "truncated_ad": "stored page text looks like a login wall, not the ad - "
                            "recapture it from the company's careers site",
        }
        print(f"[SKIP] {case['name']} ({reason[case['skipped']]})")
        return

    checks = []
    for step in ("compatibility_score", "commute_score", "days_on_office", "address"):
        if case.get(step):
            checks.append(case[step]["passed"])
    criteria = case.get("criteria")
    if criteria:
        checks.append(not criteria["wrong"])

    suffix = "" if case["verified"] else " (unverified)"
    print(f"[{'PASS' if all(checks) else 'FAIL'}] {case['name']}{suffix}")

    for step in ("compatibility_score", "commute_score"):
        r = case.get(step)
        if r and not r["passed"]:
            got = "unresolved" if r["actual"] is None else r["actual"]
            off = f" (off by {r['abs_error']})" if r["abs_error"] is not None else ""
            print(f"       - {step}: got {got}, expected {r['expected']}{off}")
    if case.get("days_on_office") and not case["days_on_office"]["passed"]:
        r = case["days_on_office"]
        print(f"       - days_on_office: got {r['actual']}, expected {r['expected']}")
    if case.get("address") and not case["address"]["passed"]:
        r = case["address"]
        print(f"       - address: got {r['actual']!r}, expected to contain "
              f"{r['expected_contains']!r}")
    if criteria:
        for w in criteria["wrong"]:
            expected_state = "match" if w["expected"] else "no match"
            actual_state = "match" if w["actual"] else "no match"
            print(f"       - criterion {w['name']!r}: expected {expected_state}, "
                  f"got {actual_state}")
        if criteria["stale_labels"]:
            print(f"       ! labels naming criteria absent from the rubric, excluded from "
                  f"accuracy: {criteria['stale_labels']}")
        if criteria["unlabeled"]:
            print(f"       ! rubric criteria with no label, excluded from accuracy: "
                  f"{criteria['unlabeled']}")


def _print_metrics(metrics):
    print("\n=== Metrics ===")
    compat = metrics.get("compatibility_score")
    if compat:
        print(f"  compatibility_score  MAE {compat['mae']}  "
              f"({compat['within_tolerance']}/{compat['n']} within tolerance)")
    commute = metrics.get("commute_score")
    if commute:
        unresolved = f", {commute['unresolved']} unresolved" if commute["unresolved"] else ""
        print(f"  commute_score        MAE {commute['mae']}  "
              f"({commute['within_tolerance']}/{commute['n']} within tolerance{unresolved})")
    days = metrics.get("days_on_office")
    if days:
        print(f"  days_on_office       {days['exact']}/{days['n']} exact")
    address = metrics.get("address")
    if address:
        print(f"  address              {round(address['pass_rate'] * 100)}% of {address['n']}")
    criteria = metrics.get("criteria")
    if criteria:
        # precision is undefined without positive predictions, recall without positive labels
        shown = {k: ("n/a" if criteria[k] is None else criteria[k])
                 for k in ("accuracy", "precision", "recall")}
        print(f"  criteria             accuracy {shown['accuracy']}  "
              f"precision {shown['precision']}  recall {shown['recall']}  "
              f"({criteria['n_labels']} labels)")
        if criteria["stale_labels"]:
            print(f"                       ! {criteria['stale_labels']} label(s) name criteria "
                  f"absent from the rubric; excluded from accuracy")
        if criteria["unlabeled"]:
            print(f"                       ! {criteria['unlabeled']} rubric criteria have no "
                  f"label; excluded from accuracy. Run: python evals/draft.py --all")


def _print_comparison(comparison, previous_path):
    print(f"\n=== Compared to {os.path.basename(previous_path)} ===")
    deltas = comparison["metrics_delta"]
    if not deltas:
        print("  no metric changed")
    for key, d in sorted(deltas.items()):
        arrow = "better" if d["better"] else "WORSE"
        sign = "+" if d["delta"] > 0 else ""
        print(f"  {key:<34} {d['was']} -> {d['now']}  ({sign}{d['delta']}, {arrow})")

    for label, entries in (("Regressed", comparison["regressed"]),
                           ("Improved", comparison["improved"])):
        if entries:
            print(f"\n  {label}:")
            for e in entries:
                print(f"    {e['name']}: {e['was']}/{e['of']} -> {e['now']}/{e['of']} checks")

    for label, names in (("only in the previous run", comparison["only_in_previous"]),
                         ("only in this run", comparison["only_in_current"])):
        if names:
            print(f"\n  Cases {label} (not compared): {names}")


def main():
    parser = argparse.ArgumentParser()
    tiers = parser.add_mutually_exclusive_group()
    tiers.add_argument("--criteria-only", action="store_true",
                       help="score only the regex criteria: no network, no cost")
    tiers.add_argument("--no-commute", action="store_true",
                       help="skip the live address search and routing")
    parser.add_argument("--verified-only", action="store_true",
                        help="only run cases with \"verified\": true")
    parser.add_argument("--tolerance-score", type=int, default=DEFAULT_TOLERANCE_SCORE,
                        help=f"compatibility_score tolerance (default {DEFAULT_TOLERANCE_SCORE})")
    parser.add_argument("--tolerance-commute", type=float, default=DEFAULT_TOLERANCE_COMMUTE,
                        help=f"commute_score tolerance in weighted minutes "
                             f"(default {DEFAULT_TOLERANCE_COMMUTE})")
    parser.add_argument("--compare", nargs="?", const=True, metavar="PATH",
                        help="diff against a run snapshot (default: the previous run)")
    args = parser.parse_args()

    tier = "criteria-only" if args.criteria_only else "no-commute" if args.no_commute else "full"
    tolerances = {"score": args.tolerance_score, "commute": args.tolerance_commute}

    rubric, stale = resolve_rubric()
    cases = dataset.load_cases()
    if args.verified_only:
        cases = [c for c in cases if c.get("verified")]
    if not cases:
        sys.exit("no cases to run" + (" with \"verified\": true - review a draft and flip it, "
                                      "see: python evals/draft.py --all" if args.verified_only
                                      else " - add one with: python evals/capture.py <url>"))

    print("=== Case results ===")
    case_results = []
    for case in cases:
        result = run_case(case, rubric, tolerances, tier)
        case_results.append(result)
        _print_case(result)

    metrics = scoring.aggregate(case_results)
    _print_metrics(metrics)

    snapshot = {
        "run_id": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "rubric_hash": storage.rubric_content_hash(rubric),
        "rubric_stale": stale,
        "rubric_criteria": [c["name"] for c in rubric["criteria"]],
        "extraction_model": EXTRACTION_MODEL,
        "rubric_model": RUBRIC_MODEL,
        "tolerances": tolerances,
        "scope": {"verified_only": args.verified_only, "tier": tier},
        "cases": case_results,
        "metrics": metrics,
    }
    path = write_snapshot(snapshot)

    if args.compare:
        found = None
        if args.compare is True:
            found = latest_run(exclude=path)
        elif os.path.exists(args.compare):
            with open(args.compare) as f:
                found = (json.load(f), args.compare)
        else:
            print(f"\nNo such run snapshot: {args.compare}")
        if found:
            previous, previous_path = found
            if previous.get("rubric_hash") != snapshot["rubric_hash"]:
                print("\nNote: the two runs used different rubrics. Criteria metrics are not "
                      "measuring the same set of criteria.")
            _print_comparison(scoring.compare_runs(previous, snapshot), previous_path)
        elif args.compare is True:
            print("\nNo previous run to compare against - this is the baseline.")

    scored = metrics["cases_scored"]
    unverified = sum(1 for c in case_results if not c["verified"] and not c.get("skipped"))
    print(f"\nScored {scored}/{metrics['cases_total']} case(s)"
          f"{f', {unverified} unverified' if unverified else ''}. Saved to {path}")


if __name__ == "__main__":
    main()
