"""
Offline unit tests for jobsearch.preselection - no LLM, no network, no database, no env.

They pin the contract described in docs/plans/pre-selection: the deterministic stage 1
(staleness drop, duplicate collapse, already-evaluated drop, rubric prescore), the stage 2
prompt-building helpers and reply validation, and preselect()'s accounting invariant that
every discovered job ad appears exactly once across "selected" and "dropped".

The one LLM call is exercised with jobsearch.preselection.ask_json patched out, so the
suite stays offline:

    podman-compose exec job-search python3 -m unittest discover -s tests/unit -v
"""

import io
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from unittest.mock import patch

from jobsearch import preselection
from jobsearch.preselection import (
    BUDGET_WARN_JOB_ADS, DEFAULT_N, DROP_DUPLICATE, DROP_EVALUATED, DROP_INCOMPLETE,
    DROP_NOT_SELECTED, DROP_STALE, EXCERPT_CHARS, MAX_AGE_DAYS,
    check_budget, collapse_duplicates, description_excerpt, drop_already_evaluated,
    drop_incomplete, drop_stale, format_preselection, job_opening_key, prescore_job_ads, preselect,
    select_batch, summarize_job_ad, validate_selection,
)

# a rubric whose weights sum to something other than 0 on every subset used below, so a
# prescore assertion can never be satisfied by the stub's constant 0
RUBRIC = {
    "criteria": [
        {"name": "widgets", "pattern": r"widgets?", "type": "skill", "weight": 3},
        {"name": "springfield", "pattern": r"springfield", "type": "field", "weight": 2},
        {"name": "night-shift", "pattern": r"night-?shift", "type": "field", "weight": -4},
    ]
}


def make_job_ad(url, title="Widget Inspector", company="Acme", location="Springfield, Utopia",
                description="We build widgets.", days_ago=1, **extra):
    """ one job ad in the shape jobspy_search() produces, dated relative to today so the
        staleness cutoff can be exercised without freezing the clock
    """
    posted = None if days_ago is None else str(date.today() - timedelta(days=days_ago))
    return {
        "url": url,
        "job_title": title,
        "company": company,
        "location": location,
        "matched_queries": ["widget inspector"],
        "description": description,
        "is_remote": False,
        "date_posted": posted,
        "job_type": None,
        "job_level": None,
        "min_amount": None,
        "max_amount": None,
        "currency": None,
        "company_industry": None,
        "work_from_home_type": None,
        **extra,
    }


def urls(records):
    """ the urls of a job ad list, or of a list of _dropped() records """
    return [r["job_ad"]["url"] if "job_ad" in r else r["url"] for r in records]


class JobOpeningKeyTest(unittest.TestCase):
    """ the identity two job ads must share to be the same opening: normalized company +
        title. Board noise is stripped; anything separating two real openings, a location
        suffix included, is kept.
    """

    def test_lowercases_and_collapses_whitespace(self):
        self.assertEqual(job_opening_key("  ACME  Corp ", " Widget   Inspector "),
                         job_opening_key("acme corp", "widget inspector"))

    def test_strips_gender_markers(self):
        base = job_opening_key("Acme", "Widget Inspector")
        self.assertEqual(job_opening_key("Acme", "Widget Inspector (m/f/d)"), base)
        self.assertEqual(job_opening_key("Acme", "Widget Inspector (h/f/x)"), base)
        self.assertEqual(job_opening_key("Acme", "Widget Inspector (M/W/D)"), base)

    def test_expands_seniority_abbreviations(self):
        senior = job_opening_key("Acme", "Senior Widget Engineer")
        self.assertEqual(job_opening_key("Acme", "Sr. Widget Engineer"), senior)
        self.assertEqual(job_opening_key("Acme", "Snr Widget Engineer"), senior)
        self.assertEqual(job_opening_key("Acme", "Jr Widget Engineer"),
                         job_opening_key("Acme", "Junior Widget Engineer"))

    def test_seniority_levels_stay_distinct(self):
        self.assertNotEqual(job_opening_key("Acme", "Sr. Widget Engineer"),
                            job_opening_key("Acme", "Jr Widget Engineer"))

    def test_location_suffix_is_kept(self):
        # the same role advertised in two cities is two job openings with different commutes
        self.assertNotEqual(job_opening_key("Acme", "Widget Inspector - Springfield"),
                            job_opening_key("Acme", "Widget Inspector - Metropolis"))

    def test_different_company_or_title_gives_different_key(self):
        self.assertNotEqual(job_opening_key("Acme", "Widget Inspector"),
                            job_opening_key("Globex", "Widget Inspector"))
        self.assertNotEqual(job_opening_key("Acme", "Widget Inspector"),
                            job_opening_key("Acme", "Widget Engineer"))

    def test_missing_fields_do_not_raise(self):
        self.assertIsInstance(job_opening_key(None, None), str)
        self.assertEqual(job_opening_key(None, "Widget Inspector"),
                         job_opening_key("", "Widget Inspector"))


