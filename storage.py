"""
Persistence for job evaluations: a SQLite-backed cache keyed by normalized job URL,
invalidated whenever the compatibility rubric's criteria change.
"""

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from commute import FULLY_REMOTE

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "evaluations.db")

# query params that are tracking noise, not part of a job posting's identity
_TRACKING_PARAMS = {"trk", "trackingid", "refid", "ref", "originalsubdomain", "position", "pagenum"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL UNIQUE,
    job_title TEXT,
    company TEXT,
    is_remote INTEGER NOT NULL,
    days_on_office INTEGER,
    commute_address TEXT,
    commute_score REAL,
    compatibility_score INTEGER NOT NULL,
    compatibility_rationale TEXT,
    works_well TEXT,
    does_not_work TEXT,
    rubric_hash TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    reviewed INTEGER NOT NULL DEFAULT 0,
    application_status TEXT NOT NULL DEFAULT 'new',
    status_reason TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS evaluation_criteria (
    evaluation_id INTEGER NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    weight INTEGER NOT NULL,
    matched INTEGER NOT NULL,
    score INTEGER NOT NULL,
    rationale TEXT
);

CREATE INDEX IF NOT EXISTS idx_criteria_eval ON evaluation_criteria(evaluation_id);
CREATE INDEX IF NOT EXISTS idx_criteria_name ON evaluation_criteria(name);
CREATE INDEX IF NOT EXISTS idx_evaluations_score ON evaluations(compatibility_score);
"""

# columns added after the initial release; applied to pre-existing DBs via ALTER TABLE
_MIGRATIONS = [
    ("reviewed", "ALTER TABLE evaluations ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0"),
    ("application_status", "ALTER TABLE evaluations ADD COLUMN application_status TEXT NOT NULL DEFAULT 'new'"),
    ("status_reason", "ALTER TABLE evaluations ADD COLUMN status_reason TEXT"),
    ("notes", "ALTER TABLE evaluations ADD COLUMN notes TEXT"),
]

APPLICATION_STATUSES = {"new", "applied", "discarded"}


def _migrate_schema(conn):
    """ add any columns from _MIGRATIONS that are missing from an existing evaluations table """
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(evaluations)")}
    for column, ddl in _MIGRATIONS:
        if column not in existing_columns:
            conn.execute(ddl)


def _get_connection():
    """ open a connection to the evaluations DB, creating/migrating the schema if needed """
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _migrate_schema(conn)
    return conn


def normalize_url(url):
    """ canonicalize a job URL for dedup/lookup: strip tracking params and trailing slashes,
        but keep other query params since some sites encode the job id there
    """
    parts = urlsplit(url)
    query_pairs = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query_pairs), ""))


def rubric_content_hash(rubric):
    """ sha256 of every rubric field that feeds compatibility_score()'s prompt (criteria +
        scoring_guidance), used to detect any change that would affect an already-evaluated
        job's judgment - including hand-edits to compatibility_rubric.json that don't touch
        resume.md/job_preferences.md, and scoring_guidance-only edits that don't add/remove/
        reweight any criterion.
    """
    payload = {"criteria": rubric["criteria"], "scoring_guidance": rubric.get("scoring_guidance")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def list_evaluated_urls():
    """ return [(url, normalized_url), ...] for every saved evaluation - the original url last
        passed to save_evaluation() plus its normalized form, for callers that need to diff
        against another set of urls (e.g. cases.json) using the same normalization.
    """
    conn = _get_connection()
    try:
        rows = conn.execute("SELECT url, normalized_url FROM evaluations").fetchall()
    finally:
        conn.close()
    return rows


_EVALUATION_COLUMNS = (
    "job_title", "company", "commute_score", "commute_address", "days_on_office",
    "compatibility_score", "compatibility_rationale", "works_well", "does_not_work",
    "rubric_hash", "evaluated_at", "reviewed", "application_status", "status_reason", "notes",
)


def get_evaluation(url):
    """ return the full saved evaluation row for url as a dict, or None if never evaluated.
        includes both pipeline-derived fields and user-tracked fields (reviewed, notes, etc).
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            f"SELECT {', '.join(_EVALUATION_COLUMNS)} FROM evaluations WHERE normalized_url = ?",
            (normalize_url(url),),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    return dict(zip(_EVALUATION_COLUMNS, row))


