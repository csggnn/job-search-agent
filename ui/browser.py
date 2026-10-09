"""
Read-only web UI over an evaluations database: a filterable, sortable list of jobs and a
detail page per job.

The database is opened with SQLite's `mode=ro`, so no request can write, create or migrate
it. The columns read are those of `ui.columns` that the database has, found per request
with `PRAGMA table_info`: a missing optional column hides its field, its filter and its
sort, and every page names it in a warning. Columns outside `ui.columns` are never read.
"""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Flask, abort, render_template, request

from ui import columns

STATUSES = ("new", "applied", "discarded")
REVIEWED = {"yes": 1, "no": 0}
DIRECTIONS = ("asc", "desc")

EVALUATION_LABELS = dict(columns.EVALUATION_COLUMNS)
CRITERION_LABELS = dict(columns.CRITERION_COLUMNS)

# evaluation columns shown on the detail page; the title is the page heading
DETAIL_COLUMNS = tuple(name for name, label in columns.EVALUATION_COLUMNS
                       if label is not None and name != "job_title")
CRITERION_SHOWN = tuple(name for name, label in columns.CRITERION_COLUMNS if label is not None)

_TABLES = (
    (columns.EVALUATIONS_TABLE, columns.EVALUATION_COLUMNS, columns.EVALUATION_KEY),
    (columns.CRITERIA_TABLE, columns.CRITERION_COLUMNS, columns.CRITERION_KEY),
)


def create_app(db_path):
    """ the UI as a Flask app reading the database at db_path """
    app = Flask(__name__)
    app.jinja_env.globals.update(commute=_commute, ad_href=_ad_href)

    @app.get("/")
    def job_list():
        conn = _connect(db_path)
        if conn is None:
            return render_template("list.html", rows=None, warnings=[])
        with closing(conn):
            present, warnings = _schema(conn)
            cols = present[columns.EVALUATIONS_TABLE]
            if cols is None:
                return render_template("list.html", rows=None, warnings=warnings)
            view = _list_view(cols, request.args)
            rows = conn.execute(
                f"SELECT {', '.join(cols)} FROM {columns.EVALUATIONS_TABLE}"
                f"{view['where']} ORDER BY {view['order']}",
                view["params"],
            ).fetchall()
        return render_template("list.html", rows=[dict(r) for r in rows], warnings=warnings,
                               cols=cols, labels=EVALUATION_LABELS, statuses=STATUSES,
                               **view)

    @app.get("/job/<int:job_id>")
    def job_detail(job_id):
        conn = _connect(db_path)
        if conn is None:
            abort(404)
        with closing(conn):
            present, warnings = _schema(conn)
            cols = present[columns.EVALUATIONS_TABLE]
            if cols is None:
                abort(404)
            row = conn.execute(
                f"SELECT {', '.join(cols)} FROM {columns.EVALUATIONS_TABLE} "
                f"WHERE {columns.EVALUATION_KEY} = ?", (job_id,),
            ).fetchone()
            if row is None:
                abort(404)
            criteria, criterion_cols = None, []
            if present[columns.CRITERIA_TABLE] is not None:
                criterion_cols = [c for c in CRITERION_SHOWN
                                  if c in present[columns.CRITERIA_TABLE]]
                criteria = [dict(r) for r in conn.execute(
                    f"SELECT {', '.join(criterion_cols)} FROM {columns.CRITERIA_TABLE} "
                    f"WHERE {columns.CRITERION_KEY} = ?", (job_id,),
                )] if criterion_cols else []
        return render_template("detail.html", row=dict(row), warnings=warnings,
                               detail_fields=[c for c in DETAIL_COLUMNS if c in cols],
                               labels=EVALUATION_LABELS, criteria=criteria,
                               criterion_cols=criterion_cols, criterion_labels=CRITERION_LABELS)

    return app


def _connect(db_path):
    """ a read-only connection returning sqlite3.Row rows, or None when the file is missing """
    if not os.path.isfile(db_path):
        return None
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _schema(conn):
    """ ({table: present expected columns, or None when the table or its key is missing},
         [missing table or column names, for the warning])
    """
    present, missing = {}, []
    for table, expected, key in _TABLES:
        actual = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not actual:
            present[table] = None
            missing.append(f"{table} (table)")
            continue
        missing += [f"{table}.{name}" for name, _ in expected if name not in actual]
        found = [name for name, _ in expected if name in actual]
        present[table] = found if key in actual else None
    return present, missing


def _list_view(cols, args):
    """ the WHERE clause, ORDER BY and template state for the list page. Values outside the
        allowed set, and filters or sorts on an absent column, are dropped.
    """
    shown = [c for c in columns.LIST_COLUMNS if c in cols]
    where, params = [], []

    status = args.get("status")
    if status not in STATUSES or "application_status" not in cols:
        status = None
    if status:
        where.append("application_status = ?")
        params.append(status)

    reviewed = args.get("reviewed")
    if reviewed not in REVIEWED or "reviewed" not in cols:
        reviewed = None
    if reviewed:
        where.append("reviewed = ?")
        params.append(REVIEWED[reviewed])

    max_commute = _number(args.get("max_commute")) if "commute_score" in cols else None
    if max_commute is not None:
        keep = ["commute_score <= ?", "commute_score IS NULL"]
        if "is_remote" in cols:
            keep.append("is_remote = 1")
        where.append(f"({' OR '.join(keep)})")
        params.append(max_commute)

    sort = args.get("sort") if args.get("sort") in shown else None
    direction = args.get("dir") if args.get("dir") in DIRECTIONS else "asc"
    if sort:
        order = f"{sort} {direction}"
    elif "compatibility_score" in cols:
        order = "compatibility_score DESC"
    else:
        order = None
    order = f"{order}, {columns.EVALUATION_KEY}" if order else columns.EVALUATION_KEY

    filters = {"status": status, "reviewed": reviewed,
               "max_commute": args.get("max_commute") if max_commute is not None else None}
    filters = {k: v for k, v in filters.items() if v is not None}
    # each header links to its column ascending, or descending when already sorted ascending
    sort_args = {
        c: dict(filters, sort=c, dir="desc" if sort == c and direction == "asc" else "asc")
        for c in shown
    }
    return {
        "where": f" WHERE {' AND '.join(where)}" if where else "",
        "params": params,
        "order": order,
        "shown": shown,
        "filters": filters,
        "sort": sort,
        "direction": direction if sort else None,
        "sort_args": sort_args,
    }


def _number(value):
    """ value as a float, or None when it is not a number """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _commute(row):
    """ the commute as shown: remote, unknown, or the stored value in minutes """
    if row.get("is_remote"):
        return "remote"
    value = row.get("commute_score")
    if value is None:
        return "unknown"
    if isinstance(value, (int, float)):
        return f"{value:.0f} min"
    return str(value)


def _ad_href(url):
    """ url when it is an http(s) link, else None. Stored URLs come from scraped ads. """
    if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
        return url
    return None
