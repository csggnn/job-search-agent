"""
Schema contract between the pipeline and the UI: every column `ui/columns.py` reads exists
in `jobsearch.storage`'s schema. A failure means the UI would hide that field at runtime.

    podman-compose exec job-search python3 -m unittest discover -s tests/unit -v
"""

import sqlite3
import unittest

from jobsearch import storage
from ui import columns


def _schema_columns(table):
    """ the column names of `table` after running storage's schema on an empty database """
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(storage._SCHEMA)
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


class UiSchemaContractTest(unittest.TestCase):
    def test_evaluation_columns_exist(self):
        present = _schema_columns(columns.EVALUATIONS_TABLE)
        expected = {name for name, _ in columns.EVALUATION_COLUMNS}
        self.assertEqual(set(), expected - present)

    def test_criterion_columns_exist(self):
        present = _schema_columns(columns.CRITERIA_TABLE)
        expected = {name for name, _ in columns.CRITERION_COLUMNS}
        self.assertEqual(set(), expected - present)


if __name__ == "__main__":
    unittest.main()