class DropIncompleteTest(unittest.TestCase):
    """ a job ad evaluation cannot score, one with a blank title, company, location or
        description, is dropped before it can take a selection slot
    """

    def test_keeps_a_complete_job_ad(self):
        kept, dropped = drop_incomplete([make_job_ad("https://acme.example/1")])
        self.assertEqual(urls(kept), ["https://acme.example/1"])
        self.assertEqual(dropped, [])

    def test_drops_a_job_ad_with_a_missing_or_blank_field_naming_it(self):
        no_description = make_job_ad("https://acme.example/1", description=None)
        blank_company = make_job_ad("https://acme.example/2", company="  ")
        kept, dropped = drop_incomplete([no_description, blank_company])
        self.assertEqual(kept, [])
        self.assertEqual([(r["stage"], r["reason"]) for r in dropped],
                         [(DROP_INCOMPLETE, "no description"), (DROP_INCOMPLETE, "no company")])


class DropStaleTest(unittest.TestCase):
    """ a drop on date_posted against a caller-supplied cutoff. A
        missing or unparseable date is not evidence of staleness. No other field, work mode
        and location included, drops an ad at this step.
    """

    def test_drops_job_ad_older_than_the_cutoff(self):
        old = make_job_ad("https://acme.example/1", days_ago=MAX_AGE_DAYS + 5)
        kept, dropped = drop_stale([old], MAX_AGE_DAYS)
        self.assertEqual(kept, [])
        self.assertEqual(urls(dropped), ["https://acme.example/1"])

    def test_keeps_job_ad_within_the_cutoff(self):
        fresh = make_job_ad("https://acme.example/1", days_ago=MAX_AGE_DAYS - 5)
        kept, dropped = drop_stale([fresh], MAX_AGE_DAYS)
        self.assertEqual(urls(kept), ["https://acme.example/1"])
        self.assertEqual(dropped, [])

    def test_missing_date_is_kept(self):
        # absent data is not evidence of staleness
        kept, dropped = drop_stale([make_job_ad("https://acme.example/1", days_ago=None)],
                                   MAX_AGE_DAYS)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])

    def test_unparseable_date_is_kept(self):
        job_ad = make_job_ad("https://acme.example/1")
        job_ad["date_posted"] = "not a date"
        kept, dropped = drop_stale([job_ad], MAX_AGE_DAYS)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])

    def test_dropped_record_names_the_stage(self):
        old = make_job_ad("https://acme.example/1", days_ago=MAX_AGE_DAYS + 1)
        _, [record] = drop_stale([old], MAX_AGE_DAYS)
        self.assertEqual(record["stage"], DROP_STALE)
        self.assertEqual(record["job_ad"]["url"], "https://acme.example/1")
        self.assertTrue(record["reason"])

    def test_cutoff_is_the_parameter_not_the_constant(self):
        job_ad = make_job_ad("https://acme.example/1", days_ago=10)
        self.assertEqual(drop_stale([job_ad], 5)[0], [])
        self.assertEqual(len(drop_stale([job_ad], 30)[0]), 1)

    def test_remote_and_location_play_no_part(self):
        # pre-selection never filters on work mode: the commute modifier scores it later
        onsite = make_job_ad("https://acme.example/1", is_remote=False, location="Elbonia")
        remote = make_job_ad("https://acme.example/2", is_remote=True, location=None)
        kept, dropped = drop_stale([onsite, remote], MAX_AGE_DAYS)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, [])


