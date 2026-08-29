from datetime import datetime
import unittest

from manmanzhuanqian import config_from_form, DEFAULT_CONFIG, format_gold_weight, format_percent, get_snapshot, normalise_sessions, parse_clock


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


if __name__ == "__main__":
    unittest.main()
