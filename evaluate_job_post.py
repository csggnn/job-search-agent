"""
CLI entrypoint: evaluate a single job posting by URL.

The pipeline itself lives in jobsearch.evaluation; this file only parses arguments so
that `python evaluate_job_post.py <url>` keeps working.
"""

import argparse

from jobsearch import config
from jobsearch.evaluation import evaluate_job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--force", action="store_true",
                        help="ignore any saved evaluation and force a fresh run")
    config.add_profile_argument(parser)
    args = parser.parse_args()
    profile = config.profile_from_args(args)
    evaluate_job(args.url, force=args.force, profile=profile)


if __name__ == "__main__":
    main()
