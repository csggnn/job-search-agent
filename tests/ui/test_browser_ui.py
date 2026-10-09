"""
Browser tests for the database UI (ui/), one per scenario of the database-browser spec.

Each test class builds its own SQLite database from `ui.columns` under a temporary directory,
serves `ui.browser.create_app` on a free local port, and drives it with headless Chromium.
No test reads or writes `data/`, needs API keys or reaches the network.

    podman-compose exec ui python3 -m unittest discover -s tests/ui -v
"""

import hashlib
import os
import sqlite3
import tempfile
import threading
import unittest

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from ui import columns
from ui.browser import create_app

AD_HOST = "https://jobs.example.com"

# id, title, company, compatibility, is_remote, commute, status, reviewed
EVALUATIONS = [
    dict(id=1, job_title="ML Engineer", company="Acme", compatibility_score=82, is_remote=0,
         commute_score=20, application_status="new", reviewed=0),
    dict(id=2, job_title="Data Scientist", company="Beta", compatibility_score=60, is_remote=0,
         commute_score=45, application_status="applied", reviewed=1),
    dict(id=3, job_title="Robotics Lead", company="Gamma", compatibility_score=75, is_remote=0,
         commute_score=None, application_status="new", reviewed=1),
    dict(id=4, job_title="AI Engineer", company="Delta", compatibility_score=70, is_remote=1,
         commute_score=0, application_status="discarded", reviewed=0),
    dict(id=5, job_title=None, company="Epsilon", compatibility_score=50, is_remote=0,
         commute_score=25, application_status="new", reviewed=0),
]
for _row in EVALUATIONS:
    _row.update(
        url=f"{AD_HOST}/{_row['id']}",
        commute_address=None if _row["is_remote"] else f"Street {_row['id']}, Leuven",
        days_on_office=None if _row["is_remote"] else 2,
        status_reason=None,
        evaluated_at=f"2026-10-0{_row['id']}T10:00:00+00:00",
        notes=f"note for job {_row['id']}",
        compatibility_rationale=f"rationale for job {_row['id']}",
        works_well=f"works well for job {_row['id']}",
        does_not_work=f"does not work for job {_row['id']}",
    )

CRITERIA = [
    dict(evaluation_id=1, name="Python", type="skill", weight=3, matched=1, score=3,
         rationale="listed in requirements"),
    dict(evaluation_id=1, name="Computer vision", type="domain", weight=2, matched=1, score=2,
         rationale="core of the role"),
    dict(evaluation_id=1, name="Defense", type="penalty", weight=-3, matched=0, score=0,
         rationale="not a defense company"),
]

EXTRA_COLUMN = "ad_text"


def build_db(path, drop=(), extra_column=False, criteria_table=True, evaluations_table=True):
    """ write a database at `path` from `ui.columns` and the fixed rows. `drop` names
        evaluation columns to leave out; `extra_column` adds a column the UI does not read.
    """
    eval_cols = [name for name, _ in columns.EVALUATION_COLUMNS if name not in drop]
    conn = sqlite3.connect(path)
    try:
        if evaluations_table:
            ddl = [f"{c} INTEGER PRIMARY KEY" if c == columns.EVALUATION_KEY else c
                   for c in eval_cols]
            if extra_column:
                ddl.append(EXTRA_COLUMN)
            conn.execute(f"CREATE TABLE {columns.EVALUATIONS_TABLE} ({', '.join(ddl)})")
            for row in EVALUATIONS:
                values = {c: row[c] for c in eval_cols}
                if extra_column:
                    values[EXTRA_COLUMN] = f"full ad text of job {row['id']}"
                _insert(conn, columns.EVALUATIONS_TABLE, values)
        if criteria_table:
            crit_cols = [name for name, _ in columns.CRITERION_COLUMNS]
            conn.execute(f"CREATE TABLE {columns.CRITERIA_TABLE} ({', '.join(crit_cols)})")
            for row in CRITERIA:
                _insert(conn, columns.CRITERIA_TABLE, row)
        conn.commit()
    finally:
        conn.close()


def _insert(conn, table, values):
    names = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", list(values.values()))


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


_playwright = None
_browser = None


def setUpModule():
    global _playwright, _browser
    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch()


def tearDownModule():
    _browser.close()
    _playwright.stop()


