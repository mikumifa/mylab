from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.services.notifications import (
    NotificationClient,
    NotificationSettings,
    resolve_notification_settings,
)
from mylab.storage.runs import init_run_dirs


class FakeApprise:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.configs: list[object] = []
        self.calls: list[dict[str, object]] = []

    def add(self, value: object) -> None:
        if isinstance(value, str):
            self.urls.append(value)
        else:
            self.configs.append(value)

    def notify(self, **payload: object) -> bool:
        self.calls.append(payload)
        return True


class FakeAppriseConfig:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def add(self, value: str) -> None:
        self.paths.append(value)


class NotificationServiceTest(unittest.TestCase):
    def test_resolve_notification_settings_from_user_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mylab-config-") as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[notifications]",
                        'urls = ["tgram://token/chat/", "discord://token/channel"]',
                        'config_path = "/tmp/apprise.yaml"',
                        'tag = "mylab"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            settings = resolve_notification_settings(config_path)

            self.assertEqual(
                settings.urls,
                ["tgram://token/chat/", "discord://token/channel"],
            )
            self.assertEqual(settings.config_path, "/tmp/apprise.yaml")
            self.assertEqual(settings.tag, "mylab")

    def test_notification_client_uses_apprise_urls_and_logs_delivery(self) -> None:
        fake_apprise = FakeApprise()
        fake_module = types.SimpleNamespace(
            Apprise=lambda: fake_apprise,
            AppriseConfig=FakeAppriseConfig,
            NotifyType=types.SimpleNamespace(
                INFO="INFO",
                SUCCESS="SUCCESS",
                WARNING="WARNING",
                FAILURE="FAILURE",
            ),
        )
        original_module = sys.modules.get("apprise")
        sys.modules["apprise"] = fake_module
        try:
            with tempfile.TemporaryDirectory(prefix="mylab-notify-") as temp_dir:
                run_dir = Path(temp_dir) / "run-001"
                init_run_dirs(run_dir)
                client = NotificationClient(
                    run_dir,
                    NotificationSettings(
                        urls=["discord://token/channel"],
                        config_path="/tmp/apprise.yaml",
                        tag="lab",
                    ),
                )

                sent = client.notify(
                    "mylab summary ready",
                    "plan-001 completed",
                    notify_type="success",
                )

                self.assertTrue(sent)
                self.assertEqual(fake_apprise.urls, ["discord://token/channel"])
                self.assertEqual(len(fake_apprise.configs), 1)
                self.assertEqual(fake_apprise.calls[0]["title"], "mylab summary ready")
                self.assertEqual(fake_apprise.calls[0]["body"], "plan-001 completed")
                self.assertEqual(fake_apprise.calls[0]["tag"], "lab")
                self.assertEqual(fake_apprise.calls[0]["notify_type"], "SUCCESS")

                log_lines = (
                    (run_dir / "logs" / "notifications.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
                events = [json.loads(line)["event"] for line in log_lines]
                self.assertEqual(events, ["notifier_ready", "notify_sent"])
        finally:
            if original_module is None:
                sys.modules.pop("apprise", None)
            else:
                sys.modules["apprise"] = original_module

    def test_notification_client_skips_feishu_urls_for_apprise(self) -> None:
        import mylab.services.notifications as notifications_module

        fake_apprise = FakeApprise()
        fake_module = types.SimpleNamespace(
            Apprise=lambda: fake_apprise,
            AppriseConfig=FakeAppriseConfig,
            NotifyType=types.SimpleNamespace(INFO="INFO"),
        )
        original_module = sys.modules.get("apprise")
        original_sender = notifications_module.send_feishu_message
        original_loader = notifications_module.load_feishu_settings
        sys.modules["apprise"] = fake_module
        try:
            notifications_module.load_feishu_settings = lambda config_path=None: type(
                "FeishuSettings",
                (),
                {"enabled": True},
            )()
            notifications_module.send_feishu_message = lambda settings, message: True
            with tempfile.TemporaryDirectory(prefix="mylab-notify-") as temp_dir:
                run_dir = Path(temp_dir) / "run-001"
                init_run_dirs(run_dir)
                client = NotificationClient(
                    run_dir,
                    NotificationSettings(
                        urls=[
                            "https://open.feishu.cn/open-apis/bot/v2/hook/abc",
                            "discord://token/channel",
                        ]
                    ),
                )

                sent = client.notify("title", "body")

                self.assertTrue(sent)
                self.assertEqual(fake_apprise.urls, ["discord://token/channel"])
        finally:
            notifications_module.send_feishu_message = original_sender
            notifications_module.load_feishu_settings = original_loader
            if original_module is None:
                sys.modules.pop("apprise", None)
            else:
                sys.modules["apprise"] = original_module

    def test_notification_client_sends_to_feishu_without_apprise(self) -> None:
        import mylab.services.notifications as notifications_module

        original_sender = notifications_module.send_feishu_message
        original_loader = notifications_module.load_feishu_settings
        original_module = sys.modules.get("apprise")
        sys.modules.pop("apprise", None)
        sent_messages: list[str] = []
        try:
            notifications_module.load_feishu_settings = lambda config_path=None: type(
                "FeishuSettings",
                (),
                {"enabled": True},
            )()
            notifications_module.send_feishu_message = (
                lambda settings, message: sent_messages.append(message) or True
            )
            with tempfile.TemporaryDirectory(prefix="mylab-notify-") as temp_dir:
                run_dir = Path(temp_dir) / "run-001"
                init_run_dirs(run_dir)
                client = NotificationClient(run_dir, NotificationSettings(urls=[]))

                sent = client.notify(
                    "mylab summary ready",
                    "plan-001 completed",
                    notify_type="success",
                )

                self.assertTrue(sent)
                self.assertEqual(
                    sent_messages,
                    ["mylab summary ready\n\nplan-001 completed"],
                )
        finally:
            notifications_module.send_feishu_message = original_sender
            notifications_module.load_feishu_settings = original_loader
            if original_module is not None:
                sys.modules["apprise"] = original_module

    def test_notification_client_sends_to_telegram_directly(self) -> None:
        import mylab.services.notifications as notifications_module

        original_sender = notifications_module.send_telegram_notification
        original_loader = notifications_module.load_telegram_settings
        sent_payloads: list[tuple[str, str, str]] = []
        try:
            notifications_module.load_telegram_settings = lambda config_path=None: type(
                "TelegramSettings",
                (),
                {"enabled": True},
            )()
            notifications_module.send_telegram_notification = (
                lambda settings, urls, *, title, body, notify_type="info": (
                    sent_payloads.append((title, body, notify_type)) or True
                )
            )
            with tempfile.TemporaryDirectory(prefix="mylab-notify-") as temp_dir:
                run_dir = Path(temp_dir) / "run-001"
                init_run_dirs(run_dir)
                client = NotificationClient(
                    run_dir,
                    NotificationSettings(urls=["tgram://token/42"]),
                )

                sent = client.notify(
                    "mylab summary ready",
                    "plan-001 completed",
                    notify_type="success",
                )

                self.assertTrue(sent)
                self.assertEqual(
                    sent_payloads,
                    [("mylab summary ready", "plan-001 completed", "success")],
                )
        finally:
            notifications_module.send_telegram_notification = original_sender
            notifications_module.load_telegram_settings = original_loader

    def test_notification_client_skips_telegram_urls_for_apprise(self) -> None:
        import mylab.services.notifications as notifications_module

        fake_apprise = FakeApprise()
        fake_module = types.SimpleNamespace(
            Apprise=lambda: fake_apprise,
            AppriseConfig=FakeAppriseConfig,
            NotifyType=types.SimpleNamespace(INFO="INFO"),
        )
        original_module = sys.modules.get("apprise")
        original_sender = notifications_module.send_telegram_notification
        original_loader = notifications_module.load_telegram_settings
        sys.modules["apprise"] = fake_module
        try:
            notifications_module.load_telegram_settings = lambda config_path=None: type(
                "TelegramSettings",
                (),
                {"enabled": True},
            )()
            notifications_module.send_telegram_notification = (
                lambda settings, urls, *, title, body, notify_type="info": True
            )
            with tempfile.TemporaryDirectory(prefix="mylab-notify-") as temp_dir:
                run_dir = Path(temp_dir) / "run-001"
                init_run_dirs(run_dir)
                client = NotificationClient(
                    run_dir,
                    NotificationSettings(
                        urls=[
                            "tgram://token/42",
                            "discord://token/channel",
                        ]
                    ),
                )

                sent = client.notify("title", "body")

                self.assertTrue(sent)
                self.assertEqual(fake_apprise.urls, ["discord://token/channel"])
        finally:
            notifications_module.send_telegram_notification = original_sender
            notifications_module.load_telegram_settings = original_loader
            if original_module is None:
                sys.modules.pop("apprise", None)
            else:
                sys.modules["apprise"] = original_module

    def test_resolve_notification_settings_includes_feishu_webhook(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mylab-config-") as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[feishu]",
                        'webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/abc"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            settings = resolve_notification_settings(config_path)

            self.assertEqual(
                settings.urls,
                ["https://open.feishu.cn/open-apis/bot/v2/hook/abc"],
            )

    def test_resolve_notification_settings_filters_invalid_url_entries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mylab-config-") as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[notifications]",
                        'urls = ["tgram://token/chat/", ""]',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            settings = resolve_notification_settings(config_path)

            self.assertEqual(settings.urls, ["tgram://token/chat/"])


if __name__ == "__main__":
    unittest.main()
