import unittest
from unittest.mock import patch
from io import StringIO

from src.wrappers.StreamLogger import StreamLogger


class TestStreamLogger(unittest.TestCase):

    def setUp(self):
        self.stream = StringIO()
        self.logger = StreamLogger(self.stream)

    def test_info_writes_formatted_message(self):
        with patch("src.wrappers.StreamLogger.datetime") as mock_dt:
            mock_dt.now.return_value.astimezone.return_value.strftime.return_value = "2026-01-01 12:00:00 UTC"
            mock_dt.side_effect = lambda *a, **kw: mock_dt
            self.logger.info("hello world")
        output = self.stream.getvalue()
        self.assertIn("[INFO]", output)
        self.assertIn("hello world", output)
        self.assertIn("2026-01-01 12:00:00 UTC", output)

    def test_debug_writes_formatted_message(self):
        with patch("src.wrappers.StreamLogger.datetime") as mock_dt:
            mock_dt.now.return_value.astimezone.return_value.strftime.return_value = "2026-01-01 12:00:00 UTC"
            self.logger.debug("debug msg")
        output = self.stream.getvalue()
        self.assertIn("[DEBUG]", output)
        self.assertIn("debug msg", output)

    def test_warning_writes_formatted_message(self):
        with patch("src.wrappers.StreamLogger.datetime") as mock_dt:
            mock_dt.now.return_value.astimezone.return_value.strftime.return_value = "2026-01-01 12:00:00 UTC"
            self.logger.warning("watch out")
        output = self.stream.getvalue()
        self.assertIn("[WARNING]", output)
        self.assertIn("watch out", output)

    def test_error_writes_formatted_message(self):
        with patch("src.wrappers.StreamLogger.datetime") as mock_dt:
            mock_dt.now.return_value.astimezone.return_value.strftime.return_value = "2026-01-01 12:00:00 UTC"
            self.logger.error("something broke")
        output = self.stream.getvalue()
        self.assertIn("[ERROR]", output)
        self.assertIn("something broke", output)

    def test_critical_writes_formatted_message(self):
        with patch("src.wrappers.StreamLogger.datetime") as mock_dt:
            mock_dt.now.return_value.astimezone.return_value.strftime.return_value = "2026-01-01 12:00:00 UTC"
            self.logger.critical("system down")
        output = self.stream.getvalue()
        self.assertIn("[CRITICAL]", output)
        self.assertIn("system down", output)

    def test_output_ends_with_newline(self):
        with patch("src.wrappers.StreamLogger.datetime") as mock_dt:
            mock_dt.now.return_value.astimezone.return_value.strftime.return_value = "2026-01-01 12:00:00 UTC"
            self.logger.info("test")
        output = self.stream.getvalue()
        self.assertTrue(output.endswith("\n"))

    def test_log_format_matches_expected_pattern(self):
        with patch("src.wrappers.StreamLogger.datetime") as mock_dt:
            mock_dt.now.return_value.astimezone.return_value.strftime.return_value = "2026-01-01 12:00:00 UTC"
            self.logger.info("formatted")
        output = self.stream.getvalue().strip()
        self.assertEqual(output, "[2026-01-01 12:00:00 UTC] [INFO] formatted")

    def test_multiple_logs_append_to_stream(self):
        with patch("src.wrappers.StreamLogger.datetime") as mock_dt:
            mock_dt.now.return_value.astimezone.return_value.strftime.return_value = "2026-01-01 12:00:00 UTC"
            self.logger.info("first")
            self.logger.error("second")
        output = self.stream.getvalue()
        lines = output.strip().split("\n")
        self.assertEqual(len(lines), 2)
        self.assertIn("[INFO]", lines[0])
        self.assertIn("[ERROR]", lines[1])

    def test_is_instance_of_ilogger(self):
        from src.Interfaces.ILogger import ILogger
        self.assertIsInstance(self.logger, ILogger)


if __name__ == '__main__':
    unittest.main()