class CollapseDuplicatesTest(unittest.TestCase):
    """ one job opening reaches evaluation once, however many boards carry it. The survivor
        is a job ad with a description, and among those the preferred url source.
    """

    def test_same_job_opening_under_several_urls_collapses_to_one(self):
        job_ads = [
            make_job_ad("https://www.linkedin.com/jobs/view/1"),
            make_job_ad("https://www.indeed.com/viewjob?jk=2"),
            make_job_ad("https://acme.example/careers/3"),
        ]
        kept, dropped = collapse_duplicates(job_ads)
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 2)

    def test_survivor_is_the_companys_own_careers_page(self):
        job_ads = [
            make_job_ad("https://www.linkedin.com/jobs/view/1"),
            make_job_ad("https://acme.example/careers/3"),
        ]
        [kept], _ = collapse_duplicates(job_ads)
        self.assertEqual(kept["url"], "https://acme.example/careers/3")

    def test_survivor_prefers_a_source_board_over_a_re_poster(self):
        job_ads = [
            make_job_ad("https://www.jobleads.com/posting/9"),
            make_job_ad("https://www.linkedin.com/jobs/view/1"),
        ]
        [kept], _ = collapse_duplicates(job_ads)
        self.assertEqual(kept["url"], "https://www.linkedin.com/jobs/view/1")

    def test_dropped_records_name_the_stage(self):
        job_ads = [
            make_job_ad("https://acme.example/careers/3"),
            make_job_ad("https://www.linkedin.com/jobs/view/1"),
        ]
        _, [record] = collapse_duplicates(job_ads)
        self.assertEqual(record["stage"], DROP_DUPLICATE)
        self.assertEqual(record["job_ad"]["url"], "https://www.linkedin.com/jobs/view/1")

    def test_distinct_job_openings_both_survive(self):
        job_ads = [
            make_job_ad("https://acme.example/careers/3", title="Widget Inspector"),
            make_job_ad("https://acme.example/careers/4", title="Widget Engineer"),
        ]
        kept, dropped = collapse_duplicates(job_ads)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, [])

    def test_collapse_uses_the_normalized_job_opening_key(self):
        job_ads = [
            make_job_ad("https://acme.example/careers/3", title="Senior Widget Engineer"),
            make_job_ad("https://www.linkedin.com/jobs/view/1",
                           title="Sr. Widget Engineer (m/f/d)"),
        ]
        kept, dropped = collapse_duplicates(job_ads)
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(dropped), 1)

    def test_every_survivor_carries_its_job_opening_key(self):
        [kept], _ = collapse_duplicates([make_job_ad("https://acme.example/careers/3")])
        self.assertEqual(kept["job_opening_key"], job_opening_key("Acme", "Widget Inspector"))


class DropAlreadyEvaluatedTest(unittest.TestCase):
    """ an opening already in storage is not evaluated twice. The match is on
        job_opening_key(), not url, and application_status never enters the decision.
    """

    def test_drops_a_job_opening_already_in_storage(self):
        known = [("https://other.example/1", "Acme", "Widget Inspector", None)]
        kept, dropped = drop_already_evaluated([make_job_ad("https://acme.example/3")], known)
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]["stage"], DROP_EVALUATED)

    def test_matches_on_the_normalized_key_not_the_raw_strings(self):
        known = [("https://other.example/1", "acme", "Sr. Widget Engineer", None)]
        job_ad = make_job_ad("https://acme.example/3", title="Senior Widget Engineer (m/f/d)")
        kept, _ = drop_already_evaluated([job_ad], known)
        self.assertEqual(kept, [])

    def test_application_status_is_ignored(self):
        # having been evaluated is the drop rule on its own
        for status in ("discarded", "applied", "reviewed", None):
            known = [("https://other.example/1", "Acme", "Widget Inspector", status)]
            kept, _ = drop_already_evaluated([make_job_ad("https://acme.example/3")], known)
            self.assertEqual(kept, [], f"status {status!r} should not change the drop")

    def test_a_discard_does_not_suppress_other_roles_at_the_same_company(self):
        known = [("https://other.example/1", "Acme", "Widget Inspector", "discarded")]
        job_ad = make_job_ad("https://acme.example/4", title="Widget Engineer")
        kept, dropped = drop_already_evaluated([job_ad], known)
        self.assertEqual(urls(kept), ["https://acme.example/4"])
        self.assertEqual(dropped, [])

    def test_same_title_at_another_company_is_kept(self):
        known = [("https://other.example/1", "Globex", "Widget Inspector", None)]
        kept, _ = drop_already_evaluated([make_job_ad("https://acme.example/3")], known)
        self.assertEqual(len(kept), 1)

    def test_empty_known_job_openings_keeps_everything(self):
        job_ads = [make_job_ad("https://acme.example/3")]
        kept, dropped = drop_already_evaluated(job_ads, ())
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])

    def test_known_job_opening_with_missing_fields_does_not_raise(self):
        known = [("https://other.example/1", None, None, None)]
        kept, _ = drop_already_evaluated([make_job_ad("https://acme.example/3")], known)
        self.assertEqual(len(kept), 1)


