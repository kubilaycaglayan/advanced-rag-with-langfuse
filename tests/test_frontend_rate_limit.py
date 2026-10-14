"""Rolling production question quotas persist and remain atomic."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.frontend_rate_limit import WINDOWS, reserve_request


class FrontendRateLimitTests(TestCase):
    def test_each_rolling_window_and_exact_expiry(self):
        self.assertEqual(WINDOWS, ((60, 3), (1800, 10), (3600, 15), (86400, 25)))
        for seconds, maximum in WINDOWS:
            with self.subTest(seconds=seconds), TemporaryDirectory() as directory, \
                 patch("app.frontend_rate_limit.WINDOWS", ((seconds, maximum),)):
                path = Path(directory) / "quotas.sqlite3"
                for _ in range(maximum):
                    self.assertIsNone(reserve_request("198.51.100.9", path=path, now_ms=0))
                self.assertEqual(reserve_request("198.51.100.9", path=path, now_ms=0), seconds)
                self.assertEqual(reserve_request("198.51.100.9", path=path, now_ms=seconds * 1000 - 1), 1)
                self.assertIsNone(reserve_request("198.51.100.9", path=path, now_ms=seconds * 1000))

    def test_rejections_do_not_consume_quota_and_ips_are_independent(self):
        with TemporaryDirectory() as directory, patch("app.frontend_rate_limit.WINDOWS", ((60, 1),)):
            path = Path(directory) / "quotas.sqlite3"
            self.assertIsNone(reserve_request("198.51.100.9", path=path, now_ms=0))
            self.assertEqual(reserve_request("198.51.100.9", path=path, now_ms=1000), 59)
            self.assertEqual(reserve_request("198.51.100.9", path=path, now_ms=2000), 58)
            self.assertIsNone(reserve_request("203.0.113.8", path=path, now_ms=2000))
            self.assertIsNone(reserve_request("198.51.100.9", path=path, now_ms=60000))

    def test_combined_windows_apply_to_one_ip(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "quotas.sqlite3"
            reserve_at_minute = lambda minute: reserve_request("198.51.100.9", path=path, now_ms=minute * 60_000)
            for minute in range(0, 30, 3):
                self.assertIsNone(reserve_at_minute(minute))
            self.assertEqual(reserve_at_minute(28), 120)
            for minute in range(30, 45, 3):
                self.assertIsNone(reserve_at_minute(minute))
            self.assertEqual(reserve_at_minute(45), 900)
            for minute in range(60, 90, 3):
                self.assertIsNone(reserve_at_minute(minute))
            self.assertEqual(reserve_at_minute(90), 81_000)
            self.assertIsNone(reserve_at_minute(1440))

    def test_parallel_reservations_cannot_exceed_quota(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "quotas.sqlite3"
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(lambda _: reserve_request("198.51.100.9", path=path, now_ms=0), range(4)))
            self.assertEqual(outcomes.count(None), 3)
            self.assertEqual(outcomes.count(60), 1)
