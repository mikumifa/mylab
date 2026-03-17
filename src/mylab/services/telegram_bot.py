from __future__ import annotations

import json
import time
import tomllib
import urllib.parse
import urllib.request
from getpass import getpass
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mylab.config import (
    CONFIG_FILE,
    TELEGRAM_FILE_DIR,
    TELEGRAM_INBOX_FILE,
    TELEGRAM_STATE_FILE,
)
from mylab.logging import logger
from mylab.storage import append_jsonl, ensure_dir, read_json, write_json, write_text
from mylab.utils import utc_now


def _read_config(config_path: Path | None = None) -> dict[str, object]:
    target = config_path or CONFIG_FILE
    if not target.exists():
        return {}
    with target.open("rb") as handle:
        payload = tomllib.load(handle)
    return payload if isinstance(payload, dict) else {}


def _format_toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    raise TypeError(f"unsupported config value: {value!r}")


def _split_notify_values(values: str) -> list[str]:
    parts = []
    for chunk in values.replace("\n", ",").split(","):
        value = chunk.strip()
        if value:
            parts.append(value)
    return parts


def write_user_config(payload: dict[str, object], path: Path = CONFIG_FILE) -> Path:
    lines: list[str] = []
    for section_name, section_value in payload.items():
        if not isinstance(section_name, str) or not isinstance(section_value, dict):
            continue
        lines.append(f"[{section_name}]")
        for key, value in section_value.items():
            if value is None:
                continue
            lines.append(f"{key} = {_format_toml_value(value)}")
        lines.append("")
    write_text(path, "\n".join(lines).rstrip())
    return path


@dataclass
class TelegramSettings:
    bot_token: str | None
    allowed_chat_ids: list[int]
    poll_interval_seconds: int = 5
    feedback_context_limit: int = 5

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token)


def load_telegram_settings(config_path: Path | None = None) -> TelegramSettings:
    payload = _read_config(config_path)
    section = payload.get("telegram", {})
    if not isinstance(section, dict):
        return TelegramSettings(bot_token=None, allowed_chat_ids=[])
    bot_token = section.get("bot_token")
    raw_ids = section.get("allowed_chat_ids", [])
    chat_ids: list[int] = []
    if isinstance(raw_ids, list):
        for item in raw_ids:
            try:
                chat_ids.append(int(item))
            except Exception:
                continue
    poll_interval = section.get("poll_interval_seconds", 5)
    feedback_limit = section.get("feedback_context_limit", 5)
    return TelegramSettings(
        bot_token=bot_token
        if isinstance(bot_token, str) and bot_token.strip()
        else None,
        allowed_chat_ids=chat_ids,
        poll_interval_seconds=int(poll_interval)
        if isinstance(poll_interval, int)
        else 5,
        feedback_context_limit=(
            int(feedback_limit) if isinstance(feedback_limit, int) else 5
        ),
    )


def configure_telegram_bot(
    *,
    bot_token: str,
    allowed_chat_ids: list[int],
    poll_interval_seconds: int,
    feedback_context_limit: int,
    notification_chat_id: int | None,
    config_path: Path = CONFIG_FILE,
) -> Path:
    payload = _read_config(config_path)
    telegram_section = payload.get("telegram", {})
    if not isinstance(telegram_section, dict):
        telegram_section = {}
    telegram_section.update(
        {
            "bot_token": bot_token.strip(),
            "allowed_chat_ids": allowed_chat_ids,
            "poll_interval_seconds": poll_interval_seconds,
            "feedback_context_limit": feedback_context_limit,
        }
    )
    payload["telegram"] = telegram_section

    notifications = payload.get("notifications", {})
    if not isinstance(notifications, dict):
        notifications = {}
    raw_urls = notifications.get("urls", [])
    existing_urls: list[str] = []
    if isinstance(raw_urls, list):
        existing_urls = [str(item).strip() for item in raw_urls if str(item).strip()]
    elif isinstance(raw_urls, str):
        existing_urls = _split_notify_values(raw_urls)
    preserved_urls = [item for item in existing_urls if not item.startswith("tgram://")]
    if notification_chat_id is not None:
        preserved_urls.insert(0, f"tgram://{bot_token.strip()}/{notification_chat_id}")
    notifications["urls"] = preserved_urls
    payload["notifications"] = notifications
    return write_user_config(payload, config_path)


