"""
Maintenance utility: force-recompile the compatibility rubric from resume.md +
job_preferences.md, bypassing the file-hash cache.

The rubric normally recompiles itself inside evaluate_job() whenever those files change
(load_or_compile_rubric). Reach for this only to force a fresh build when the hash check
won't notice the reason — e.g. after swapping RUBRIC_MODEL, or to re-run drafting after a
prompt change. Prints a summary of the resulting criteria.

Run with: python scripts/recompile_rubric.py [--if-changed]
"""

import argparse

from jobsearch.rubric import compile_rubric, load_or_compile_rubric


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--if-changed", action="store_true",
                        help="only recompile if resume.md/job_preferences.md hashes changed "
                             "(same check evaluate_job() uses); otherwise force a fresh build")
    args = parser.parse_args()

    rubric = load_or_compile_rubric() if args.if_changed else compile_rubric()

    print(f"criteria: {len(rubric['criteria'])}")
    for c in rubric["criteria"]:
        tag = "DEALBREAKER" if c["type"] == "dealbreaker" else c["type"]
        print(f"  [{tag:>18}] w{c['weight']}  {c['name']}")
    guidance = rubric.get("scoring_guidance")
    print(f"scoring_guidance: {'set' if guidance else 'none'}")


if __name__ == "__main__":
    main()