_CRITERION_COLUMNS = ("name", "type", "weight", "matched", "score", "rationale")


def get_evaluation_criteria(url):
    """ return the list of evaluation_criteria rows (name, type, weight, matched, score,
        rationale) for url's saved evaluation, or [] if never evaluated.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_CRITERION_COLUMNS)} FROM evaluation_criteria "
            "WHERE evaluation_id = (SELECT id FROM evaluations WHERE normalized_url = ?)",
            (normalize_url(url),),
        ).fetchall()
    finally:
        conn.close()

    return [dict(zip(_CRITERION_COLUMNS, row)) for row in rows]


def save_evaluation(url, rubric_hash, job, commute, compatibility, overview):
    """ upsert the pipeline-derived fields of the evaluation for url: updates the existing row
        if one exists for this normalized_url (preserving user-tracked fields like reviewed/
        notes/application_status), else inserts a fresh row with their defaults. Always
        replaces evaluation_criteria for the row, since those are fully derived.
    """
    normalized = normalize_url(url)
    evaluated_at = datetime.now(timezone.utc).isoformat()
    is_remote = 1 if commute["address"] == FULLY_REMOTE else 0

    conn = _get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM evaluations WHERE normalized_url = ?", (normalized,)
        ).fetchone()

        if existing:
            evaluation_id = existing[0]
            conn.execute(
                "UPDATE evaluations SET url = ?, job_title = ?, company = ?, is_remote = ?, "
                "days_on_office = ?, commute_address = ?, commute_score = ?, "
                "compatibility_score = ?, compatibility_rationale = ?, works_well = ?, "
                "does_not_work = ?, rubric_hash = ?, evaluated_at = ? WHERE id = ?",
                (
                    url, job["job_title"], job["company"], is_remote, commute["days_on_office"],
                    commute["address"], commute["score"], compatibility["compatibility_score"],
                    compatibility["rationale"], overview["works_well"], overview["does_not_work"],
                    rubric_hash, evaluated_at, evaluation_id,
                ),
            )
            conn.execute("DELETE FROM evaluation_criteria WHERE evaluation_id = ?", (evaluation_id,))
        else:
            cursor = conn.execute(
                "INSERT INTO evaluations (url, normalized_url, job_title, company, is_remote, "
                "days_on_office, commute_address, commute_score, compatibility_score, "
                "compatibility_rationale, works_well, does_not_work, rubric_hash, evaluated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    url, normalized, job["job_title"], job["company"], is_remote,
                    commute["days_on_office"], commute["address"], commute["score"],
                    compatibility["compatibility_score"], compatibility["rationale"],
                    overview["works_well"], overview["does_not_work"], rubric_hash, evaluated_at,
                ),
            )
            evaluation_id = cursor.lastrowid

        conn.executemany(
            "INSERT INTO evaluation_criteria (evaluation_id, name, type, weight, matched, "
            "score, rationale) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    evaluation_id,
                    c["name"],
                    c["type"],
                    c["weight"],
                    1 if c["matched"] else 0,
                    c["score"],
                    c.get("rationale"),
                )
                for c in compatibility["criteria"]
            ],
        )
        conn.commit()
    finally:
        conn.close()


def update_review(url, reviewed=None, application_status=None, status_reason=None, notes=None):
    """ partial update of the user-tracked fields for an existing evaluation; None = leave
        unchanged. Raises ValueError if the url has never been evaluated, or if
        application_status isn't one of APPLICATION_STATUSES.
    """
    if application_status is not None and application_status not in APPLICATION_STATUSES:
        raise ValueError(f"application_status must be one of {APPLICATION_STATUSES}, got {application_status!r}")

    normalized = normalize_url(url)
    updates = {
        "reviewed": 1 if reviewed else 0 if reviewed is not None else None,
        "application_status": application_status,
        "status_reason": status_reason,
        "notes": notes,
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        return

    conn = _get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM evaluations WHERE normalized_url = ?", (normalized,)
        ).fetchone()
        if existing is None:
            raise ValueError(f"no saved evaluation for url: {url}")

        set_clause = ", ".join(f"{col} = ?" for col in updates)
        conn.execute(
            f"UPDATE evaluations SET {set_clause} WHERE id = ?",
            (*updates.values(), existing[0]),
        )
        conn.commit()
    finally:
        conn.close()