def interactive_telegram_setup(
    *,
    config_path: Path = CONFIG_FILE,
    input_fn: Any = input,
    secret_input_fn: Any = getpass,
) -> Path:
    current = _read_config(config_path)
    telegram = current.get("telegram", {})
    notifications = current.get("notifications", {})
    telegram = telegram if isinstance(telegram, dict) else {}
    notifications = notifications if isinstance(notifications, dict) else {}

    current_token = str(telegram.get("bot_token", "")).strip()
    current_chat_ids = telegram.get("allowed_chat_ids", [])
    current_poll = int(telegram.get("poll_interval_seconds", 5))
    current_feedback_limit = int(telegram.get("feedback_context_limit", 5))

    print(f"Config file: {config_path}")
    print("Telegram only requires a bot token. Advanced fields are optional.")
    token = secret_input_fn(
        f"Telegram bot token [{'*' * 8 if current_token else 'required'}]: "
    ).strip()
    if not token:
        token = current_token
    if not token:
        raise ValueError("telegram bot token is required")

    advanced_text = (
        input_fn("Configure advanced Telegram fields? [y/N]: ").strip().lower()
    )
    use_advanced = advanced_text in {"y", "yes"}

    existing_urls = notifications.get("urls", [])
    default_notify_chat = ""
    if isinstance(existing_urls, list):
        for item in existing_urls:
            value = str(item)
            if value.startswith("tgram://"):
                suffix = value.removeprefix("tgram://")
                if "/" in suffix:
                    default_notify_chat = suffix.split("/", 1)[1]
                    break
    if use_advanced:
        default_chat_ids = ""
        if isinstance(current_chat_ids, list) and current_chat_ids:
            default_chat_ids = ",".join(str(int(item)) for item in current_chat_ids)
        chat_id_text = input_fn(
            f"Allowed chat ids, comma-separated [{default_chat_ids or 'blank=allow any'}]: "
        ).strip()
        if not chat_id_text:
            allowed_chat_ids = (
                [int(item) for item in current_chat_ids]
                if isinstance(current_chat_ids, list)
                else []
            )
        else:
            allowed_chat_ids = [
                int(part.strip()) for part in chat_id_text.split(",") if part.strip()
            ]

        poll_text = input_fn(f"Poll interval seconds [{current_poll}]: ").strip()
        poll_interval_seconds = int(poll_text) if poll_text else current_poll

        feedback_text = input_fn(
            f"Feedback context limit [{current_feedback_limit}]: "
        ).strip()
        feedback_context_limit = (
            int(feedback_text) if feedback_text else current_feedback_limit
        )

        notify_chat_text = input_fn(
            f"Notification chat id for outgoing messages [{default_notify_chat or 'blank=skip'}]: "
        ).strip()
        notification_chat_id = (
            int(notify_chat_text)
            if notify_chat_text
            else (int(default_notify_chat) if default_notify_chat else None)
        )
    else:
        allowed_chat_ids = (
            [int(item) for item in current_chat_ids]
            if isinstance(current_chat_ids, list)
            else []
        )
        poll_interval_seconds = current_poll
        feedback_context_limit = current_feedback_limit
        notification_chat_id = int(default_notify_chat) if default_notify_chat else None

    return configure_telegram_bot(
        bot_token=token,
        allowed_chat_ids=allowed_chat_ids,
        poll_interval_seconds=poll_interval_seconds,
        feedback_context_limit=feedback_context_limit,
        notification_chat_id=notification_chat_id,
        config_path=config_path,
    )


