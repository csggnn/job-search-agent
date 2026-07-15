"""
CLI entrypoint: discover new candidate job postings.

The discovery pipeline lives in jobsearch.discovery; this file only parses arguments so
that `python discover_jobs.py` keeps working.
"""

import argparse

from jobsearch.discovery import discover_jobs, DEFAULT_MAX_RESULTS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluate", action="store_true",
                        help="run the full evaluate_job() pipeline on each new candidate")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap how many new candidates get evaluated when --evaluate is set")
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS,
                        help="max JobSpy results to keep per query")
    parser.add_argument("--force", action="store_true",
                        help="ignore the cached search queries and recompile them")
    parser.add_argument("--debug", action="store_true", help="print intermediate search details")
    args = parser.parse_args()
    discover_jobs(evaluate=args.evaluate, limit=args.limit, max_results_per_query=args.max_results,
                  force_queries=args.force, debug=args.debug)


if __name__ == "__main__":
    main()
