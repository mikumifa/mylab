from __future__ import annotations

import argparse
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mylab.commands.root as root_module
from mylab.services.notifications import NotificationSettings
from mylab.services.telegram_bot import TelegramSettings


class FakeTelegramBotClient:
    def __init__(self, settings: TelegramSettings) -> None:
        self.settings = settings

    def get_me(self) -> dict[str, object]:
        return {"id": 123, "username": "mylab_test_bot"}


class FakeNotificationClient:
    def __init__(self, run_dir: Path, settings: NotificationSettings) -> None:
        self.run_dir = run_dir
        self.settings = settings

    def notify(self, title: str, body: str, *, notify_type: str = "info") -> bool:
        return True


class BotTestCommandTest(unittest.TestCase):
    def test_cmd_bot_test_sends_feishu_message(self) -> None:
        original_feishu_settings = root_module.load_feishu_settings
        original_feishu_sender = root_module.send_feishu_test_message
        original_telegram_settings = root_module.load_telegram_settings
        original_notification_settings = root_module.resolve_notification_settings
        try:
            root_module.load_feishu_settings = (
                lambda config_path=None: type("FeishuSettings", (), {"enabled": True})()
            )
            called: list[str] = []
            root_module.send_feishu_test_message = (
                lambda settings, message="": called.append(message) or True
            )
            root_module.load_telegram_settings = lambda config_path=None: TelegramSettings(
                bot_token=None,
                allowed_chat_ids=[],
            )
            root_module.resolve_notification_settings = (
                lambda config_path=None: NotificationSettings(urls=[])
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = root_module.cmd_bot_test(argparse.Namespace(config_path=None))
        finally:
            root_module.load_feishu_settings = original_feishu_settings
            root_module.send_feishu_test_message = original_feishu_sender
            root_module.load_telegram_settings = original_telegram_settings
            root_module.resolve_notification_settings = original_notification_settings

        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("feishu bot ok", output)
        self.assertEqual(called, ["This is a test notification from mylab bot test."])

    def test_cmd_bot_test_succeeds_for_configured_integrations(self) -> None:
        original_feishu_settings = root_module.load_feishu_settings
        original_telegram_settings = root_module.load_telegram_settings
        original_telegram_client = root_module.TelegramBotClient
        original_notification_settings = root_module.resolve_notification_settings
        original_notification_client = root_module.NotificationClient
        original_notifications_enabled = root_module.telegram_notifications_enabled
        try:
            root_module.load_feishu_settings = (
                lambda config_path=None: type("FeishuSettings", (), {"enabled": False})()
            )
            root_module.load_telegram_settings = lambda config_path=None: TelegramSettings(
                bot_token="123:abc",
                allowed_chat_ids=[42],
            )
            root_module.TelegramBotClient = FakeTelegramBotClient
            root_module.resolve_notification_settings = (
                lambda config_path=None: NotificationSettings(urls=["tgram://123:abc/42"])
            )
            root_module.NotificationClient = FakeNotificationClient
            root_module.telegram_notifications_enabled = lambda: True

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = root_module.cmd_bot_test(
                    argparse.Namespace(config_path=None)
                )
        finally:
            root_module.load_feishu_settings = original_feishu_settings
            root_module.load_telegram_settings = original_telegram_settings
            root_module.TelegramBotClient = original_telegram_client
            root_module.resolve_notification_settings = original_notification_settings
            root_module.NotificationClient = original_notification_client
            root_module.telegram_notifications_enabled = original_notifications_enabled

        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("telegram bot ok", output)
        self.assertIn("notification endpoints ok", output)

    def test_cmd_bot_test_fails_when_nothing_is_configured(self) -> None:
        original_feishu_settings = root_module.load_feishu_settings
        original_telegram_settings = root_module.load_telegram_settings
        original_notification_settings = root_module.resolve_notification_settings
        try:
            root_module.load_feishu_settings = (
                lambda config_path=None: type("FeishuSettings", (), {"enabled": False})()
            )
            root_module.load_telegram_settings = lambda config_path=None: TelegramSettings(
                bot_token=None,
                allowed_chat_ids=[],
            )
            root_module.resolve_notification_settings = (
                lambda config_path=None: NotificationSettings(urls=[])
            )

            with self.assertRaisesRegex(RuntimeError, "no bot integrations are configured"):
                root_module.cmd_bot_test(argparse.Namespace(config_path=None))
        finally:
            root_module.load_feishu_settings = original_feishu_settings
            root_module.load_telegram_settings = original_telegram_settings
            root_module.resolve_notification_settings = original_notification_settings


if __name__ == "__main__":
    unittest.main()
