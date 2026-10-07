"""
CLI entrypoint: evaluate a single job posting by URL.

The pipeline itself lives in jobsearch.evaluation; this file parses arguments and checks
that user data exists, so that `python evaluate_job_post.py <url>` keeps working.
"""

import argparse

from jobsearch import config
from jobsearch.evaluation import evaluate_job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--force", action="store_true",
                        help="ignore any saved evaluation and force a fresh run")
    args = parser.parse_args()
    config.require_data()
    evaluate_job(args.url, force=args.force)


if __name__ == "__main__":
    main()