class PrescoreJobAdsTest(unittest.TestCase):
    """ the rubric's regex verdict is attached to every ad, over the untruncated
        title + location + description. An annotation, never a filter: the returned list is
        the input list, whatever the score.
    """

    def test_prescore_is_the_signed_sum_of_matched_weights(self):
        job_ad = make_job_ad("https://acme.example/1",
                                   description="Rotating night-shift on the widget line.")
        [scored] = prescore_job_ads([job_ad], RUBRIC)
        # widgets +3, springfield +2, night-shift -4
        self.assertEqual(scored["prescore"], 1)
        self.assertEqual(sorted(scored["matched_criteria"]),
                         ["night-shift", "springfield", "widgets"])

    def test_matched_criteria_lists_only_matched_names(self):
        job_ad = make_job_ad("https://acme.example/1", description="Daytime widget work.")
        [scored] = prescore_job_ads([job_ad], RUBRIC)
        self.assertEqual(scored["prescore"], 5)
        self.assertNotIn("night-shift", scored["matched_criteria"])

    def test_evidence_in_title_and_location_counts(self):
        # prescore matches against match_text(title, location, description), not description alone
        job_ad = make_job_ad("https://acme.example/1", title="Widget Inspector",
                                   location="Springfield, Utopia",
                                   description="You will check things daily.")
        [scored] = prescore_job_ads([job_ad], RUBRIC)
        self.assertEqual(sorted(scored["matched_criteria"]), ["springfield", "widgets"])

    def test_uses_the_untruncated_description(self):
        # regex has no token budget, so the whole ad is scored, not the prompt excerpt
        description = "x " * EXCERPT_CHARS + "night-shift rota"
        job_ad = make_job_ad("https://acme.example/1", title="Inspector",
                                   location="Metropolis", description=description)
        [scored] = prescore_job_ads([job_ad], RUBRIC)
        self.assertEqual(scored["matched_criteria"], ["night-shift"])
        self.assertEqual(scored["prescore"], -4)

    def test_is_an_annotation_never_a_filter(self):
        # an unmatched criterion on thin ad text is evidence of thin text, not of a bad job
        job_ads = [
            make_job_ad("https://acme.example/1", title="Inspector", location="Metropolis",
                           description=""),
            make_job_ad("https://acme.example/2", title="Inspector", location="Metropolis",
                           description="Permanent night-shift."),
        ]
        scored = prescore_job_ads(job_ads, RUBRIC)
        self.assertEqual(urls(scored), urls(job_ads))
        self.assertEqual([c["prescore"] for c in scored], [0, -4])

    def test_leaves_the_original_fields_intact(self):
        job_ad = make_job_ad("https://acme.example/1")
        [scored] = prescore_job_ads([job_ad], RUBRIC)
        for key, value in job_ad.items():
            self.assertEqual(scored[key], value)


