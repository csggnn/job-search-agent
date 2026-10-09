"""
The database columns the UI reads: its contract with the pipeline's schema.

Each entry is (column, label). A label of None marks a column the UI reads but does not show
as a field of its own. Every column is optional except the key of each table: a table
without its key is treated as absent.

This module imports nothing, so the pipeline's unit tests can check it against
`jobsearch.storage`'s schema without the UI's dependencies.
"""

EVALUATIONS_TABLE = "evaluations"
EVALUATION_KEY = "id"

EVALUATION_COLUMNS = (
    ("id", None),
    ("job_title", "Title"),
    ("company", "Company"),
    ("compatibility_score", "Compatibility"),
    ("is_remote", None),
    ("commute_score", "Commute"),
    ("commute_address", "Commute address"),
    ("days_on_office", "Office days"),
    ("reviewed", "Reviewed"),
    ("application_status", "Status"),
    ("status_reason", "Status reason"),
    ("evaluated_at", "Evaluated"),
    ("url", "Ad"),
    ("notes", "Notes"),
    ("compatibility_rationale", "Rationale"),
    ("works_well", "Works well"),
    ("does_not_work", "Does not work"),
)

# the evaluation columns shown on the list page, in display order
LIST_COLUMNS = (
    "job_title", "company", "compatibility_score", "commute_score", "reviewed",
    "application_status", "evaluated_at", "url",
)

CRITERIA_TABLE = "evaluation_criteria"
CRITERION_KEY = "evaluation_id"

CRITERION_COLUMNS = (
    ("evaluation_id", None),
    ("name", "Criterion"),
    ("type", "Type"),
    ("weight", "Weight"),
    ("matched", "Matched"),
    ("score", "Score"),
    ("rationale", "Rationale"),
)
