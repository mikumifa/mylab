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
                        urls=["tgram://token/chat/"],
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
                self.assertEqual(fake_apprise.urls, ["tgram://token/chat/"])
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


if __name__ == "__main__":
    unittest.main()
