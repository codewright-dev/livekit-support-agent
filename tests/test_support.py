import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from support_agent.desk import SupportDesk, within_support_hours
from support_agent.retrieval import ManualIndex, split_sections, tokenize

MANUAL = Path(__file__).resolve().parent.parent / "manual" / "aeroflow-t2.md"


class RetrievalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = ManualIndex.from_file(MANUAL)

    def top(self, q):
        return self.index.search(q, top_k=1)[0][0].title

    def test_splits_on_headings(self):
        titles = [s.title for s in split_sections(MANUAL.read_text())]
        self.assertIn("Wi-Fi setup", titles)
        self.assertIn("Error codes", titles)

    def test_finds_the_right_section_for_natural_questions(self):
        cases = {
            "my thermostat won't connect to my 5 gigahertz wifi": "Wi-Fi setup",
            "the light is blinking amber": "Status light",
            "screen shows E3": "Error codes",
            "how do I reboot it": "Restart and factory reset",
            "can I get a refund": "Warranty and returns",
            "does it work with baseboard heaters": "Compatibility",
            "I don't have a C-wire": "Compatibility",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(self.top(question), expected)

    def test_tokenizer_maps_synonyms_and_drops_stopwords(self):
        self.assertEqual(tokenize("How do I fix the WiFi?"), ["fix", "wi-fi"])


class DeskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = SupportDesk(ManualIndex.from_file(MANUAL), self.tmp.name, today=date(2026, 11, 20))

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_returns_excerpts_with_titles(self):
        out = self.desk.search_manual("what does error E1 mean")
        self.assertIn("[Error codes]", out)
        self.assertIn("C-wire", out)

    def test_search_admits_when_manual_has_no_answer(self):
        for q in ["can I control my garage door with it?", "does it support alexa", "what is the price"]:
            with self.subTest(q=q):
                self.assertTrue(self.desk.search_manual(q).startswith("NOT_IN_MANUAL"))
        for q in ["the screen says E1", "can I return it, I bought it two weeks ago", "how long does the battery last"]:
            with self.subTest(q=q):
                self.assertFalse(self.desk.search_manual(q).startswith("NOT_IN_MANUAL"))

    def test_warranty(self):
        r = self.desk.check_warranty("AF-T2-123456", "2025-06-01")
        self.assertTrue(r["in_warranty"])
        self.assertFalse(r["refund_eligible"])
        self.assertEqual(r["warranty_expires"], "2027-06-01")
        self.assertFalse(self.desk.check_warranty("AF-T2-123456", "2024-01-10")["in_warranty"])
        self.assertTrue(self.desk.check_warranty("af t2 654321", "2026-11-05")["refund_eligible"])

    def test_warranty_rejects_bad_input(self):
        self.assertFalse(self.desk.check_warranty("12345", "2025-06-01")["ok"])
        self.assertFalse(self.desk.check_warranty("AF-T2-123456", "last summer")["ok"])
        self.assertFalse(self.desk.check_warranty("AF-T2-123456", "2027-01-01")["ok"])

    def test_ticket_is_saved_and_has_a_speakable_id(self):
        r = self.desk.create_ticket("Sam Rivera", "+1 555 0199", "E2 keeps returning after restart", "urgent")
        self.assertTrue(r["ok"])
        saved = json.loads((Path(self.tmp.name) / f"{r['ticket_id']}.json").read_text())
        self.assertEqual(saved["priority"], "urgent")
        self.assertEqual(len(r["spoken_id"].split()), 6)

    def test_ticket_requires_contact_details(self):
        self.assertFalse(self.desk.create_ticket("", "+1 555 0199", "x")["ok"])
        self.assertFalse(self.desk.create_ticket("Sam", "12", "x")["ok"])


class HoursTest(unittest.TestCase):
    def test_support_hours(self):
        self.assertTrue(within_support_hours(datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)))  # Wed 10:00 ET
        self.assertFalse(within_support_hours(datetime(2026, 11, 18, 2, 0, tzinfo=timezone.utc)))  # Tue 21:00 ET
        self.assertFalse(within_support_hours(datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc)))  # Saturday


if __name__ == "__main__":
    unittest.main()
