import unittest
import json
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from src.containers.TelegramReportingServiceContainer import TelegramReportingServiceContainer


class TestTelegramReportingServiceContainerConfiguration(unittest.TestCase):
    """Test configuration loading and mode selection in TelegramReportingServiceContainer"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.original_dir = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        os.chdir(self.original_dir)
        # Clean up temp directory
        for file in os.listdir(self.temp_dir):
            os.remove(os.path.join(self.temp_dir, file))
        os.rmdir(self.temp_dir)

    def create_config_file(self, config):
        """Helper to create a config.json file"""
        with open("config.json", "w") as f:
            json.dump(config, f)

    def test_http_mode_5_json_file(self):
        """Test that APP_MODE 5 (JSON file + HTTP) is properly configured"""
        config = {
            "categories": [
                {"prefix": "test", "description": "Test category"}
            ],
            "APP_MODE": 5,
            "JSON_PATH": ".",
            "HTTP_URL": "0.0.0.0",
            "HTTP_PORT": "8080",
            "HTTP_TOKEN": "test_token",
            "HTTP_CHAT_ID": "1",
            "DEDICATION_TIME": "2p"
        }
        self.create_config_file(config)

        with patch('telegram.Bot'), \
             patch('src.wrappers.HttpUserCommService.web.Server'):
            container = TelegramReportingServiceContainer()
            
            # Verify HTTP mode is detected (as integer)
            self.assertEqual(int(container.tryGetConfig("APP_MODE")), 5)
            
            # Verify HTTP configuration values are loaded
            self.assertEqual(container.tryGetConfig("HTTP_URL"), "0.0.0.0")
            self.assertEqual(container.tryGetConfig("HTTP_PORT"), "8080")
            self.assertEqual(container.tryGetConfig("HTTP_TOKEN"), "test_token")
            self.assertEqual(container.tryGetConfig("HTTP_CHAT_ID"), "1")

    def test_http_mode_6_obsidian(self):
        """Test that APP_MODE 6 (Obsidian + HTTP) is properly configured"""
        config = {
            "categories": [
                {"prefix": "test", "description": "Test category"}
            ],
            "APP_MODE": 6,
            "JSON_PATH": ".",
            "OBSIDIAN_VAULT_PATH": ".",
            "APPDATA": ".",
            "HTTP_URL": "localhost",
            "HTTP_PORT": "9090",
            "HTTP_TOKEN": "secure_token",
            "HTTP_CHAT_ID": "2",
            "CONTEXT_MISSING_POLICY": "0",
            "DATE_MISSING_POLICY": "0",
            "DEDICATION_TIME": "2p"
        }
        self.create_config_file(config)

        with patch('telegram.Bot'), \
             patch('src.wrappers.HttpUserCommService.web.Server'):
            container = TelegramReportingServiceContainer()
            
            # Verify HTTP mode is detected (as integer)
            self.assertEqual(int(container.tryGetConfig("APP_MODE")), 6)
            
            # Verify HTTP configuration values are loaded
            self.assertEqual(container.tryGetConfig("HTTP_URL"), "localhost")
            self.assertEqual(container.tryGetConfig("HTTP_PORT"), "9090")
            self.assertEqual(container.tryGetConfig("HTTP_TOKEN"), "secure_token")
            self.assertEqual(container.tryGetConfig("HTTP_CHAT_ID"), "2")
            
            # Verify Obsidian configuration is also present
            self.assertEqual(container.tryGetConfig("OBSIDIAN_VAULT_PATH"), ".")

    def test_telegram_mode_3_still_works(self):
        """Test that existing APP_MODE 3 (JSON file + Telegram) still works"""
        config = {
            "categories": [
                {"prefix": "test", "description": "Test category"}
            ],
            "APP_MODE": 3,
            "JSON_PATH": ".",
            "TELEGRAM_BOT_TOKEN": "test_bot_token",
            "TELEGRAM_CHAT_ID": "12345",
            "DEDICATION_TIME": "2p"
        }
        self.create_config_file(config)

        with patch('telegram.Bot'):
            container = TelegramReportingServiceContainer()
            
            # Verify Telegram mode is detected (as integer)
            self.assertEqual(int(container.tryGetConfig("APP_MODE")), 3)
            
            # Verify Telegram configuration values are loaded
            self.assertEqual(container.tryGetConfig("TELEGRAM_BOT_TOKEN"), "test_bot_token")
            self.assertEqual(container.tryGetConfig("TELEGRAM_CHAT_ID"), "12345")

    def test_cmd_mode_1_still_works(self):
        """Test that existing APP_MODE 1 (Obsidian + cmd) still works"""
        config = {
            "categories": [
                {"prefix": "test", "description": "Test category"}
            ],
            "APP_MODE": 1,
            "JSON_PATH": ".",
            "OBSIDIAN_VAULT_PATH": ".",
            "APPDATA": ".",
            "CONTEXT_MISSING_POLICY": "0",
            "DATE_MISSING_POLICY": "0",
            "DEDICATION_TIME": "2p"
        }
        self.create_config_file(config)

        with patch('telegram.Bot'):
            container = TelegramReportingServiceContainer()
            
            # Verify cmd mode is detected (as integer)
            self.assertEqual(int(container.tryGetConfig("APP_MODE")), 1)
            
            # Verify Obsidian configuration values are loaded
            self.assertEqual(container.tryGetConfig("OBSIDIAN_VAULT_PATH"), ".")


if __name__ == '__main__':
    unittest.main()
