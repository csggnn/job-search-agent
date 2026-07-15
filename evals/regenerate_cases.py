"""
Bulk-regenerate cases.json from live evaluate_job() runs: every URL currently in cases.json,
plus any URL already saved in storage.py's DB but not yet represented as a case. Each case is
rebuilt from scratch (same shape as add_case.build_case()) - existing "expected" values and
hand-written notes are discarded in favor of a fresh, unverified draft ("verified": false), so
review the regenerated cases.json afterward and re-verify/hand-correct as needed.

Backs up the current cases.json to cases.json.bak before writing anything.

On a failed evaluate_job() call for a URL (e.g. a transient scrape failure), retries once;
if the retry also fails, that URL's existing case (if any) is left untouched and the URL is
reported as skipped at the end - one bad job doesn't abort the whole batch.

Run with: python evals/regenerate_cases.py
"""

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jobsearch.evaluation import evaluate_job
from add_case import build_case, _slugify
from jobsearch import storage

CASES_PATH = os.path.join(os.path.dirname(__file__), "cases.json")
BACKUP_PATH = os.path.join(os.path.dirname(__file__), "cases.json.bak")


def evaluate_with_retry(url):
    """ evaluate_job(url, force=True), retrying once on failure. Returns True on success,
        False if both attempts failed.
    """
    for attempt in range(2):
        try:
            evaluate_job(url, force=True)
            return True
        except Exception as e:
            print(f"  attempt {attempt + 1} failed for {url}: {e}")
    return False


def main():
    shutil.copyfile(CASES_PATH, BACKUP_PATH)
    print(f"Backed up {CASES_PATH} to {BACKUP_PATH}")

    with open(CASES_PATH) as f:
        cases = json.load(f)

    known_urls = {storage.normalize_url(c["url"]): c["url"] for c in cases}

    for url, normalized_url in storage.list_evaluated_urls():
        known_urls.setdefault(normalized_url, url)

    regenerated, skipped = [], []
    new_cases = list(cases)

    for normalized_url, url in known_urls.items():
        existing_index = next(
            (i for i, c in enumerate(new_cases) if storage.normalize_url(c["url"]) == normalized_url),
            None,
        )
        print(f"Evaluating {url} ...")
        if not evaluate_with_retry(url):
            print(f"  skipping {url} (kept previous case unchanged, if any)")
            skipped.append(url)
            continue

        evaluation = storage.get_evaluation(url)
        if existing_index is not None:
            name = new_cases[existing_index]["name"]
        else:
            name = _slugify(f"{evaluation['company']}-{evaluation['job_title']}")

        new_case = build_case(url, name)
        if existing_index is not None:
            new_cases[existing_index] = new_case
        else:
            new_cases.append(new_case)
        regenerated.append(name)

    with open(CASES_PATH, "w") as f:
        json.dump(new_cases, f, indent=2)
        f.write("\n")

    print(f"\nRegenerated {len(regenerated)} case(s): {regenerated}")
    if skipped:
        print(f"Skipped {len(skipped)} url(s) after a failed retry: {skipped}")
    print(f"\n{CASES_PATH} now has {len(new_cases)} case(s), all freshly regenerated cases "
          "marked \"verified\": false - review and re-verify by hand.")


if __name__ == "__main__":
    main()
