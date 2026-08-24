from datetime import datetime
import unittest

from manmanzhuanqian import DEFAULT_CONFIG, get_snapshot, normalise_sessions, parse_clock


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {
            **DEFAULT_CONFIG,
            "monthly_salary": 21750,
            "paid_days": 21.75,
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
        self.assertEqual(snapshot.earned, 375)

    def test_after_work_reaches_daily_value(self) -> None:
        snapshot = get_snapshot(datetime(2026, 8, 24, 18, 1), self.config)
        self.assertEqual(snapshot.phase, "complete")
        self.assertEqual(snapshot.progress, 1)
        self.assertEqual(snapshot.earned, 1000)

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


if __name__ == "__main__":
    unittest.main()