class UiTestCase(unittest.TestCase):
    """ serves one database for the class; subclasses set `db_options` or `create_db` """

    db_options = {}
    create_db = True

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp.name, "evaluations.db")
        if cls.create_db:
            build_db(cls.db_path, **cls.db_options)
        cls.server = make_server("127.0.0.1", 0, create_app(cls.db_path), threaded=True)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.tmp.cleanup()

    def setUp(self):
        self.context = _browser.new_context()
        self.context.set_default_timeout(5000)
        # ad links point at AD_HOST; answer them locally so no test reaches the network
        self.context.route(f"{AD_HOST}/**", lambda route: route.fulfill(body="ad page"))
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def open(self, path="/"):
        return self.page.goto(self.base + path)

    def listed_ids(self):
        return [int(i) for i in
                self.page.locator("tr.job").evaluate_all("rows => rows.map(r => r.dataset.id)")]

    def cell(self, job_id, column):
        return self.page.locator(f"tr.job[data-id='{job_id}'] td.col-{column}")

    def warning_text(self):
        warning = self.page.locator("#schema-warning")
        return warning.inner_text() if warning.count() else ""


class ListPageTest(UiTestCase):
    def test_default_order(self):
        self.open()
        self.assertEqual([1, 3, 4, 2, 5], self.listed_ids())
        self.assertEqual("5", self.page.locator("#row-count").inner_text())

    def test_unknown_commute(self):
        self.open()
        self.assertEqual("unknown", self.cell(3, "commute_score").inner_text().strip())

    def test_remote_job(self):
        self.open()
        self.assertEqual("remote", self.cell(4, "commute_score").inner_text().strip())

    def test_ad_link_opens_new_tab(self):
        self.open()
        link = self.cell(1, "url").locator("a")
        self.assertEqual("_blank", link.get_attribute("target"))
        with self.page.expect_popup() as popup:
            link.click()
        self.assertEqual(f"{AD_HOST}/1", popup.value.url)

    def test_job_without_title(self):
        self.open()
        link = self.cell(5, "job_title").locator("a")
        self.assertEqual("(untitled)", link.inner_text().strip())
        link.click()
        self.assertTrue(self.page.url.endswith("/job/5"))

    def test_no_warning_for_complete_schema(self):
        self.open()
        self.assertEqual("", self.warning_text())


class FilterSortTest(UiTestCase):
    def test_filter_by_status(self):
        self.open()
        self.page.select_option("select[name=status]", "new")
        self.page.click("#filters button[type=submit]")
        self.assertEqual([1, 3, 5], self.listed_ids())
        self.assertEqual("3", self.page.locator("#row-count").inner_text())

    def test_maximum_commute(self):
        self.open()
        self.page.fill("input[name=max_commute]", "30")
        self.page.click("#filters button[type=submit]")
        self.assertEqual([1, 3, 4, 5], self.listed_ids())

    def test_combined_filters(self):
        self.open()
        self.page.select_option("select[name=status]", "new")
        self.page.select_option("select[name=reviewed]", "no")
        self.page.click("#filters button[type=submit]")
        self.assertEqual([1, 5], self.listed_ids())

    def test_sort_by_column(self):
        self.open()
        self.page.click("th.col-company a")
        self.assertEqual([1, 2, 4, 5, 3], self.listed_ids())  # Acme Beta Delta Epsilon Gamma
        self.page.click("th.col-company a")
        self.assertEqual([3, 5, 4, 2, 1], self.listed_ids())

    def test_url_reproduces_view(self):
        self.open()
        self.page.select_option("select[name=status]", "new")
        self.page.click("#filters button[type=submit]")
        self.page.click("th.col-company a")
        url, ids = self.page.url, self.listed_ids()
        other = self.context.new_page()
        other.goto(url)
        self.page = other
        self.assertEqual(ids, self.listed_ids())
        self.assertEqual([1, 5, 3], ids)

    def test_unknown_sort_value(self):
        self.open("/?sort=bogus&dir=sideways")
        self.assertEqual([1, 3, 4, 2, 5], self.listed_ids())

    def test_invalid_filter_values_are_ignored(self):
        self.open("/?status=maybe&reviewed=perhaps&max_commute=far")
        self.assertEqual([1, 3, 4, 2, 5], self.listed_ids())