class DescriptionExcerptTest(unittest.TestCase):
    """ the slice of an ad worth prompt tokens: the responsibilities/requirements middle,
        without the opening company blurb or the closing benefits boilerplate, capped at
        EXCERPT_CHARS. Head truncation is the fallback, not the rule.
    """

    BLURB = "About Acme, an employer of many people, founded long ago in a garage. "
    MIDDLE = ("Responsibilities: inspect widgets end to end. "
              "Requirements: three years of widget work. ") * 2
    TAIL = "We offer a competitive package, a bicycle and free fruit."

    def test_starts_at_the_first_section_anchor(self):
        excerpt = description_excerpt(self.BLURB + self.MIDDLE + self.TAIL)
        self.assertTrue(excerpt.startswith("Responsibilities"))
        self.assertNotIn("garage", excerpt)

    def test_ends_at_a_tail_anchor_past_the_guard_position(self):
        excerpt = description_excerpt(self.BLURB + self.MIDDLE + self.TAIL)
        self.assertIn("three years of widget work", excerpt)
        self.assertNotIn("free fruit", excerpt)

    def test_ignores_a_tail_anchor_inside_the_opening_blurb(self):
        # "benefits" appearing in a company blurb is the measured false positive the
        # TAIL_MIN_POSITION guard exists for
        text = "Acme benefits from a strong market position. " + self.MIDDLE
        excerpt = description_excerpt(text)
        self.assertTrue(excerpt.startswith("Responsibilities"))
        self.assertIn("three years of widget work", excerpt)

    def test_falls_back_to_head_truncation_without_an_anchor(self):
        text = "Acme makes widgets in Springfield with a small team. " * 40
        self.assertEqual(description_excerpt(text), text[:EXCERPT_CHARS])

    def test_caps_at_excerpt_chars(self):
        text = self.BLURB + "Responsibilities: inspect widgets. " * 200
        self.assertEqual(len(description_excerpt(text)), EXCERPT_CHARS)

    def test_missing_description_is_empty(self):
        self.assertEqual(description_excerpt(None), "")
        self.assertEqual(description_excerpt(""), "")

    def test_short_description_is_returned_whole(self):
        self.assertEqual(description_excerpt("Widget work."), "Widget work.")


class SummarizeJobAdTest(unittest.TestCase):
    """ one prompt line per ad: the integer id the reply refers back to, the structured
        fields, the prescore annotation, and the excerpt in place of the full description.
    """

    def test_renders_the_id_the_fields_and_the_prescore(self):
        job_ad = {**make_job_ad("https://acme.example/1"), "prescore": 5,
                     "matched_criteria": ["widgets", "springfield"]}
        line = summarize_job_ad(job_ad, 7)
        for expected in ("7", "Widget Inspector", "Acme", "Springfield", "5", "widgets"):
            self.assertIn(expected, line)

    def test_includes_the_description_excerpt_not_the_whole_description(self):
        description = "Responsibilities: inspect widgets. " + "filler text. " * 200
        job_ad = {**make_job_ad("https://acme.example/1", description=description),
                     "prescore": 3, "matched_criteria": ["widgets"]}
        line = summarize_job_ad(job_ad, 0)
        self.assertIn("Responsibilities: inspect widgets.", line)
        self.assertLess(len(line), len(description))

    def test_missing_fields_do_not_raise(self):
        job_ad = {"url": "https://acme.example/1", "job_title": None, "company": None,
                     "location": None, "description": None, "prescore": 0,
                     "matched_criteria": []}
        self.assertIsInstance(summarize_job_ad(job_ad, 0), str)


