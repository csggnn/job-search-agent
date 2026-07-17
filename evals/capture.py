"""
Capture a job posting's inputs into a stored ad for replay by the eval harness.

A stored ad holds the raw page text returned by Tavily and the structured post extracted
from it. --re-extract regenerates the post from the stored raw text with one LLM call and
no fetch, including for URLs that no longer resolve.

Capture writes no ground truth. A new case is created with an empty "expected" block, which
evals/draft.py fills.

Run with:
    python evals/capture.py <url> [<url> ...] [--name NAME]
    python evals/capture.py --list-candidates            # print the eval set
    python evals/capture.py --from-cases NAME [NAME ...] # capture named existing cases
    python evals/capture.py --re-extract NAME | --all    # rebuild post from stored raw text
"""

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals import dataset
from jobsearch import storage
from jobsearch.llm import EXTRACTION_MODEL
from jobsearch.scrape import extract_post, fetch_page_text


# A job board serving a login wall returns a post with a populated job_title and company and
# a description holding the wall's teaser text. validate_post() accepts such a post. A
# description of that length matches no rubric criteria, and figure_days_on_office() returns
# its 5-day fallback. Observed lengths: job ads 2000-4700 chars, login walls 200-450 chars.
MIN_DESCRIPTION_CHARS = 600


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def looks_truncated(post):
    """ True if a post's description is below MIN_DESCRIPTION_CHARS """
    return len(post["description"]) < MIN_DESCRIPTION_CHARS


def capture(url, name=None):
    """ fetch a posting and build its ad. returns (name, ad).
        name defaults to a slug of the posting's company + title.
    """
    page_text = fetch_page_text(url)
    post = extract_post(page_text, source=url)
    name = name or dataset.slugify(f"{post['company']}-{post['job_title']}")
    ad = {
        "url": url,
        "normalized_url": storage.normalize_url(url),
        "captured_at": _now(),
        "extraction_model": EXTRACTION_MODEL,
        "extracted_at": _now(),
        "raw_content": page_text,
        "post": post,
    }
    return name, ad


def re_extract(case):
    """ rebuild an ad's post from its stored raw_content. one LLM call, no fetch.
        applies to ads whose posting URL no longer resolves.
    """
    ad = dataset.load_ad(case)
    ad["post"] = extract_post(ad["raw_content"], source=f"ad {case['ad']!r}")
    ad["extraction_model"] = EXTRACTION_MODEL
    ad["extracted_at"] = _now()
    return ad


def upsert_case(cases, name, url, ad):
    """ record a captured ad on a new or existing case, preserving any ground truth.
        returns (name, added). The returned name may differ from the one passed in.
    """
    index = dataset.find_case(cases, name=name, url=url)
    if index is not None:
        # an existing case keeps its recorded name, which the extracted company/title may no
        # longer produce
        name = cases[index]["name"]
    filename = dataset.save_ad(name, ad)
    if index is None:
        cases.append({
            "name": name,
            "url": url,
            "ad": filename,
            "verified": False,
            "notes": "",
            "expected": {},
        })
    else:
        cases[index]["ad"] = filename
        cases[index].setdefault("expected", {})
    return name, index is None


def _capture_urls(cases, urls, name=None, truncated=None):
    """ capture each url into the eval set, reporting failures without aborting the batch """
    failed = []
    truncated = truncated if truncated is not None else []
    for url in urls:
        print(f"Capturing {url} ...")
        try:
            captured_name, ad = capture(url, name=name if len(urls) == 1 else None)
        except Exception as e:
            # an unavailable posting raises ScrapeError; Tavily transport errors propagate as
            # their own types. Both are caught so one URL does not abort the batch.
            print(f"  FAILED: {type(e).__name__}: {e}")
            failed.append(url)
            continue
        name_used, added = upsert_case(cases, captured_name, url, ad)
        print(f"  {'added' if added else 'updated'} case {name_used!r} "
              f"({len(ad['raw_content'])} chars of page text)")
        if looks_truncated(ad["post"]):
            truncated.append(name_used)
            print(f"  ! description is {len(ad['post']['description'])} chars, below the "
                  f"{MIN_DESCRIPTION_CHARS}-char threshold: the fetch returned a login wall "
                  f"rather than the ad.\n    Recapture from the company's careers site.")
    return failed


def _report_truncated(truncated):
    if truncated:
        print(f"\n{len(truncated)} capture(s) are below the {MIN_DESCRIPTION_CHARS}-char "
              f"description threshold: {truncated}\n  Recapture from the company's careers "
              f"site, or drop the case. run_evals.py skips these ads.")


