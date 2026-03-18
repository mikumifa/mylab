from __future__ import annotations

import json
import urllib.error
import urllib.request
from getpass import getpass
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mylab.config import CONFIG_FILE
from mylab.services.telegram_bot import (
    _read_config,
    _split_notify_values,
    write_user_config,
)

FEISHU_WEBHOOK_PREFIXES = (
    "https://open.feishu.cn/open-apis/bot/v2/hook/",
    "https://open.larksuite.com/open-apis/bot/v2/hook/",
    "lark://",
    "feishu://",
)


def _is_feishu_notify_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().startswith(FEISHU_WEBHOOK_PREFIXES)


def is_feishu_notify_url(value: object) -> bool:
    return _is_feishu_notify_url(value)


def _default_webhook_url(
    section: dict[str, object], notifications: dict[str, object]
) -> str:
    webhook_url = section.get("webhook_url")
    if isinstance(webhook_url, str) and webhook_url.strip():
        return webhook_url.strip()
    raw_urls = notifications.get("urls", [])
    if isinstance(raw_urls, list):
        values = [str(item).strip() for item in raw_urls if str(item).strip()]
    elif isinstance(raw_urls, str):
        values = _split_notify_values(raw_urls)
    else:
        values = []
    for value in values:
        if _is_feishu_notify_url(value):
            return value
    return ""


@dataclass
class FeishuSettings:
    webhook_url: str | None
    default_check_command: str | None = None
    bidirectional_control_enabled: bool = False
    app_id: str | None = None
    app_secret: str | None = None
    chat_id: str | None = None

    @property
    def notification_enabled(self) -> bool:
        return bool(self.webhook_url)

    @property
    def bidirectional_enabled(self) -> bool:
        return bool(
            self.bidirectional_control_enabled
            and self.app_id
            and self.app_secret
            and self.chat_id
        )

    @property
    def enabled(self) -> bool:
        return self.notification_enabled or self.bidirectional_enabled


def _clean_optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _prompt_yes_no(prompt: str, *, current_value: bool, input_fn: Any) -> bool:
    suffix = "Y/n" if current_value else "y/N"
    while True:
        value = input_fn(f"{prompt} [{suffix}]: ").strip().lower()
        if not value:
            return current_value
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def load_feishu_settings(config_path: Path | None = None) -> FeishuSettings:
    payload = _read_config(config_path)
    section = payload.get("feishu", {})
    if not isinstance(section, dict):
        section = {}
    notifications = payload.get("notifications", {})
    if not isinstance(notifications, dict):
        notifications = {}
    webhook_url = _default_webhook_url(section, notifications)
    return FeishuSettings(
        webhook_url=webhook_url or None,
        default_check_command=_clean_optional_text(
            section.get("default_check_command")
        ),
        bidirectional_control_enabled=_parse_bool(
            section.get("bidirectional_control_enabled"),
            default=False,
        ),
        app_id=_clean_optional_text(section.get("app_id")),
        app_secret=_clean_optional_text(section.get("app_secret")),
        chat_id=_clean_optional_text(section.get("chat_id")),
    )


def configure_feishu_bot(
    *,
    webhook_url: str | None,
    default_check_command: str | None = None,
    bidirectional_control_enabled: bool = False,
    app_id: str | None = None,
    app_secret: str | None = None,
    chat_id: str | None = None,
    config_path: Path | None = CONFIG_FILE,
) -> Path:
    target = config_path or CONFIG_FILE
    payload = _read_config(target)

    feishu_section = payload.get("feishu", {})
    if not isinstance(feishu_section, dict):
        feishu_section = {}
    feishu_section["webhook_url"] = webhook_url.strip() if webhook_url else None
    feishu_section["default_check_command"] = (
        default_check_command.strip() if default_check_command else None
    )
    feishu_section["bidirectional_control_enabled"] = bidirectional_control_enabled
    feishu_section["app_id"] = app_id.strip() if app_id else None
    feishu_section["app_secret"] = app_secret.strip() if app_secret else None
    feishu_section["chat_id"] = chat_id.strip() if chat_id else None
    payload["feishu"] = feishu_section

    notifications = payload.get("notifications", {})
    if not isinstance(notifications, dict):
        notifications = {}
    raw_urls = notifications.get("urls", [])
    existing_urls: list[str] = []
    if isinstance(raw_urls, list):
        existing_urls = [str(item).strip() for item in raw_urls if str(item).strip()]
    elif isinstance(raw_urls, str):
        existing_urls = _split_notify_values(raw_urls)
    preserved_urls = [item for item in existing_urls if not _is_feishu_notify_url(item)]
    if webhook_url and webhook_url.strip():
        preserved_urls.insert(0, webhook_url.strip())
    notifications["urls"] = preserved_urls
    payload["notifications"] = notifications
    return write_user_config(payload, target)


