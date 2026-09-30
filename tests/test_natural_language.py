import os
import unittest
from datetime import datetime
from unittest.mock import patch

from backend.services.natural_language import VagueSearchError, parse_natural_language


class NaturalLanguageSearchTests(unittest.TestCase):
    @patch("backend.services.natural_language._parse_with_llm")
    def test_llm_gets_first_chance_to_interpret_context(self, parse_with_llm):
        parse_with_llm.return_value = {
            "actionable": True,
            "clarification": "",
            "type": "classroom",
            "attendees": 1,
            "equipment": [],
            "date": "2026-09-30",
            "start_time": "16:00",
            "end_time": "17:00",
        }
        with patch.dict(os.environ, {"LLM_API_KEY": "test-key"}):
            result = parse_natural_language(
                "somewhere for a discussion around 4pm",
                datetime(2026, 9, 30, 10, 15),
            )

        self.assertEqual(result["type"], "classroom")
        self.assertEqual(result["start_time"], "16:00")

    @patch("backend.services.natural_language._parse_with_llm")
    def test_llm_clarification_is_returned_for_vague_context(self, parse_with_llm):
        parse_with_llm.return_value = {
            "actionable": False,
            "clarification": "Please include the time you need the lab.",
            "type": "lab",
            "attendees": 1,
            "equipment": [],
            "date": "2026-09-30",
            "start_time": "10:00",
            "end_time": "11:00",
        }
        with patch.dict(os.environ, {"LLM_API_KEY": "test-key"}):
            with self.assertRaisesRegex(VagueSearchError, "include the time"):
                parse_natural_language(
                    "I need a lab",
                    datetime(2026, 9, 30, 10, 15),
                )

    def test_everyday_room_meeting_wording_is_understood(self):
        with patch.dict(os.environ, {"LLM_API_KEY": ""}):
            result = parse_natural_language(
                "book a room for 5 faculties for a faculty meeting "
                "from 8am till 12am for day after tomorrow",
                datetime(2026, 9, 30, 10, 15),
            )

        self.assertEqual(result["type"], "classroom")
        self.assertEqual(result["attendees"], 5)
        self.assertEqual(result["date"], "2026-10-02")
        self.assertEqual(result["start_time"], "08:00")
        self.assertEqual(result["end_time"], "12:00")

    def test_query_without_a_time_is_rejected_as_vague(self):
        with patch.dict(os.environ, {"LLM_API_KEY": ""}):
            with self.assertRaisesRegex(VagueSearchError, "include a time"):
                parse_natural_language(
                    "I need a lab",
                    datetime(2026, 9, 30, 10, 15),
                )

    def test_compact_attendees_and_quarter_hour_use_next_valid_window(self):
        with patch.dict(os.environ, {"LLM_API_KEY": ""}):
            result = parse_natural_language(
                "I need a lab for 10people from 8am to 9:45 am",
                datetime(2026, 9, 30, 10, 15),
            )

        self.assertEqual(result["type"], "lab")
        self.assertEqual(result["attendees"], 10)
        self.assertEqual(result["date"], "2026-10-01")
        self.assertEqual(result["start_time"], "08:00")
        self.assertEqual(result["end_time"], "10:00")


if __name__ == "__main__":
    unittest.main()
