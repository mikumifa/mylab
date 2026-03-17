from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any

from mylab.config import CONFIG_FILE
from mylab.logging import logger
from mylab.services.feishu_bot import (
    is_feishu_notify_url,
    load_feishu_settings,
    send_feishu_message,
)
from mylab.services.telegram_bot import (
    is_telegram_notify_url,
    load_telegram_settings,
    send_telegram_notification,
    telegram_notifications_enabled,
)
from mylab.storage import append_jsonl
from mylab.storage.runs import load_manifest
from mylab.utils import utc_now


def _split_notify_values(values: str) -> list[str]:
    parts = []
    for chunk in values.replace("\n", ",").split(","):
        value = chunk.strip()
        if value:
            parts.append(value)
    return parts


@dataclass
class NotificationSettings:
    urls: list[str]
    config_path: str | None = None
    tag: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.urls or self.config_path)


def _read_user_config(config_path: Path | None = None) -> dict[str, object]:
    target = config_path or CONFIG_FILE
    if not target.exists():
        return {}
    with target.open("rb") as handle:
        payload = tomllib.load(handle)
    return payload if isinstance(payload, dict) else {}


def resolve_notification_settings(
    config_path: Path | None = None,
) -> NotificationSettings:
    payload = _read_user_config(config_path)
    section = payload.get("notifications", {})
    if not isinstance(section, dict):
        return NotificationSettings(urls=[])
    raw_urls = section.get("urls", [])
    urls: list[str] = []
    if isinstance(raw_urls, list):
        urls = [str(item).strip() for item in raw_urls if str(item).strip()]
    elif isinstance(raw_urls, str):
        urls = _split_notify_values(raw_urls)
    raw_config_path = section.get("config_path")
    notify_config = (
        str(raw_config_path).strip()
        if isinstance(raw_config_path, str) and raw_config_path.strip()
        else None
    )
    raw_tag = section.get("tag")
    tag = str(raw_tag).strip() if isinstance(raw_tag, str) and raw_tag.strip() else None
    feishu_settings = load_feishu_settings(config_path)
    if feishu_settings.enabled and feishu_settings.webhook_url not in urls:
        urls.insert(0, feishu_settings.webhook_url)
    urls = [value for value in urls if isinstance(value, str) and value.strip()]
    return NotificationSettings(urls=urls, config_path=notify_config, tag=tag)


def load_notification_settings(run_dir: Path) -> NotificationSettings:
    manifest = load_manifest(run_dir)
    file_settings = resolve_notification_settings()
    return NotificationSettings(
        urls=manifest.notify_urls or file_settings.urls,
        config_path=manifest.notify_config_path or file_settings.config_path,
        tag=manifest.notify_tag or file_settings.tag,
    )


class NotificationClient:
    def __init__(self, run_dir: Path, settings: NotificationSettings) -> None:
        self.run_dir = run_dir
        self.settings = settings
        self.feishu_settings = load_feishu_settings()
        self.telegram_settings = load_telegram_settings()
        self.log_path = run_dir / "logs" / "notifications.jsonl"
        self._app: Any | None = None
        self._notify_type_map: dict[str, Any] | None = None
        self._ready = False
        self._disabled_reason: str | None = None

    def enabled(self) -> bool:
        return (
            self.settings.enabled
            or self.feishu_settings.enabled
            or self.telegram_settings.enabled
        )

    def _record(self, event: str, **payload: object) -> None:
        append_jsonl(
            self.log_path,
            {"ts": utc_now(), "event": event, **payload},
        )

    def _ensure_ready(self) -> bool:
        if not self.enabled():
            return False
        if not telegram_notifications_enabled():
            self._record("notifier_paused", reason="paused_by_telegram_command")
            return False
        if self._ready:
            return True
        if self._disabled_reason:
            return False
        try:
            import apprise
        except ModuleNotFoundError:
            if self.feishu_settings.enabled:
                self._ready = True
                self._record(
                    "notifier_ready",
                    urls=self.settings.urls,
                    config_path=self.settings.config_path,
                    tag=self.settings.tag,
                    feishu_enabled=True,
                )
                return True
            self._disabled_reason = "apprise is not installed"
            logger.info("Notifications requested but apprise is not installed")
            self._record("notifier_unavailable", reason=self._disabled_reason)
            return False

        app = apprise.Apprise()
        for url in self.settings.urls:
            if not is_feishu_notify_url(url) and not is_telegram_notify_url(url):
                app.add(url)
        if self.settings.config_path:
            config = apprise.AppriseConfig()
            config.add(self.settings.config_path)
            app.add(config)
        notify_type_cls = getattr(apprise, "NotifyType", None)
        if notify_type_cls is not None:
            self._notify_type_map = {
                "info": getattr(notify_type_cls, "INFO", None),
                "success": getattr(notify_type_cls, "SUCCESS", None),
                "warning": getattr(notify_type_cls, "WARNING", None),
                "failure": getattr(notify_type_cls, "FAILURE", None),
            }
        self._app = app
        self._ready = True
        self._record(
            "notifier_ready",
            urls=self.settings.urls,
            config_path=self.settings.config_path,
            tag=self.settings.tag,
            feishu_enabled=self.feishu_settings.enabled,
        )
        return True

    def notify(self, title: str, body: str, *, notify_type: str = "info") -> bool:
        if not self._ensure_ready():
            return False
        message = f"{title}\n\n{body}".strip()
        feishu_ok = True
        if self.feishu_settings.enabled:
            try:
                feishu_ok = bool(
                    send_feishu_message(
                        self.feishu_settings,
                        message=message[:4000],
                    )
                )
            except Exception as exc:
                logger.info("Feishu notification send failed: {}", exc)
                self._record(
                    "notify_feishu_failed",
                    title=title,
                    notify_type=notify_type,
                    error=str(exc),
                )
                feishu_ok = False
        telegram_ok = True
        if self.telegram_settings.enabled:
            try:
                telegram_ok = bool(
                    send_telegram_notification(
                        self.telegram_settings,
                        self.settings.urls,
                        title=title,
                        body=body,
                        notify_type=notify_type,
                    )
                )
            except Exception as exc:
                logger.info("Telegram notification send failed: {}", exc)
                self._record(
                    "notify_telegram_failed",
                    title=title,
                    notify_type=notify_type,
                    error=str(exc),
                )
                telegram_ok = False
        payload: dict[str, object] = {"body": body, "title": title}
        if self.settings.tag:
            payload["tag"] = self.settings.tag
        if self._notify_type_map:
            notify_value = self._notify_type_map.get(notify_type)
            if notify_value is not None:
                payload["notify_type"] = notify_value
        apprise_ok = True
        try:
            if self._app is not None:
                apprise_ok = bool(self._app.notify(**payload))
        except Exception as exc:
            logger.info("Notification send failed: {}", exc)
            self._record(
                "notify_failed",
                title=title,
                notify_type=notify_type,
                error=str(exc),
            )
            apprise_ok = False
        ok = feishu_ok or telegram_ok or apprise_ok
        self._record(
            "notify_sent",
            title=title,
            notify_type=notify_type,
            ok=ok,
            feishu_ok=feishu_ok if self.feishu_settings.enabled else None,
            telegram_ok=telegram_ok if self.telegram_settings.enabled else None,
            apprise_ok=apprise_ok if self._app is not None else None,
        )
        return ok

    def notify_agent_message(self, plan_id: str, text: str) -> bool:
        message = text.strip()
        if not message:
            return False
        return self.notify(
            f"mylab agent {plan_id}",
            message[:4000],
            notify_type="info",
        )
