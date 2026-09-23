"""
CLI entrypoint: propose the N best-ranked jobs on the single combined fitness/commute score.

The default run discovers and pre-selects `N * --preselect-multiplier` job ads, evaluates
them, then prints two shortlists: the top N over every saved evaluation, and the top N over
just the jobs evaluated in this run. A job good enough to reach both appears in both.
`--no-discover` skips search and evaluation, leaving only the first shortlist.

The pipeline itself lives in jobsearch.discovery and jobsearch.ranking; this file only
parses arguments and picks the pools to rank.
"""

import argparse

from jobsearch import storage
from jobsearch.discovery import discover_jobs, add_discovery_arguments
from jobsearch.ranking import propose, format_proposal

DEFAULT_PRESELECT_MULTIPLIER = 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("n", type=int, help="how many jobs to propose")
    parser.add_argument("--preselect-multiplier", type=int, default=DEFAULT_PRESELECT_MULTIPLIER,
                        help="discover, pre-select and evaluate this many times N job ads "
                             f"before ranking (default {DEFAULT_PRESELECT_MULTIPLIER})")
    parser.add_argument("--no-discover", action="store_true",
                        help="skip discovery and evaluation; rank the saved evaluations as they "
                             "are, printing the overall shortlist only")
    add_discovery_arguments(parser)
    args = parser.parse_args()

    if args.n < 1:
        parser.error("n must be >= 1")
    if args.preselect_multiplier < 1:
        parser.error("--preselect-multiplier must be >= 1")

    fresh = []
    if not args.no_discover:
        fresh = discover_jobs(
            evaluate=True,
            limit=args.n * args.preselect_multiplier,
            max_results_per_query=args.max_results,
            force_queries=args.force,
            preselect_job_ads=True,
            debug=args.debug,
        )

    pools = [("Best overall", storage.list_evaluations())]
    if not args.no_discover:
        pools.append(("Best of this run", fresh))
    for heading, pool in pools:
        print(format_proposal(propose(pool, args.n), args.n, heading))


if __name__ == "__main__":
    main()