def _default_state() -> dict[str, object]:
    return {"notifications_enabled": True, "last_update_id": 0}


def load_telegram_state() -> dict[str, object]:
    if not TELEGRAM_STATE_FILE.exists():
        return _default_state()
    payload = read_json(TELEGRAM_STATE_FILE)
    state = _default_state()
    state.update(payload)
    return state


def save_telegram_state(state: dict[str, object]) -> None:
    write_json(TELEGRAM_STATE_FILE, state)


def telegram_notifications_enabled() -> bool:
    return bool(load_telegram_state().get("notifications_enabled", True))


def _sanitize_filename(name: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_" for char in name
    )


def load_feedback_context(limit: int | None = None) -> str:
    if not TELEGRAM_INBOX_FILE.exists():
        return ""
    lines = TELEGRAM_INBOX_FILE.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    useful = [item for item in records if item.get("kind") in {"text", "document"}]
    if limit is not None:
        useful = useful[-limit:]
    snippets = []
    for item in useful:
        if item["kind"] == "text":
            snippets.append(
                f"- {item['ts']} chat={item['chat_id']} text={str(item.get('text', '')).strip()}"
            )
        else:
            snippets.append(
                f"- {item['ts']} chat={item['chat_id']} file={item.get('stored_path', '-')}"
            )
    return "\n".join(snippets)