def _list_candidates(cases):
    """ print each case's name, ad/verified state, and drafted ground truth.

        days_on_office and address_contains are independent of the rubric and remain valid
        across a recompile. A drafted compatibility_score is rubric-dependent and may predate
        the current rubric. Reads cases.json only.
    """
    if not cases:
        print("No cases yet. Add one with: python evals/capture.py <url>")
        return
    print(f"{len(cases)} case(s). ad = ad captured, v = verified.\n")
    print(f"  {'ad':<3} {'v':<2} {'name':<52} {'days':<5} {'score':<7} address / url")
    for case in cases:
        expected = case.get("expected") or {}
        score = expected.get("compatibility_score")
        if isinstance(score, list):
            score = f"{score[0]}-{score[1]}"
        days = expected.get("days_on_office")
        if isinstance(days, list):
            days = days[0] if days[0] == days[1] else f"{days[0]}-{days[1]}"
        where = expected.get("address_contains") or case.get("url", "")
        print(f"  {'*' if dataset.has_ad(case) else '-':<3} "
              f"{'*' if case.get('verified') else '-':<2} "
              f"{case['name'][:52]:<52} {str(days if days is not None else '?'):<5} "
              f"{str(score if score is not None else '?'):<7} {where[:60]}")
    print("\nSelect cases covering a range of commutes, remote policies, and fit, then:\n"
          "  python evals/capture.py --from-cases NAME [NAME ...]")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("urls", nargs="*", help="posting url(s) to capture")
    parser.add_argument("--name", help="case name (only when capturing a single url)")
    parser.add_argument("--list-candidates", action="store_true",
                        help="print the eval set so cases can be picked by hand")
    parser.add_argument("--from-cases", nargs="+", metavar="NAME",
                        help="capture ads for these existing cases, dropping the rest")
    parser.add_argument("--re-extract", nargs="*", metavar="NAME",
                        help="rebuild post(s) from saved raw text; no NAME means all")
    args = parser.parse_args()

    cases = dataset.load_cases()

    if args.list_candidates:
        _list_candidates(cases)
        return

    if args.re_extract is not None:
        targets = [c for c in cases if c["name"] in args.re_extract] if args.re_extract else \
                  [c for c in cases if dataset.has_ad(c)]
        if not targets:
            sys.exit("no matching cases with an ad to re-extract")
        for case in targets:
            print(f"Re-extracting {case['name']} ...")
            ad = re_extract(case)
            dataset.save_ad(case["name"], ad)
            print(f"  {ad['post']['job_title']} at {ad['post']['company']}")
        dataset.save_cases(cases)
        print(f"\nRe-extracted {len(targets)} ad(s) with {EXTRACTION_MODEL}.")
        return

    if args.from_cases:
        picked = [c for c in cases if c["name"] in args.from_cases]
        missing = set(args.from_cases) - {c["name"] for c in picked}
        if missing:
            sys.exit(f"no such case(s): {sorted(missing)}")
        backup = dataset.backup_cases()
        if backup:
            print(f"Backed up the eval set to {backup}\n")
        dropped = len(cases) - len(picked)
        # the picked cases replace the dataset. Their existing ground truth is discarded: it
        # was drafted against an earlier rubric. draft.py refills it from the ad.
        cases = [{"name": c["name"], "url": c["url"], "ad": None,
                  "verified": False, "notes": "", "expected": {}} for c in picked]
        truncated = []
        failed = _capture_urls(cases, [c["url"] for c in cases], truncated=truncated)
        dataset.save_cases(cases)
        print(f"\nCorpus is now {len(cases)} case(s); dropped {dropped} unpicked.")
        _report_truncated(truncated)
        if failed:
            print(f"{len(failed)} posting(s) could not be captured; their cases are kept with "
                  f"\"ad\": null:")
            for url in failed:
                print(f"  {url}")
        print("\nNext: python evals/draft.py --all")
        return

    if not args.urls:
        parser.error("give a url, --from-cases, --re-extract, or --list-candidates")
    if args.name and len(args.urls) > 1:
        parser.error("--name only makes sense with a single url")

    truncated = []
    failed = _capture_urls(cases, args.urls, name=args.name, truncated=truncated)
    dataset.save_cases(cases)
    _report_truncated(truncated)
    if failed:
        print(f"\n{len(failed)} url(s) failed: {failed}")
    print("\nNext: python evals/draft.py --all")


if __name__ == "__main__":
    main()
