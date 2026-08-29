from datetime import date, datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from manmanzhuanqian import (
    DEFAULT_CONFIG,
    DEFAULT_WEATHER_CONFIG,
    ai_request_guard,
    config_from_ai_response,
    config_from_form,
    format_gold_weight,
    format_percent,
    forget_byok_connection,
    get_snapshot,
    normalise_ai_base_url,
    normalise_ai_usage_period,
    normalise_sessions,
    parse_clock,
    request_current_weather,
    request_schedule_suggestion,
    save_byok_connection,
    search_cities,
    weather_icon,
    weather_label,
    weather_snapshot_from_config,
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

    def test_ai_budget_blocks_current_month_and_resets_next_month(self) -> None:
        config = {
            "base_url": "https://api.example.com/v1",
            "model": "my-model",
            "monthly_request_limit": 2,
            "usage_month": "2026-08",
            "request_count": 2,
            "input_tokens": 12,
            "output_tokens": 5,
        }
        current, reason = ai_request_guard(config, date(2026, 8, 29))
        self.assertEqual(current["request_count"], 2)
        self.assertIn("上限", reason or "")
        next_month, reason = ai_request_guard(config, date(2026, 9, 1))
        self.assertIsNone(reason)
        self.assertEqual(next_month["request_count"], 0)
        self.assertEqual(next_month["usage_month"], "2026-09")

    def test_forgetting_byok_connection_removes_only_its_two_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            key_file = folder / "byok.key"
            config_file = folder / "ai.json"
            keep_file = folder / "settings.json"
            key_file.write_bytes(b"encrypted")
            config_file.write_text("{}", encoding="utf-8")
            keep_file.write_text('{"monthly_salary": 40000}', encoding="utf-8")
            forget_byok_connection(key_file, config_file)
            self.assertFalse(key_file.exists())
            self.assertFalse(config_file.exists())
            self.assertTrue(keep_file.exists())

    def test_invalid_budget_does_not_write_a_new_api_key(self) -> None:
        with patch("manmanzhuanqian.save_api_key") as save_key:
            with self.assertRaises(ValueError):
                save_byok_connection("https://api.example.com/v1", "my-model", "new-key", "not-a-number")
        save_key.assert_not_called()

    def test_weather_labels_keep_the_sky_human_and_compact(self) -> None:
        self.assertEqual(weather_label(0), "晴朗")
        self.assertEqual(weather_label(63), "下雨")
        self.assertEqual(weather_label(95), "雷雨")
        self.assertEqual(weather_icon(0, True), "☀")
        self.assertEqual(weather_icon(0, False), "☾")

    def test_city_search_and_weather_request_use_only_selected_city_data(self) -> None:
        class Response:
            def __init__(self, body: bytes) -> None:
                self.body = body

            def read(self) -> bytes:
                return self.body

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        city_response = b'{"results":[{"name":"Shanghai","admin1":"Shanghai","country":"China","latitude":31.23,"longitude":121.47,"timezone":"Asia/Shanghai"}]}'
        weather_response = b'{"current":{"temperature_2m":24.4,"weather_code":61,"wind_speed_10m":12.0,"is_day":1,"time":"2026-08-29T14:30"}}'
        with patch("manmanzhuanqian.urlrequest.urlopen", side_effect=[Response(city_response), Response(weather_response)]) as mocked_open:
            cities = search_cities("上海")
            weather = request_current_weather({"city": cities[0]["city"], "latitude": cities[0]["latitude"], "longitude": cities[0]["longitude"]})
        self.assertEqual(cities[0]["city"], "Shanghai")
        self.assertEqual(weather.city, "Shanghai")
        self.assertEqual(weather.weather_code, 61)
        self.assertEqual(weather.temperature, 24.4)
        search_url = mocked_open.call_args_list[0].args[0]
        forecast_url = mocked_open.call_args_list[1].args[0]
        self.assertIn("name=%E4%B8%8A%E6%B5%B7", search_url)
        self.assertIn("latitude=31.23", forecast_url)
        self.assertNotIn("monthly_salary", forecast_url)

    def test_weather_snapshot_uses_local_cache_without_a_network_request(self) -> None:
        config = {
            **DEFAULT_WEATHER_CONFIG,
            "enabled": True,
            "city": "上海",
            "latitude": 31.23,
            "longitude": 121.47,
            "last_weather": {
                "weather_code": 2,
                "temperature": 26.0,
                "wind_speed": 8.0,
                "is_day": True,
                "observed_at": "2026-08-29T14:30",
            },
        }
        snapshot = weather_snapshot_from_config(config)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.city if snapshot else "", "上海")


if __name__ == "__main__":
    unittest.main()
