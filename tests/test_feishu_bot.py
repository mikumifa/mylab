from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mylab.services.feishu_bot as feishu_bot
from mylab.services.feishu_bot import (
    build_feishu_post_content,
    interactive_feishu_setup,
    load_feishu_settings,
    send_feishu_message,
)


class FeishuBotTest(unittest.TestCase):
    def test_build_feishu_post_content_uses_post_markdown(self) -> None:
        content = build_feishu_post_content(
            "mylab summary ready",
            "**done**\n[link](https://example.com)",
        )
        self.assertEqual(content["zh_cn"]["title"], "mylab summary ready")
        self.assertEqual(content["zh_cn"]["content"][0][0]["tag"], "md")
        self.assertIn("**done**", content["zh_cn"]["content"][0][0]["text"])

    def test_load_feishu_settings_from_section(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mylab-feishu-") as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[feishu]",
                        'webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/abc"',
                        'default_check_command = "pytest -q"',
                        "bidirectional_control_enabled = true",
                        'app_id = "cli_a"',
                        'app_secret = "secret_a"',
                        'chat_id = "oc_123"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            settings = load_feishu_settings(config_path)

            self.assertEqual(
                settings.webhook_url,
                "https://open.feishu.cn/open-apis/bot/v2/hook/abc",
            )
            self.assertEqual(settings.default_check_command, "pytest -q")
            self.assertTrue(settings.bidirectional_enabled)

    def test_interactive_setup_writes_section_and_notification_url(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mylab-feishu-") as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            answers = iter(
                [
                    "",
                    "y",
                    "cli_a",
                    "oc_123",
                    "https://open.feishu.cn/open-apis/bot/v2/hook/abc",
                ]
            )

            path = interactive_feishu_setup(
                config_path=config_path,
                input_fn=lambda _prompt="": next(answers),
                secret_input_fn=lambda _prompt="": "secret_a",
            )

            self.assertEqual(path, config_path)
            settings = load_feishu_settings(config_path)
            self.assertEqual(
                settings.webhook_url,
                "https://open.feishu.cn/open-apis/bot/v2/hook/abc",
            )
            self.assertTrue(settings.bidirectional_control_enabled)
            self.assertEqual(settings.app_id, "cli_a")
            self.assertEqual(settings.app_secret, "secret_a")
            self.assertEqual(settings.chat_id, "oc_123")
            content = config_path.read_text(encoding="utf-8")
            self.assertIn("[feishu]", content)
            self.assertIn(
                'urls = ["https://open.feishu.cn/open-apis/bot/v2/hook/abc"]',
                content,
            )

    def test_load_feishu_settings_falls_back_to_notification_urls(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mylab-feishu-") as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[notifications]",
                        'urls = ["https://open.larksuite.com/open-apis/bot/v2/hook/abc"]',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            settings = load_feishu_settings(config_path)

            self.assertEqual(
                settings.webhook_url,
                "https://open.larksuite.com/open-apis/bot/v2/hook/abc",
            )

    def test_interactive_setup_can_skip_bidirectional_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mylab-feishu-") as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            answers = iter(
                [
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )

            path = interactive_feishu_setup(
                config_path=config_path,
                input_fn=lambda _prompt="": next(answers),
                secret_input_fn=lambda _prompt="": "",
            )

            self.assertEqual(path, config_path)
            settings = load_feishu_settings(config_path)
            self.assertFalse(settings.bidirectional_control_enabled)
            self.assertIsNone(settings.app_id)
            self.assertIsNone(settings.webhook_url)

    def test_send_feishu_message_uses_post_payloads(self) -> None:
        calls: list[tuple[str, dict[str, object], dict[str, str]]] = []
        original_post_json = feishu_bot._post_json
        try:
            feishu_bot._post_json = lambda url, payload, headers: (
                calls.append((url, payload, headers)) or {"code": 0}
            )
            sent = send_feishu_message(
                feishu_bot.FeishuSettings(
                    webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/abc"
                ),
                title="mylab bot test",
                message="**hello**",
            )
        finally:
            feishu_bot._post_json = original_post_json

        self.assertTrue(sent)
        self.assertEqual(calls[0][1]["msg_type"], "post")
        self.assertEqual(
            calls[0][1]["content"]["post"]["zh_cn"]["title"],
            "mylab bot test",
        )
        self.assertEqual(
            calls[0][1]["content"]["post"]["zh_cn"]["content"][0][0]["tag"],
            "md",
        )
        self.assertEqual(
            calls[0][1]["content"]["post"]["zh_cn"]["content"][0][0]["text"],
            "**hello**",
        )


if __name__ == "__main__":
    unittest.main()
