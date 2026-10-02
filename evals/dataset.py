"""
Read/write layer for the eval set: cases.json (ground truth) and the ads it references
(stored job-posting inputs).

Every function that reads or writes a file takes the eval directory as its first argument:
a profile's evals/ directory, jobsearch.config.Profile.evals_dir.

A case references its ad by filename rather than deriving it from the case name, so a
rename leaves the reference intact. A case with a null "ad" has no captured inputs;
run_evals.py reports and skips it.

No LLM calls, no network, and no database access: see the package docstring.
"""

import json
import os
import re

from jobsearch import storage
from jobsearch.scrape import validate_post

__all__ = [
    "EXPECTED_TYPES", "slugify", "cases_path", "load_cases", "save_cases", "backup_cases",
    "find_case", "save_ad", "load_ad", "case_post", "has_ad", "usable_expected",
    "validate_expected",
]

# ground truth holds one value per step, not a range. The accepted margin is a harness-level
# --tolerance-* option. A per-case range yields a constant pass/fail across the whole band.
EXPECTED_TYPES = {
    "compatibility_score": (int,),
    "days_on_office": (int,),
    "commute_score": (int, float),
    "address_contains": (str,),
    "criteria": (dict,),
}


def slugify(text):
    """ turn free text (e.g. "Acme - Widget Inspector") into a filesystem/case-name safe slug """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def cases_path(evals_dir):
    """ path of the case list in `evals_dir` """
    return os.path.join(evals_dir, "cases.json")


def _backup_path(evals_dir):
    return os.path.join(evals_dir, "cases.json.bak")


def _ads_dir(evals_dir):
    return os.path.join(evals_dir, "ads")


def load_cases(evals_dir):
    """ return the case list, or [] if cases.json is absent """
    if not os.path.exists(cases_path(evals_dir)):
        return []
    with open(cases_path(evals_dir)) as f:
        return json.load(f)


def save_cases(evals_dir, cases):
    """ write the case list to cases.json, creating `evals_dir` if absent """
    os.makedirs(evals_dir, exist_ok=True)
    with open(cases_path(evals_dir), "w") as f:
        json.dump(cases, f, indent=2)
        f.write("\n")


def backup_cases(evals_dir):
    """ copy cases.json to cases.json.bak. returns the backup path, or None if cases.json is
        absent.
    """
    if not os.path.exists(cases_path(evals_dir)):
        return None
    with open(cases_path(evals_dir)) as src, open(_backup_path(evals_dir), "w") as dst:
        dst.write(src.read())
    return _backup_path(evals_dir)


def find_case(cases, name=None, url=None):
    """ index of the case matching name, or matching url after normalization; None if absent """
    if name is not None:
        for i, case in enumerate(cases):
            if case.get("name") == name:
                return i
    if url is not None:
        normalized = storage.normalize_url(url)
        for i, case in enumerate(cases):
            if case.get("url") and storage.normalize_url(case["url"]) == normalized:
                return i
    return None


def _ad_filename(name):
    """ the ad filename assigned to a newly captured case """
    return f"{name}.json"


def _ad_path(evals_dir, ad):
    """ path of an ad, given the filename stored on a case """
    return os.path.join(_ads_dir(evals_dir), ad)


def save_ad(evals_dir, name, ad):
    """ write an ad and return the filename to record on the case """
    os.makedirs(_ads_dir(evals_dir), exist_ok=True)
    filename = _ad_filename(name)
    with open(_ad_path(evals_dir, filename), "w") as f:
        json.dump(ad, f, indent=2)
        f.write("\n")
    return filename


def load_ad(evals_dir, case):
    """ return a case's stored ad. raises FileNotFoundError if the case records no
        ad, or the recorded file is absent.
    """
    ad = case.get("ad")
    if not ad:
        raise FileNotFoundError(
            f"case {case['name']!r} has no ad - capture one with: "
            f"python evals/capture.py {case.get('url', '<url>')}"
        )
    path = _ad_path(evals_dir, ad)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"ad {ad!r} for case {case['name']!r} is missing - recapture it with: "
            f"python evals/capture.py {case.get('url', '<url>')}"
        )
    with open(path) as f:
        return json.load(f)


def case_post(evals_dir, case):
    """ the job posting a case replays against, checked by scrape.validate_post """
    return validate_post(load_ad(evals_dir, case)["post"], f"ad {case['ad']!r}")


def has_ad(evals_dir, case):
    """ True if the case's ad is recorded and present on disk """
    return bool(case.get("ad")) and os.path.exists(_ad_path(evals_dir, case["ad"]))


def _well_typed(key, value):
    types = EXPECTED_TYPES.get(key)
    if types is None:
        return False
    # bool is a subclass of int; exclude it from the numeric types
    return isinstance(value, types) and not isinstance(value, bool)


def usable_expected(expected):
    """ the subset of an "expected" block whose values match EXPECTED_TYPES.

        Unknown keys and values of another type, such as a [lo, hi] range from the previous
        case format, are omitted. draft.py treats an omitted value as unset and refills it.
    """
    return {k: v for k, v in (expected or {}).items() if _well_typed(k, v)}


def validate_expected(case):
    """ raise ValueError naming any expected value outside EXPECTED_TYPES """
    bad = sorted(k for k, v in (case.get("expected") or {}).items() if not _well_typed(k, v))
    if bad:
        raise ValueError(
            f"case {case['name']!r} has unusable ground truth for {bad}. Expected one value "
            f"per step (a [lo, hi] range is the old format). Re-draft it with: "
            f"python evals/draft.py {case['name']} --force"
        )
