from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mylab.services.telegram_bot as telegram_bot
from mylab.services.telegram_bot import (
    TelegramBotClient,
    TelegramSettings,
    interactive_telegram_setup,
    load_feedback_context,
    load_persistent_feedback_context,
    load_telegram_settings,
    push_summary_to_telegram,
)


class FakeTelegramBot(TelegramBotClient):
    def __init__(
        self, settings: TelegramSettings, updates: list[dict[str, object]]
    ) -> None:
        super().__init__(settings)
        self._updates = updates
        self.sent_messages: list[tuple[int, str]] = []
        self.sent_documents: list[tuple[int, str, str | None]] = []
        self.downloads: dict[str, bytes] = {"documents/test.txt": b"hello"}

    def get_updates(self) -> list[dict[str, object]]:
        return self._updates

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent_messages.append((chat_id, text))

    def get_file_path(self, file_id: str) -> str:
        return "documents/test.txt"

    def download_file(self, file_path: str) -> bytes:
        return self.downloads[file_path]

    def send_document(
        self, chat_id: int, file_path: Path, *, caption: str | None = None
    ) -> None:
        self.sent_documents.append((chat_id, file_path.name, caption))


class TelegramBotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-telegram-")
        self.root = Path(self.temp_dir.name)
        self.original_state = telegram_bot.TELEGRAM_STATE_FILE
        self.original_inbox = telegram_bot.TELEGRAM_INBOX_FILE
        self.original_file_dir = telegram_bot.TELEGRAM_FILE_DIR
        telegram_bot.TELEGRAM_STATE_FILE = self.root / "state.json"
        telegram_bot.TELEGRAM_INBOX_FILE = self.root / "inbox" / "messages.jsonl"
        telegram_bot.TELEGRAM_FILE_DIR = self.root / "inbox" / "files"

    def tearDown(self) -> None:
        telegram_bot.TELEGRAM_STATE_FILE = self.original_state
        telegram_bot.TELEGRAM_INBOX_FILE = self.original_inbox
        telegram_bot.TELEGRAM_FILE_DIR = self.original_file_dir
        self.temp_dir.cleanup()

    def test_load_telegram_settings_from_config(self) -> None:
        config_path = self.root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[telegram]",
                    'bot_token = "123:abc"',
                    "allowed_chat_ids = [42]",
                    "poll_interval_seconds = 3",
                    "feedback_context_limit = 2",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        settings = load_telegram_settings(config_path)

        self.assertEqual(settings.bot_token, "123:abc")
        self.assertEqual(settings.allowed_chat_ids, [42])
        self.assertEqual(settings.poll_interval_seconds, 3)
        self.assertEqual(settings.feedback_context_limit, 2)

    def test_interactive_setup_writes_config(self) -> None:
        config_path = self.root / "config.toml"
        answers = iter(["y", "42,43", "7", "9", "424242"])

        path = interactive_telegram_setup(
            config_path=config_path,
            input_fn=lambda _prompt="": next(answers),
            secret_input_fn=lambda _prompt="": "123:abc",
        )

        self.assertEqual(path, config_path)
        settings = load_telegram_settings(config_path)
        self.assertEqual(settings.bot_token, "123:abc")
        self.assertEqual(settings.allowed_chat_ids, [42, 43])
        self.assertEqual(settings.poll_interval_seconds, 7)
        self.assertEqual(settings.feedback_context_limit, 9)
        content = config_path.read_text(encoding="utf-8")
        self.assertIn('urls = ["tgram://123:abc/424242"]', content)

    def test_interactive_setup_accepts_token_only(self) -> None:
        config_path = self.root / "config.toml"
        answers = iter([""])

        path = interactive_telegram_setup(
            config_path=config_path,
            input_fn=lambda _prompt="": next(answers),
            secret_input_fn=lambda _prompt="": "123:abc",
        )

        self.assertEqual(path, config_path)
        settings = load_telegram_settings(config_path)
        self.assertEqual(settings.bot_token, "123:abc")
        self.assertEqual(settings.allowed_chat_ids, [])
        self.assertEqual(settings.poll_interval_seconds, 5)
        self.assertEqual(settings.feedback_context_limit, 5)
        content = config_path.read_text(encoding="utf-8")
        self.assertNotIn("tgram://", content)

    def test_interactive_setup_accepts_none_config_path(self) -> None:
        custom_home_config = self.root / ".mylab" / "config.toml"
        original_config_file = telegram_bot.CONFIG_FILE
        telegram_bot.CONFIG_FILE = custom_home_config
        answers = iter([""])
        try:
            path = interactive_telegram_setup(
                config_path=None,
                input_fn=lambda _prompt="": next(answers),
                secret_input_fn=lambda _prompt="": "123:abc",
            )
        finally:
            telegram_bot.CONFIG_FILE = original_config_file

        self.assertEqual(path, custom_home_config)
        self.assertTrue(custom_home_config.exists())
        settings = load_telegram_settings(custom_home_config)
        self.assertEqual(settings.bot_token, "123:abc")

    def test_on_off_text_and_document_are_persisted_with_scopes(self) -> None:
        updates = [
            {
                "update_id": 1,
                "message": {"message_id": 9, "chat": {"id": 42}, "text": "/test"},
            },
            {
                "update_id": 2,
                "message": {"message_id": 10, "chat": {"id": 42}, "text": "/off"},
            },
            {
                "update_id": 3,
                "message": {"message_id": 11, "chat": {"id": 42}, "text": "/on"},
            },
            {
                "update_id": 4,
                "message": {"message_id": 15, "chat": {"id": 42}, "text": "/continue"},
            },
            {
                "update_id": 5,
                "message": {
                    "message_id": 12,
                    "chat": {"id": 42},
                    "text": "next round compare with a lighter baseline",
                },
            },
            {
                "update_id": 6,
                "message": {
                    "message_id": 14,
                    "chat": {"id": 42},
                    "text": "/run always keep the lightweight baseline in scope",
                },
            },
            {
                "update_id": 7,
                "message": {
                    "message_id": 13,
                    "chat": {"id": 42},
                    "document": {"file_id": "file-1", "file_name": "notes.txt"},
                },
            },
        ]
        bot = FakeTelegramBot(
            TelegramSettings(bot_token="123:abc", allowed_chat_ids=[42]),
            updates,
        )

        processed = bot.poll_once()

        self.assertEqual(processed, 7)
        state = json.loads(telegram_bot.TELEGRAM_STATE_FILE.read_text(encoding="utf-8"))
        self.assertTrue(state["notifications_enabled"])
        self.assertEqual(state["last_update_id"], 7)

        inbox_lines = telegram_bot.TELEGRAM_INBOX_FILE.read_text(
            encoding="utf-8"
        ).splitlines()
        records = [json.loads(line) for line in inbox_lines]
        kinds = [record["kind"] for record in records]
        scopes = [record.get("scope", "-") for record in records]
        self.assertEqual(
            kinds,
            ["command", "command", "command", "text", "text", "text", "document"],
        )
        self.assertEqual(scopes, ["-", "-", "-", "step", "step", "run", "run"])
        self.assertTrue((telegram_bot.TELEGRAM_FILE_DIR / "13-notes.txt").exists())

        context = load_feedback_context(limit=5)
        self.assertIn("lighter baseline", context)
        self.assertIn("Continue to the next full iteration", context)
        self.assertIn("scope=step", context)
        self.assertIn("scope=run", context)
        self.assertIn("13-notes.txt", context)
        persistent_context = load_persistent_feedback_context(limit=5)
        self.assertIn("always keep the lightweight baseline in scope", persistent_context)
        self.assertNotIn("next round compare", persistent_context)
        self.assertEqual(
            bot.sent_messages,
            [
                (42, "mylab telegram bot ok."),
                (42, "mylab notifications paused."),
                (42, "mylab notifications enabled."),
                (
                    42,
                    "Queued the next iteration using the latest run context.",
                ),
                (
                    42,
                    "Feedback saved for the next iteration. Use /run <text> for persistent run guidance.",
                ),
                (
                    42,
                    "Run guidance saved. It will be carried into future iterations.",
                ),
                (42, "File saved: 13-notes.txt"),
            ],
        )

    def test_push_summary_to_telegram_sends_text_and_documents(self) -> None:
        config_path = self.root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[telegram]",
                    'bot_token = "123:abc"',
                    "",
                    "[notifications]",
                    'urls = ["tgram://123:abc/42"]',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        summary_path = self.root / "run" / "summaries" / "plan-001.summary.md"
        result_path = self.root / "run" / "results" / "plan-001.result.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        summary_content = "\n".join(
            [
                "# Summary Metadata",
                "- run_id: run",
                "- plan_id: plan-001",
                "",
                "# Outcome",
                "Validation accuracy reached 91.2%.",
                "",
                "# Evidence",
                "1. results/metrics.json",
                "",
                "# Artifacts",
                "1. summaries/plan-001.summary.md",
                "",
                "# Next Iteration",
                "1. Compare against the lighter baseline.",
            ]
        )
        summary_path.write_text(summary_content, encoding="utf-8")
        result_path.write_text("# Outcome\nDetailed result\n", encoding="utf-8")
        run_dir = self.root / "run"
        (run_dir / "manifests").mkdir(parents=True, exist_ok=True)
        from mylab.domain import RunManifest
        from mylab.storage.runs import save_manifest, init_run_dirs

        paths = init_run_dirs(run_dir)
        save_manifest(
            paths,
            RunManifest(
                run_id="run-001",
                repo_path=str(self.root / "repo"),
                source_branch="main",
                goal_file=str(self.root / "goal.txt"),
                runs_env_var="MYLAB_RUNS_DIR",
                notify_urls=["tgram://123:abc/42"],
            ),
        )

        original_config = telegram_bot.CONFIG_FILE
        original_client = telegram_bot.TelegramBotClient
        try:
            telegram_bot.CONFIG_FILE = config_path
            fake_bot = FakeTelegramBot(
                TelegramSettings(bot_token="123:abc", allowed_chat_ids=[42]),
                [],
            )
            telegram_bot.TelegramBotClient = lambda settings: fake_bot
            sent = push_summary_to_telegram(
                run_dir,
                "plan-001",
                summary_path,
                summary_content=summary_content,
            )
        finally:
            telegram_bot.CONFIG_FILE = original_config
            telegram_bot.TelegramBotClient = original_client

        self.assertTrue(sent)
        self.assertEqual(len(fake_bot.sent_messages), 1)
        self.assertIn("Reply /continue to proceed", fake_bot.sent_messages[0][1])
        self.assertIn("Validation accuracy reached 91.2%", fake_bot.sent_messages[0][1])
        self.assertEqual(
            fake_bot.sent_documents,
            [
                (42, "plan-001.summary.md", "plan-001 summary"),
                (42, "plan-001.result.md", "plan-001 result"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
