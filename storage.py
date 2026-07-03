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
    evaluated_at TEXT NOT NULL
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


def _get_connection():
    """ open a connection to the evaluations DB, creating the schema if needed """
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
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
    """ sha256 of the rubric's criteria list, used to detect any rubric change (including
        hand-edits to compatibility_rubric.json that don't touch resume.md/job_preferences.md)
    """
    return hashlib.sha256(json.dumps(rubric["criteria"], sort_keys=True).encode()).hexdigest()


def get_cached_evaluation(url, rubric_hash):
    """ return the saved evaluation for url if one exists and matches rubric_hash, else None.
        shaped like evaluate_job()'s return value, plus "evaluated_at".
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT job_title, company, commute_score, commute_address, days_on_office, "
            "compatibility_score, works_well, does_not_work, rubric_hash, evaluated_at "
            "FROM evaluations WHERE normalized_url = ?",
            (normalize_url(url),),
        ).fetchone()
    finally:
        conn.close()

    if row is None or row[8] != rubric_hash:
        return None

    return {
        "job_title": row[0],
        "company": row[1],
        "commute_score": row[2],
        "commute_address": row[3],
        "days_on_office": row[4],
        "compatibility_score": row[5],
        "works_well": row[6],
        "does_not_work": row[7],
        "evaluated_at": row[9],
    }


def save_evaluation(url, rubric_hash, job, commute, compatibility, overview):
    """ upsert the evaluation for url: replaces any prior row (and its criteria) for the
        same normalized_url with the freshly computed result
    """
    normalized = normalize_url(url)
    evaluated_at = datetime.now(timezone.utc).isoformat()

    conn = _get_connection()
    try:
        conn.execute("DELETE FROM evaluations WHERE normalized_url = ?", (normalized,))
        cursor = conn.execute(
            "INSERT INTO evaluations (url, normalized_url, job_title, company, is_remote, "
            "days_on_office, commute_address, commute_score, compatibility_score, "
            "compatibility_rationale, works_well, does_not_work, rubric_hash, evaluated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                url,
                normalized,
                job["job_title"],
                job["company"],
                1 if commute["address"] == FULLY_REMOTE else 0,
                commute["days_on_office"],
                commute["address"],
                commute["score"],
                compatibility["compatibility_score"],
                compatibility["rationale"],
                overview["works_well"],
                overview["does_not_work"],
                rubric_hash,
                evaluated_at,
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
