"""
Tests for WasseLead.

The cases that matter most are the ones where getting it wrong would cost the
client money or reputation:

  - messaging the same person twice, because two rows had the same number
    written differently;
  - messaging someone who explicitly opted out;
  - replying to a booking with a sales pitch instead of a confirmation;
  - promising a reply time and then missing it silently.

Standard library only, so a client can run the suite with plain python3.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "src" / "wasselead.py"

_spec = importlib.util.spec_from_file_location("wasselead", MODULE_PATH)
wl = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["wasselead"] = wl  # dataclasses resolve types via sys.modules
_spec.loader.exec_module(wl)

NOW = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
BIZ = {
    "name": "Apollo Clinic",
    "owner_name": "Dr. Meera",
    "slots": {"price": "₹600 per session.", "offer": "Free first assessment."},
}


def ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


def lead(**kw) -> "wl.Lead":
    base = dict(name="Test", phone="9876543210", message="hello",
                received_at=ago(hours=1))
    base.update(kw)
    return wl.Lead(**base)


class TestPhoneNormalisation(unittest.TestCase):
    """The same human must always reduce to the same key."""

    def test_all_formats_of_one_number_agree(self):
        formats = ["+91 98765 43210", "098765 43210", "9876543210",
                   "919876543210", "00919876543210", "+91-98765-43210"]
        results = {wl.normalise_phone(f) for f in formats}
        self.assertEqual(results, {"919876543210"})

    def test_different_numbers_stay_different(self):
        self.assertNotEqual(wl.normalise_phone("9876543210"),
                            wl.normalise_phone("9876543211"))

    def test_international_number_is_preserved(self):
        self.assertEqual(wl.normalise_phone("+1 415 555 2671"), "14155552671")

    def test_rejects_garbage(self):
        for bad in ["", "abc", "12"]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                wl.normalise_phone(bad)

    def test_rejects_none(self):
        with self.assertRaises(ValueError):
            wl.normalise_phone(None)  # type: ignore[arg-type]


class TestUrgency(unittest.TestCase):
    def test_opt_out_beats_everything(self):
        l = lead(opted_out=True, replied=True, message="price?")
        self.assertIs(l.urgency(), wl.LeadUrgency.DO_NOT_DISTURB)

    def test_reply_without_answer_is_hot(self):
        self.assertIs(lead(replied=True, message="hello").urgency(), wl.LeadUrgency.HOT)

    def test_question_is_hot(self):
        self.assertIs(lead(message="do you have slots?").urgency(), wl.LeadUrgency.HOT)

    def test_price_question_is_hot(self):
        self.assertIs(lead(message="what are the charges").urgency(), wl.LeadUrgency.HOT)

    def test_interest_is_warm(self):
        self.assertIs(lead(message="I am interested in the package").urgency(),
                      wl.LeadUrgency.WARM)

    def test_plain_hello_is_cold(self):
        self.assertIs(lead(message="hello").urgency(), wl.LeadUrgency.COLD)

    def test_booked_is_not_hot(self):
        # A booking must not trigger an urgent sales message.
        self.assertIs(lead(booked=True, message="price?").urgency(),
                      wl.LeadUrgency.COLD)


class TestQueue(unittest.TestCase):
    def test_opted_out_lead_is_never_queued(self):
        r = wl.build_queue([lead(opted_out=True)], BIZ, NOW)
        self.assertEqual(r.items, [])
        self.assertEqual(len(r.skipped), 1)

    def test_duplicate_number_is_queued_once(self):
        """Two rows, one person — the client must not message them twice."""
        leads = [
            lead(name="Priya", phone="+91 98765 43210", received_at=ago(hours=5)),
            lead(name="P. Sharma", phone="09876543210", received_at=ago(hours=4)),
        ]
        r = wl.build_queue(leads, BIZ, NOW)
        self.assertEqual(len(r.items), 1)
        self.assertTrue(any("duplicate" in reason for _, reason in r.skipped))

    def test_lead_with_no_phone_is_skipped_not_crashed(self):
        r = wl.build_queue([lead(phone="")], BIZ, NOW)
        self.assertEqual(r.items, [])
        self.assertIn("no digits", r.skipped[0][1])

    def test_hot_comes_before_warm_and_cold(self):
        # Names must not themselves be trigger words, or this would test
        # keyword matching rather than ordering.
        # Distinct phones, or duplicate detection (correctly) eats two of them.
        leads = [
            lead(name="Anita", phone="9876500001", message="hello", received_at=ago(days=3)),
            lead(name="Rohit", phone="9876500002", message="what is the price?", received_at=ago(hours=5)),
            lead(name="Rahul", phone="9876500003", message="interested", received_at=ago(days=1)),
        ]
        r = wl.build_queue(leads, BIZ, NOW)
        self.assertEqual([i.lead.name for i in r.items], ["Rohit", "Rahul", "Anita"])
        self.assertEqual([i.urgency for i in r.items],
                         [wl.LeadUrgency.HOT, wl.LeadUrgency.WARM, wl.LeadUrgency.COLD])

    def test_booked_lead_gets_a_confirmation_not_a_pitch(self):
        r = wl.build_queue([lead(booked=True, received_at=ago(days=1))], BIZ, NOW)
        msg = r.items[0].message
        self.assertIn("confirming your appointment", msg)
        self.assertNotIn("₹600", msg)

    def test_hot_lead_is_due_within_two_hours(self):
        r = wl.build_queue([lead(message="price?", received_at=ago(hours=1))], BIZ, NOW)
        # received 1h ago, hot window is 2h, so it is due 1h from now
        self.assertEqual(r.items[0].due_at, NOW + timedelta(hours=1))

    def test_cold_lead_is_due_in_two_days(self):
        r = wl.build_queue([lead(message="hello", received_at=ago(days=1))], BIZ, NOW)
        self.assertEqual(r.items[0].due_at, NOW - timedelta(days=1) + timedelta(days=2))

    def test_bad_timestamp_is_skipped_with_a_reason(self):
        r = wl.build_queue([lead(received_at="not-a-date")], BIZ, NOW)
        self.assertEqual(r.items, [])
        self.assertIn("timestamp", r.skipped[0][1])

    def test_naive_timestamp_is_treated_as_utc(self):
        # Spreadsheet exports drop the timezone; that must not crash the tool.
        l = lead(received_at="2026-09-30T10:00:00")
        r = wl.build_queue([l], BIZ, NOW)
        self.assertEqual(len(r.items), 1)

    def test_overdue_is_reported(self):
        r = wl.build_queue([lead(message="price?", received_at=ago(days=5))], BIZ, NOW)
        self.assertTrue(r.items[0].overdue(NOW))

    def test_not_overdue_when_recent(self):
        r = wl.build_queue([lead(message="price?", received_at=ago(minutes=5))], BIZ, NOW)
        self.assertFalse(r.items[0].overdue(NOW))

    def test_empty_input_does_not_crash(self):
        r = wl.build_queue([], BIZ, NOW)
        self.assertEqual(r.items, [])
        self.assertEqual(r.total, 0)


class TestMessages(unittest.TestCase):
    def test_uses_first_name_only(self):
        msg = wl.compose_message(lead(name="Priya Sharma"), BIZ, NOW)
        self.assertTrue(msg.startswith("Hi Priya,"))
        self.assertNotIn("Sharma", msg)

    def test_answers_a_price_question_directly(self):
        msg = wl.compose_message(lead(message="what are the charges?"), BIZ, NOW)
        self.assertIn("₹600", msg)

    def test_no_double_punctuation(self):
        """Slot text ends in a full stop; we must not add a second one."""
        for text in ("₹600 per session.", "₹600 per session", "₹600 per session.."):
            biz = {**BIZ, "slots": {"price": text, "offer": text}}
            with self.subTest(text=text):
                self.assertNotIn("..", wl.compose_message(lead(message="price?"), biz, NOW))
                self.assertNotIn("..", wl.compose_message(lead(message="hello"), biz, NOW))

    def test_sentences_are_separated(self):
        """Slot text must end a sentence, not run into the next clause.

        Regression: clean() used to strip the trailing full stop and the
        template never put one back, producing "this month Shall I share".
        """
        for text in ("Free first assessment", "Free first assessment.", "Free first assessment.."):
            biz = {**BIZ, "slots": {"offer": text}}
            with self.subTest(text=text):
                msg = wl.compose_message(lead(message="hello"), biz, NOW)
                self.assertIn("assessment. Shall", msg)
                self.assertNotIn("assessment Shall", msg)

    def test_names_the_owner_and_business(self):
        msg = wl.compose_message(lead(), BIZ, NOW)
        self.assertIn("Dr. Meera", msg)
        self.assertIn("Apollo Clinic", msg)

    def test_works_without_a_business_config(self):
        """A client must get something usable before they fill in their details."""
        msg = wl.compose_message(lead(), {}, NOW)
        self.assertTrue(msg)

    def test_handles_a_missing_name(self):
        msg = wl.compose_message(lead(name=""), BIZ, NOW)
        self.assertIn("Hi there", msg)


class TestIO(unittest.TestCase):
    def test_reads_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.json"
            p.write_text(json.dumps([{"name": "A", "phone": "9876543210",
                                      "message": "hi", "received_at": ago(hours=1)}]))
            leads = wl.load_leads(p)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].name, "A")

    def test_reads_csv(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.csv"
            p.write_text(
                "name,phone,message,received_at\n"
                f"A,9876543210,hi,{ago(hours=1)}\n"
            )
            leads = wl.load_leads(p)
        self.assertEqual(leads[0].name, "A")

    def test_csv_boolean_columns_parse(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.csv"
            p.write_text(
                "name,phone,message,received_at,opted_out\n"
                f"A,9876543210,hi,{ago(hours=1)},true\n"
            )
            leads = wl.load_leads(p)
        self.assertTrue(leads[0].opted_out)

    def test_csv_missing_optional_columns_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.csv"
            p.write_text(f"name,phone,message,received_at\nA,9876543210,hi,{ago(hours=1)}\n")
            leads = wl.load_leads(p)
        self.assertFalse(leads[0].opted_out)

    def test_json_report_is_valid_and_complete(self):
        r = wl.build_queue([lead(message="price?")], BIZ, NOW)
        data = json.loads(r.to_json())
        self.assertEqual(data["counts"]["hot"], 1)
        self.assertEqual(data["queue"][0]["phone"], "919876543210")
        self.assertIn("message", data["queue"][0])

    def test_example_files_are_valid(self):
        leads = wl.load_leads(ROOT / "examples" / "leads.json")
        biz = wl.load_business(ROOT / "examples" / "business.json")
        report = wl.build_queue(leads, biz, NOW)
        self.assertGreater(len(report.items), 0)
        self.assertGreater(len(report.skipped), 0)


class TestCLI(unittest.TestCase):
    def test_help_exits_zero(self):
        self.assertEqual(wl.main(["--help"]), 0)

    def test_missing_file_exits_nonzero(self):
        self.assertEqual(wl.main(["/nope/nothing.csv"]), 1)

    def test_runs_end_to_end(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = wl.main([str(ROOT / "examples" / "leads.json"),
                            "--business", str(ROOT / "examples" / "business.json"),
                            "--now", NOW.isoformat()])
        self.assertEqual(code, 0)
        self.assertIn("Follow-up", buf.getvalue().title().replace("Lead Follow-Up", "Follow-up"))




class TestOptOutDetection(unittest.TestCase):
    """Opt-out detection is safety-critical: messaging someone who asked to be
    left alone is far worse than skipping one lead too many."""

    def test_message_text_opt_out_is_detected(self):
        for text in (
            "Please remove me from this list",
            "stop messaging me",
            "unsubscribe please",
            "I am not interested",
            "do not contact me again",
            "Don't call me",
            "leave me alone",
            "delete my number",
            "no longer wish to receive these",
        ):
            with self.subTest(text=text):
                self.assertTrue(wl.looks_opted_out(text))

    def test_normal_enquiries_are_not_opt_out(self):
        for text in (
            "What are the charges for a cleaning?",
            "interested, tell me more",
            "Do you have slots tomorrow?",
            "ok",
            "how much for 8 sessions",
            "I stopped jogging last year, can I still join?",
        ):
            with self.subTest(text=text):
                self.assertFalse(wl.looks_opted_out(text))

    def test_text_opt_out_lead_never_reaches_queue(self):
        lead = wl.Lead(name="Sana", phone="9876500001",
                    message="Please remove me", received_at="2026-01-01T00:00:00+00:00")
        self.assertEqual(lead.urgency(), wl.LeadUrgency.DO_NOT_DISTURB)

    def test_explicit_flag_still_wins(self):
        lead = wl.Lead(name="Aman", phone="9876500002", message="What are charges?",
                    received_at="2026-01-01T00:00:00+00:00", opted_out=True)
        self.assertEqual(lead.urgency(), wl.LeadUrgency.DO_NOT_DISTURB)

    def test_empty_message_is_safe(self):
        self.assertFalse(wl.looks_opted_out(""))
        self.assertFalse(wl.looks_opted_out(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)