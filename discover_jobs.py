"""
CLI entrypoint: discover new job ads.

The discovery pipeline lives in jobsearch.discovery; this file only parses arguments so
that `python discover_jobs.py` keeps working.
"""

import argparse

from jobsearch.discovery import discover_jobs, add_discovery_arguments
from jobsearch.preselection import DEFAULT_N


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluate", action="store_true",
                        help="run the full evaluate_job() pipeline on each pre-selected job ad")
    parser.add_argument("--limit", type=int, default=DEFAULT_N,
                        help="how many job ads pre-selection hands to evaluation "
                             f"(default {DEFAULT_N}); with --no-preselect, how many of the "
                             "discovered job ads are evaluated in discovery order")
    parser.add_argument("--no-preselect", action="store_true",
                        help="skip pre-selection (no LLM call) and take the discovered job ads "
                             "in discovery order")
    add_discovery_arguments(parser)
    args = parser.parse_args()
    discover_jobs(evaluate=args.evaluate, limit=args.limit, max_results_per_query=args.max_results,
                  force_queries=args.force, preselect_job_ads=not args.no_preselect,
                  linkedin_descriptions=not args.no_linkedin_descriptions, debug=args.debug)


if __name__ == "__main__":
    main()