class DetailPageTest(UiTestCase):
    def test_detail_page_content(self):
        self.open()
        self.cell(1, "job_title").locator("a").click()
        self.assertTrue(self.page.url.endswith("/job/1"))
        self.assertIn("ML Engineer", self.page.locator("h1").inner_text())
        for column, text in [("company", "Acme"), ("notes", "note for job 1"),
                             ("compatibility_rationale", "rationale for job 1"),
                             ("works_well", "works well for job 1"),
                             ("does_not_work", "does not work for job 1"),
                             ("commute_address", "Street 1, Leuven")]:
            self.assertIn(text, self.page.locator(f"dd.field-{column}").inner_text())
        ad = self.page.locator("dd.field-url a")
        self.assertEqual(f"{AD_HOST}/1", ad.get_attribute("href"))
        self.assertEqual(3, self.page.locator("#criteria tr.criterion").count())
        self.assertIn("Computer vision", self.page.locator("#criteria").inner_text())

    def test_missing_evaluation(self):
        response = self.open("/job/999")
        self.assertEqual(404, response.status)


class ReadOnlyTest(UiTestCase):
    def test_browsing_leaves_database_unchanged(self):
        before = file_hash(self.db_path)
        listing = sorted(os.listdir(self.tmp.name))
        self.open()
        self.open("/?status=new&reviewed=no&max_commute=30&sort=company&dir=desc")
        self.open("/job/1")
        self.assertEqual(before, file_hash(self.db_path))
        self.assertEqual(listing, sorted(os.listdir(self.tmp.name)))


class NoDatabaseTest(UiTestCase):
    create_db = False

    def test_no_database_yet(self):
        self.open()
        self.assertIn("no saved evaluations", self.page.locator("#empty").inner_text().lower())
        self.assertEqual("", self.warning_text())
        self.assertFalse(os.path.exists(self.db_path))


class ExtraColumnTest(UiTestCase):
    db_options = dict(extra_column=True)

    def test_extra_column_changes_nothing(self):
        # reference: the same rows without the extra column, served by a second app
        with tempfile.TemporaryDirectory() as tmp:
            reference_db = os.path.join(tmp, "evaluations.db")
            build_db(reference_db)
            server = make_server("127.0.0.1", 0, create_app(reference_db), threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                reference = f"http://127.0.0.1:{server.server_port}"
                for path in ["/", "/job/1"]:
                    self.page.goto(reference + path)
                    expected = self.page.locator("body").inner_text()
                    self.open(path)
                    self.assertEqual(expected, self.page.locator("body").inner_text())
                    self.assertEqual("", self.warning_text())
            finally:
                server.shutdown()
                thread.join()


class OptionalColumnMissingTest(UiTestCase):
    db_options = dict(drop=("notes", "commute_score"))

    def test_fields_hidden_and_warned(self):
        self.open()
        self.assertEqual(5, len(self.listed_ids()))
        self.assertEqual(0, self.page.locator("th.col-commute_score").count())
        self.assertEqual(0, self.page.locator("input[name=max_commute]").count())
        for name in ("evaluations.notes", "evaluations.commute_score"):
            self.assertIn(name, self.warning_text())

        self.open("/job/1")
        self.assertEqual(0, self.page.locator("dd.field-notes").count())
        self.assertEqual(0, self.page.locator("dd.field-commute_score").count())
        self.assertIn("evaluations.notes", self.warning_text())

    def test_url_parameter_for_missing_column_is_ignored(self):
        self.open("/?max_commute=30&sort=commute_score")
        self.assertEqual([1, 3, 4, 2, 5], self.listed_ids())


class CriteriaTableMissingTest(UiTestCase):
    db_options = dict(criteria_table=False)

    def test_detail_without_criteria(self):
        self.open("/job/1")
        self.assertIn("ML Engineer", self.page.locator("h1").inner_text())
        self.assertEqual(0, self.page.locator("#criteria").count())
        self.assertIn(columns.CRITERIA_TABLE, self.warning_text())
        self.open()
        self.assertIn(columns.CRITERIA_TABLE, self.warning_text())


class MandatoryColumnMissingTest(UiTestCase):
    db_options = dict(drop=(columns.EVALUATION_KEY,))

    def test_table_treated_as_absent(self):
        self.open()
        self.assertIn("no saved evaluations", self.page.locator("#empty").inner_text().lower())
        self.assertIn("evaluations.id", self.warning_text())


if __name__ == "__main__":
    unittest.main()