class TelegramBotClient:
    def __init__(self, settings: TelegramSettings) -> None:
        self.settings = settings
        self.state = load_telegram_state()

    def _api_url(self, method: str, *, file_api: bool = False) -> str:
        assert self.settings.bot_token
        base = "https://api.telegram.org"
        if file_api:
            return f"{base}/file/bot{self.settings.bot_token}/{method}"
        return f"{base}/bot{self.settings.bot_token}/{method}"

    def _post(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._api_url(method),
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(self, method: str, query: dict[str, object]) -> dict[str, object]:
        encoded = urllib.parse.urlencode(query)
        with urllib.request.urlopen(
            f"{self._api_url(method)}?{encoded}",
            timeout=30,
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_updates(self) -> list[dict[str, object]]:
        payload = self._get(
            "getUpdates",
            {
                "timeout": 0,
                "offset": int(self.state.get("last_update_id", 0)) + 1,
            },
        )
        result = payload.get("result", [])
        return result if isinstance(result, list) else []

    def send_message(self, chat_id: int, text: str) -> None:
        self._post("sendMessage", {"chat_id": chat_id, "text": text})

    def get_file_path(self, file_id: str) -> str:
        payload = self._get("getFile", {"file_id": file_id})
        result = payload.get("result", {})
        if not isinstance(result, dict) or not isinstance(result.get("file_path"), str):
            raise RuntimeError("telegram getFile returned no file_path")
        return result["file_path"]

    def download_file(self, file_path: str) -> bytes:
        with urllib.request.urlopen(
            self._api_url(file_path, file_api=True), timeout=60
        ) as response:
            return response.read()

    def _record_inbox(self, payload: dict[str, object]) -> None:
        append_jsonl(TELEGRAM_INBOX_FILE, payload)

    def _chat_allowed(self, chat_id: int) -> bool:
        return (
            not self.settings.allowed_chat_ids
            or chat_id in self.settings.allowed_chat_ids
        )

    def _handle_command(self, chat_id: int, text: str) -> None:
        lowered = text.strip().lower()
        if lowered == "/on":
            self.state["notifications_enabled"] = True
            save_telegram_state(self.state)
            self.send_message(chat_id, "mylab notifications enabled.")
            self._record_inbox(
                {"ts": utc_now(), "kind": "command", "chat_id": chat_id, "text": "/on"}
            )
            return
        if lowered == "/off":
            self.state["notifications_enabled"] = False
            save_telegram_state(self.state)
            self.send_message(chat_id, "mylab notifications paused.")
            self._record_inbox(
                {"ts": utc_now(), "kind": "command", "chat_id": chat_id, "text": "/off"}
            )
            return
        self.send_message(chat_id, "Supported commands: /on, /off")

    def _handle_text(self, chat_id: int, text: str, message_id: int) -> None:
        self._record_inbox(
            {
                "ts": utc_now(),
                "kind": "text",
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
            }
        )
        self.send_message(chat_id, "Feedback saved for the next iteration.")

    def _handle_document(
        self, chat_id: int, document: dict[str, object], message_id: int
    ) -> None:
        file_id = document.get("file_id")
        file_name = document.get("file_name") or f"telegram-{message_id}.bin"
        if not isinstance(file_id, str):
            self.send_message(chat_id, "Document missing file_id; skipped.")
            return
        file_path = self.get_file_path(file_id)
        content = self.download_file(file_path)
        ensure_dir(TELEGRAM_FILE_DIR)
        stored_path = (
            TELEGRAM_FILE_DIR / f"{message_id}-{_sanitize_filename(str(file_name))}"
        )
        stored_path.write_bytes(content)
        self._record_inbox(
            {
                "ts": utc_now(),
                "kind": "document",
                "chat_id": chat_id,
                "message_id": message_id,
                "telegram_file_path": file_path,
                "stored_path": str(stored_path),
                "file_name": str(file_name),
            }
        )
        self.send_message(chat_id, f"File saved: {stored_path.name}")

    def process_update(self, update: dict[str, object]) -> None:
        update_id = int(update.get("update_id", 0))
        message = update.get("message", {})
        if not isinstance(message, dict):
            self.state["last_update_id"] = max(
                update_id, int(self.state.get("last_update_id", 0))
            )
            save_telegram_state(self.state)
            return
        chat = message.get("chat", {})
        if not isinstance(chat, dict):
            return
        chat_id = int(chat.get("id", 0))
        if not self._chat_allowed(chat_id):
            logger.info("Ignoring telegram update from unauthorized chat {}", chat_id)
            self.state["last_update_id"] = max(
                update_id, int(self.state.get("last_update_id", 0))
            )
            save_telegram_state(self.state)
            return
        text = message.get("text")
        message_id = int(message.get("message_id", 0))
        if isinstance(text, str) and text.strip().startswith("/"):
            self._handle_command(chat_id, text)
        elif isinstance(text, str) and text.strip():
            self._handle_text(chat_id, text, message_id)
        else:
            document = message.get("document")
            if isinstance(document, dict):
                self._handle_document(chat_id, document, message_id)
        self.state["last_update_id"] = max(
            update_id, int(self.state.get("last_update_id", 0))
        )
        save_telegram_state(self.state)

    def poll_once(self) -> int:
        if not self.settings.enabled:
            raise RuntimeError("telegram bot is not configured in ~/.mylab/config.toml")
        updates = self.get_updates()
        for update in updates:
            self.process_update(update)
        return len(updates)

    def run_forever(self) -> None:
        if not self.settings.enabled:
            raise RuntimeError("telegram bot is not configured in ~/.mylab/config.toml")
        logger.info("Starting telegram bot polling loop")
        while True:
            count = self.poll_once()
            logger.info("Telegram polling cycle processed {} update(s)", count)
            time.sleep(max(self.settings.poll_interval_seconds, 1))


def write_sample_config(path: Path = CONFIG_FILE) -> Path:
    if path.exists():
        return path
    content = "\n".join(
        [
            "[telegram]",
            'bot_token = "123456:replace-me"',
            "allowed_chat_ids = [123456789]",
            "poll_interval_seconds = 5",
            "feedback_context_limit = 5",
            "",
            "[runner]",
            'mode = "limit"',
            "limit = 100",
            "",
            "[notifications]",
            'urls = ["tgram://<bot_token>/<chat_id>"]',
            '# config_path = "/path/to/apprise.yaml"',
            '# tag = "mylab"',
        ]
    )
    write_text(path, content)
    return path
