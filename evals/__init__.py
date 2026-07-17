"""
The eval harness: a curated set of job postings with ground truth set by hand, used to
measure the effect of rubric, prompt and model changes on the pipeline's output.

The eval set is separate from data/evaluations.db. The database records production
evaluations and grows with use. The eval set is curated and sized to hold reviewed ground
truth. Eval code may call jobsearch.storage's pure helpers (normalize_url,
rubric_content_hash); it does not call the database functions.
"""
