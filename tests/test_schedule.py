from datetime import datetime
import json
import unittest
from unittest.mock import patch

from manmanzhuanqian import (
    DEFAULT_CONFIG,
    config_from_ai_response,
    config_from_form,
    format_gold_weight,
    format_percent,
    get_snapshot,
    normalise_ai_base_url,
    normalise_sessions,
    parse_clock,
    request_schedule_suggestion,
)


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {
            **DEFAULT_CONFIG,
            "monthly_salary": 21750,
            "paid_days": 22,
            "sessions": [
                {"start": "09:00", "end": "12:00"},
                {"start": "13:00", "end": "18:00"},
            ],
            "workdays": [0, 1, 2, 3, 4],
        }

    def test_before_work_has_no_value(self) -> None:
        snapshot = get_snapshot(datetime(2026, 8, 24, 8, 30), self.config)  # Monday
        self.assertEqual(snapshot.phase, "upcoming")
        self.assertEqual(snapshot.earned, 0)

    def test_lunch_is_not_paid_time(self) -> None:
        snapshot = get_snapshot(datetime(2026, 8, 24, 12, 30), self.config)
        self.assertEqual(snapshot.phase, "pause")
        self.assertEqual(snapshot.progress, 3 / 8)
        self.assertAlmostEqual(snapshot.earned, 21750 / 22 * 3 / 8)

    def test_after_work_reaches_daily_value(self) -> None:
        snapshot = get_snapshot(datetime(2026, 8, 24, 18, 1), self.config)
        self.assertEqual(snapshot.phase, "complete")
        self.assertEqual(snapshot.progress, 1)
        self.assertAlmostEqual(snapshot.earned, 21750 / 22)

    def test_rest_day_does_not_accumulate(self) -> None:
        snapshot = get_snapshot(datetime(2026, 8, 29, 14, 0), self.config)  # Saturday
        self.assertEqual(snapshot.phase, "off")
        self.assertEqual(snapshot.earned, 0)

    def test_overnight_shift_continues_after_midnight(self) -> None:
        config = {
            **self.config,
            "sessions": [{"start": "22:00", "end": "06:00"}],
        }
        snapshot = get_snapshot(datetime(2026, 8, 25, 2, 0), config)
        self.assertEqual(snapshot.anchor_day.isoformat(), "2026-08-24")
        self.assertEqual(snapshot.phase, "earning")
        self.assertEqual(snapshot.progress, 0.5)

    def test_time_parser_and_normalisation(self) -> None:
        self.assertEqual(parse_clock(" 9:05 "), 545)
        result = normalise_sessions([
            {"start": "13:00", "end": "18:00"},
            {"start": "09:00", "end": "12:00"},
        ])
        self.assertEqual(result[0]["start"], "09:00")

    def test_display_units_are_clear_and_unpadded(self) -> None:
        self.assertEqual(format_percent(0.608), "60.8%")
        self.assertEqual(format_gold_weight(417.2), "1.49g")

    def test_saved_form_values_immediately_change_the_calculation(self) -> None:
        before = get_snapshot(datetime(2026, 8, 24, 10, 0), self.config)
        updated = config_from_form(self.config, "43500", "22", "09:00 - 12:00", "13:00 - 18:00", "1、2、3、4、5")
        after = get_snapshot(datetime(2026, 8, 24, 10, 0), updated)
        self.assertEqual(updated["monthly_salary"], 43500)
        self.assertGreater(after.earned, before.earned)

    def test_ai_response_becomes_an_uncommitted_validated_schedule(self) -> None:
        proposal = config_from_ai_response(
            self.config,
            '''{"monthly_salary": 40000, "paid_days": 22, "sessions": [{"start": "09:30", "end": "12:00"}, {"start": "13:30", "end": "18:30"}], "workdays": [0, 1, 2, 3, 4]}''',
        )
        self.assertEqual(proposal["monthly_salary"], 40000)
        self.assertEqual(proposal["paid_days"], 22)
        self.assertEqual(proposal["sessions"][1]["end"], "18:30")
        self.assertEqual(proposal["workdays"], [0, 1, 2, 3, 4])
        self.assertEqual(self.config["monthly_salary"], 21750)

    def test_ai_endpoint_rejects_insecure_non_local_hosts(self) -> None:
        self.assertEqual(normalise_ai_base_url("https://api.example.com/v1/"), "https://api.example.com/v1")
        self.assertEqual(normalise_ai_base_url("http://127.0.0.1:11434/v1"), "http://127.0.0.1:11434/v1")
        with self.assertRaises(ValueError):
            normalise_ai_base_url("http://api.example.com/v1")

    def test_byok_request_only_contains_the_explicit_description(self) -> None:
        class Response:
            def read(self) -> bytes:
                return b'{"choices":[{"message":{"content":"{}"}}],"usage":{"prompt_tokens":12,"completion_tokens":5}}'

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        description = "我月薪 4 万，每月按 22 天算"
        with patch("manmanzhuanqian.urlrequest.urlopen", return_value=Response()) as mocked_open:
            _content, usage = request_schedule_suggestion(description, {"base_url": "https://api.example.com/v1", "model": "my-model"}, "test-key")
        request = mocked_open.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.example.com/v1/chat/completions")
        self.assertEqual(payload["messages"][1]["content"], description)
        self.assertNotIn("monthly_salary", payload["messages"][1]["content"])
        self.assertEqual(usage["prompt_tokens"], 12)


if __name__ == "__main__":
    unittest.main()