def interactive_feishu_setup(
    *,
    config_path: Path | None = CONFIG_FILE,
    input_fn: Any = input,
    secret_input_fn: Any = getpass,
) -> Path:
    target = config_path or CONFIG_FILE
    settings = load_feishu_settings(target)

    print(f"Config file: {target}")
    default_check_command = input_fn("Default check command (optional): ").strip() or (
        settings.default_check_command or ""
    )
    bidirectional_control_enabled = _prompt_yes_no(
        "Enable Feishu bidirectional control?",
        current_value=settings.bidirectional_control_enabled,
        input_fn=input_fn,
    )
    app_id = settings.app_id
    app_secret = settings.app_secret
    chat_id = settings.chat_id
    if bidirectional_control_enabled:
        app_id = (
            input_fn(f"Feishu app id [{settings.app_id or 'required'}]: ").strip()
            or settings.app_id
        )
        if not app_id:
            raise ValueError(
                "feishu app id is required when bidirectional control is enabled"
            )
        app_secret = (
            secret_input_fn(
                f"Feishu app secret [{'*' * 8 if settings.app_secret else 'required'}]: "
            ).strip()
            or settings.app_secret
        )
        if not app_secret:
            raise ValueError(
                "feishu app secret is required when bidirectional control is enabled"
            )
        chat_id = (
            input_fn(f"Feishu chat id [{settings.chat_id or 'required'}]: ").strip()
            or settings.chat_id
        )
        if not chat_id:
            raise ValueError(
                "feishu chat id is required when bidirectional control is enabled"
            )
    webhook_url = settings.webhook_url
    if not webhook_url:
        webhook_url = (
            input_fn(
                "Feishu webhook url for outgoing notifications (optional): "
            ).strip()
            or None
        )
    return configure_feishu_bot(
        webhook_url=webhook_url,
        default_check_command=default_check_command or None,
        bidirectional_control_enabled=bidirectional_control_enabled,
        app_id=app_id,
        app_secret=app_secret,
        chat_id=chat_id,
        config_path=target,
    )


def _post_json(
    url: str, payload: dict[str, object], headers: dict[str, str]
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _trim_feishu_markdown(text: str, *, limit: int = 1500) -> str:
    return text.strip()[:limit]


def build_feishu_post_content(
    title: str,
    message: str,
    *,
    locale: str = "zh_cn",
) -> dict[str, object]:
    body = _trim_feishu_markdown(message)
    rows: list[list[dict[str, str]]] = []
    if body:
        rows.append([{"tag": "md", "text": body}])
    else:
        rows.append([{"tag": "text", "text": "-"}])
    return {
        locale: {
            "title": title.strip()[:100] or "mylab",
            "content": rows,
        }
    }


def _webhook_send(webhook_url: str, title: str, message: str) -> bool:
    payload = {
        "msg_type": "post",
        "content": {
            "post": build_feishu_post_content(title, message),
        },
    }
    response = _post_json(
        webhook_url,
        payload,  # type: ignore
        {"Content-Type": "application/json; charset=utf-8"},
    )
    return response.get("code") in {0, "0", None}


def _tenant_access_token(settings: FeishuSettings) -> str:
    if not settings.app_id or not settings.app_secret:
        raise ValueError("feishu app_id/app_secret are required")
    response = _post_json(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": settings.app_id, "app_secret": settings.app_secret},
        {"Content-Type": "application/json; charset=utf-8"},
    )
    token = response.get("tenant_access_token")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("feishu auth returned no tenant_access_token")
    return token.strip()


def _api_send(settings: FeishuSettings, title: str, message: str) -> bool:
    if not settings.chat_id:
        raise ValueError("feishu chat_id is required")
    token = _tenant_access_token(settings)
    response = _post_json(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        {
            "receive_id": settings.chat_id,
            "msg_type": "post",
            "content": json.dumps(
                build_feishu_post_content(title, message),
                ensure_ascii=False,
            ),
        },
        {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    return response.get("code") in {0, "0", None}


def send_feishu_test_message(
    settings: FeishuSettings,
    *,
    message: str = "This is a test notification from mylab bot test.",
) -> bool:
    return send_feishu_message(
        settings,
        title="mylab bot test",
        message=message,
    )


def send_feishu_message(
    settings: FeishuSettings,
    *,
    title: str = "mylab",
    message: str,
) -> bool:
    sent = False
    if settings.webhook_url:
        sent = _webhook_send(settings.webhook_url, title, message) or sent
    if settings.bidirectional_enabled:
        sent = _api_send(settings, title, message) or sent
    return sent