class CheckBudgetTest(unittest.TestCase):
    """ the guard on invariant 2. Past BUDGET_WARN_JOB_ADS the whole set no longer fits in
        one call, so the count is reported before a ranked cut becomes unavoidable.
    """

    def _job_ads(self, count):
        return [make_job_ad(f"https://acme.example/{i}") for i in range(count)]

    def test_true_and_silent_within_budget(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = check_budget(self._job_ads(BUDGET_WARN_JOB_ADS))
        self.assertTrue(result)
        self.assertEqual(buffer.getvalue(), "")

    def test_false_and_warns_past_budget(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = check_budget(self._job_ads(BUDGET_WARN_JOB_ADS + 1))
        self.assertFalse(result)
        self.assertIn(str(BUDGET_WARN_JOB_ADS + 1), buffer.getvalue())


class SelectBatchTest(unittest.TestCase):
    """ the one LLM call, with jobsearch.preselection.ask_json patched out. Exactly one call
        whatever L is (invariant 2), carrying every survivor plus the resume and preferences,
        and returning the reply unread for validate_selection() to police.
    """

    JOB_ADS = [
        {**make_job_ad(f"https://acme.example/{i}", title=f"Widget Inspector {i}"),
         "prescore": i, "matched_criteria": ["widgets"]}
        for i in range(50)
    ]
    REPLY = {"selected": [{"id": 3, "reason": "closest to the resume"}]}

    def _prompt(self, mock):
        return mock.call_args.args[0] if mock.call_args.args else mock.call_args.kwargs["prompt"]

    def test_makes_exactly_one_call_regardless_of_job_ad_count(self):
        # invariant 2: the call count must not grow with L, so the batch is never chunked
        with patch.object(preselection, "ask_json", return_value=self.REPLY) as ask:
            select_batch(self.JOB_ADS, 10, "resume text", "preferences text")
        self.assertEqual(ask.call_count, 1)

    def test_prompt_carries_the_resume_the_preferences_and_every_job_ad(self):
        with patch.object(preselection, "ask_json", return_value=self.REPLY) as ask:
            select_batch(self.JOB_ADS, 10, "RESUME BODY", "PREFERENCES BODY")
        prompt = self._prompt(ask)
        self.assertIn("RESUME BODY", prompt)
        self.assertIn("PREFERENCES BODY", prompt)
        for job_ad in self.JOB_ADS:
            self.assertIn(job_ad["job_title"], prompt)

    def test_prompt_states_how_many_to_select(self):
        with patch.object(preselection, "ask_json", return_value=self.REPLY) as ask:
            select_batch(self.JOB_ADS, 7, "resume text", "preferences text")
        self.assertIn("7", self._prompt(ask))

    def test_returns_the_raw_reply(self):
        with patch.object(preselection, "ask_json", return_value=self.REPLY):
            self.assertEqual(select_batch(self.JOB_ADS, 10, "r", "p"), self.REPLY)


class ValidateSelectionTest(unittest.TestCase):
    """ a non-compliant reply cannot change how many ads reach evaluation. Out-of-range and
        repeated ids are discarded, a short reply is backfilled by descending prescore, and
        selected + dropped still partition the input.
    """

    JOB_ADS = [
        {**make_job_ad(f"https://acme.example/{i}"), "prescore": prescore,
         "matched_criteria": []}
        for i, prescore in enumerate([1, 9, 5, 7, 3])
    ]

    def test_selects_the_ids_the_reply_names(self):
        reply = {"selected": [{"id": 0, "reason": "first"}, {"id": 4, "reason": "second"}]}
        selected, _ = validate_selection(reply, self.JOB_ADS, 2)
        self.assertEqual(sorted(urls(selected)),
                         ["https://acme.example/0", "https://acme.example/4"])
        self.assertEqual({c["url"]: c["selection_reason"] for c in selected},
                         {"https://acme.example/0": "first", "https://acme.example/4": "second"})

    def test_unselected_job_ads_are_dropped_with_the_stage(self):
        reply = {"selected": [{"id": 0, "reason": "first"}]}
        _, dropped = validate_selection(reply, self.JOB_ADS, 1)
        self.assertEqual(len(dropped), 4)
        self.assertTrue(all(d["stage"] == DROP_NOT_SELECTED for d in dropped))

    def test_selected_and_dropped_partition_the_input(self):
        reply = {"selected": [{"id": 2, "reason": "why"}]}
        selected, dropped = validate_selection(reply, self.JOB_ADS, 1)
        self.assertEqual(sorted(urls(selected) + urls(dropped)), sorted(urls(self.JOB_ADS)))

    def test_out_of_range_ids_are_dropped_with_a_warning(self):
        reply = {"selected": [{"id": 0, "reason": "ok"}, {"id": 99, "reason": "hallucinated"},
                              {"id": -1, "reason": "hallucinated"}]}
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            selected, _ = validate_selection(reply, self.JOB_ADS, 3)
        self.assertIn("https://acme.example/0", urls(selected))
        self.assertIn("99", buffer.getvalue())

    def test_repeated_ids_are_collapsed(self):
        reply = {"selected": [{"id": 1, "reason": "a"}, {"id": 1, "reason": "b"},
                              {"id": 2, "reason": "c"}]}
        selected, _ = validate_selection(reply, self.JOB_ADS, 2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(len(urls(selected)), len(set(urls(selected))))

    def test_short_reply_is_backfilled_by_descending_prescore(self):
        reply = {"selected": [{"id": 0, "reason": "only one"}]}
        selected, _ = validate_selection(reply, self.JOB_ADS, 3)
        self.assertEqual(len(selected), 3)
        # prescores are [1, 9, 5, 7, 3]: the two highest unselected are ids 1 and 3
        self.assertEqual(sorted(urls(selected)),
                         ["https://acme.example/0", "https://acme.example/1",
                          "https://acme.example/3"])

    def test_backfilled_job_ads_carry_a_reason(self):
        reply = {"selected": []}
        selected, _ = validate_selection(reply, self.JOB_ADS, 2)
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(c["selection_reason"] for c in selected))

    def test_reply_longer_than_n_is_truncated_to_n(self):
        reply = {"selected": [{"id": i, "reason": "why"} for i in range(5)]}
        selected, dropped = validate_selection(reply, self.JOB_ADS, 2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(len(dropped), 3)

    def test_fewer_job_ads_than_n_selects_all_of_them(self):
        job_ads = self.JOB_ADS[:2]
        selected, dropped = validate_selection({"selected": []}, job_ads, 10)
        self.assertEqual(len(selected), 2)
        self.assertEqual(dropped, [])

    def test_empty_job_ad_list_selects_nothing(self):
        selected, dropped = validate_selection({"selected": []}, [], 10)
        self.assertEqual(selected, [])
        self.assertEqual(dropped, [])


class PreselectTest(unittest.TestCase):
    """ orchestration, with stage 2's LLM call replaced by a fabricated reply. The stages run
        in order, each stat counts its own survivors, and every discovered ad ends up in
        exactly one of selected/dropped.
    """

    def job_ads(self):
        return [
            # survives, and is the careers-page survivor of a three-way duplicate collapse
            make_job_ad("https://acme.example/careers/1"),
            make_job_ad("https://www.linkedin.com/jobs/view/1"),
            make_job_ad("https://www.jobleads.com/posting/1"),
            # survives on its own
            make_job_ad("https://globex.example/careers/2", company="Globex",
                           title="Widget Engineer"),
            # dropped: stale
            make_job_ad("https://acme.example/careers/3", title="Widget Fitter",
                           days_ago=MAX_AGE_DAYS + 10),
            # dropped: already evaluated
            make_job_ad("https://acme.example/careers/4", title="Widget Packer"),
            # dropped: incomplete
            make_job_ad("https://acme.example/careers/5", title="Widget Sorter",
                        description=None),
        ]

    KNOWN = [("https://other.example/x", "Acme", "Widget Packer", "discarded")]

    def run_preselect(self, job_ads=None, n=1, reply=None):
        job_ads = self.job_ads() if job_ads is None else job_ads
        reply = reply if reply is not None else {"selected": [{"id": 0, "reason": "best fit"}]}
        with patch.object(preselection, "select_batch", return_value=reply) as batch:
            result = preselect(job_ads, n=n, rubric=RUBRIC, resume="resume text",
                               preferences="preferences text", known_job_openings=self.KNOWN)
        return result, batch

    def test_every_job_ad_is_accounted_for_exactly_once(self):
        job_ads = self.job_ads()
        result, _ = self.run_preselect(job_ads)
        accounted = urls(result["selected"]) + urls(result["dropped"])
        self.assertEqual(sorted(accounted), sorted(urls(job_ads)))

    def test_each_stage_drops_what_it_owns(self):
        result, _ = self.run_preselect()
        by_url = {d["job_ad"]["url"]: d["stage"] for d in result["dropped"]}
        self.assertEqual(by_url["https://acme.example/careers/5"], DROP_INCOMPLETE)
        self.assertEqual(by_url["https://acme.example/careers/3"], DROP_STALE)
        self.assertEqual(by_url["https://acme.example/careers/4"], DROP_EVALUATED)
        self.assertEqual(by_url["https://www.linkedin.com/jobs/view/1"], DROP_DUPLICATE)
        self.assertEqual(by_url["https://globex.example/careers/2"], DROP_NOT_SELECTED)

    def test_stats_count_each_stage(self):
        result, _ = self.run_preselect()
        self.assertEqual(result["stats"], {
            "discovered": 7,
            "after_incomplete": 6,
            "after_stale": 5,
            "after_dedup": 3,
            "after_known": 2,
            "selected": 1,
            "llm_calls": 1,
        })

    def test_selected_carry_the_stage_1_annotations(self):
        result, _ = self.run_preselect()
        [selected] = result["selected"]
        self.assertEqual(selected["url"], "https://acme.example/careers/1")
        self.assertEqual(selected["prescore"], 5)
        self.assertEqual(selected["selection_reason"], "best fit")

    def test_stage_2_sees_only_the_survivors(self):
        _, batch = self.run_preselect()
        presented = batch.call_args.args[0]
        self.assertEqual(sorted(urls(presented)),
                         ["https://acme.example/careers/1", "https://globex.example/careers/2"])

    def test_stage_2_receives_the_resume_and_preferences(self):
        _, batch = self.run_preselect()
        passed = list(batch.call_args.args) + list(batch.call_args.kwargs.values())
        self.assertIn("resume text", passed)
        self.assertIn("preferences text", passed)

    def test_exactly_one_llm_call(self):
        _, batch = self.run_preselect()
        self.assertEqual(batch.call_count, 1)

    def test_never_selects_more_than_n(self):
        reply = {"selected": [{"id": i, "reason": "why"} for i in range(2)]}
        result, _ = self.run_preselect(n=1, reply=reply)
        self.assertEqual(len(result["selected"]), 1)
        self.assertEqual(result["stats"]["selected"], 1)

    def test_defaults_to_default_n(self):
        job_ads = [make_job_ad(f"https://acme.example/{i}", title=f"Widget Role {i}")
                      for i in range(DEFAULT_N + 5)]
        with patch.object(preselection, "select_batch", return_value={"selected": []}):
            result = preselect(job_ads, rubric=RUBRIC, resume="r", preferences="p")
        self.assertEqual(len(result["selected"]), DEFAULT_N)

    def test_no_job_ads_returns_empty_result(self):
        with patch.object(preselection, "select_batch", return_value={"selected": []}):
            result = preselect([], rubric=RUBRIC, resume="r", preferences="p")
        self.assertEqual(result["selected"], [])
        self.assertEqual(result["dropped"], [])
        self.assertEqual(result["stats"]["discovered"], 0)


class FormatPreselectionTest(unittest.TestCase):
    """ invariant 3: the listing accounts for every discovered ad, giving the reason for
        each selection and the stage that dropped each of the rest.
    """

    RESULT = {
        "selected": [{**make_job_ad("https://acme.example/1"), "prescore": 5,
                      "matched_criteria": ["widgets"],
                      "selection_reason": "closest to the resume"}],
        "dropped": [
            {"job_ad": make_job_ad("https://globex.example/2", company="Globex",
                                         title="Widget Fitter"),
             "stage": DROP_STALE, "reason": "posted 60 days ago"},
            {"job_ad": make_job_ad("https://www.linkedin.com/jobs/view/3"),
             "stage": DROP_DUPLICATE, "reason": "same job opening as another url"},
        ],
        "stats": {"discovered": 3, "after_incomplete": 3, "after_stale": 2, "after_dedup": 1,
                  "after_known": 1, "selected": 1, "llm_calls": 1},
    }

    def test_lists_the_selected_with_their_reason(self):
        text = format_preselection(self.RESULT)
        self.assertIn("https://acme.example/1", text)
        self.assertIn("closest to the resume", text)

    def test_reports_every_dropped_job_ad_with_its_stage(self):
        # invariant 3: a listing accounts for every job ad discovery produced
        text = format_preselection(self.RESULT)
        self.assertIn("https://globex.example/2", text)
        self.assertIn(DROP_STALE, text)
        self.assertIn("https://www.linkedin.com/jobs/view/3", text)
        self.assertIn(DROP_DUPLICATE, text)

    def test_includes_the_stats(self):
        text = format_preselection(self.RESULT)
        self.assertIn("3", text)
        self.assertIn("1", text)


if __name__ == "__main__":
    unittest.main()
