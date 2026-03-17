from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any

from mylab.config import CONFIG_FILE
from mylab.logging import logger
from mylab.storage import append_jsonl
from mylab.storage.runs import load_manifest
from mylab.services.telegram_bot import telegram_notifications_enabled
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
        self.log_path = run_dir / "logs" / "notifications.jsonl"
        self._app: Any | None = None
        self._notify_type_map: dict[str, Any] | None = None
        self._ready = False
        self._disabled_reason: str | None = None

    def enabled(self) -> bool:
        return self.settings.enabled

    def _record(self, event: str, **payload: object) -> None:
        append_jsonl(
            self.log_path,
            {"ts": utc_now(), "event": event, **payload},
        )

    def _ensure_ready(self) -> bool:
        if not self.settings.enabled:
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
            self._disabled_reason = "apprise is not installed"
            logger.info("Notifications requested but apprise is not installed")
            self._record("notifier_unavailable", reason=self._disabled_reason)
            return False

        app = apprise.Apprise()
        for url in self.settings.urls:
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
        )
        return True

    def notify(self, title: str, body: str, *, notify_type: str = "info") -> bool:
        if not self._ensure_ready():
            return False
        payload: dict[str, object] = {"body": body, "title": title}
        if self.settings.tag:
            payload["tag"] = self.settings.tag
        if self._notify_type_map:
            notify_value = self._notify_type_map.get(notify_type)
            if notify_value is not None:
                payload["notify_type"] = notify_value
        try:
            assert self._app is not None
            ok = bool(self._app.notify(**payload))
        except Exception as exc:
            logger.info("Notification send failed: {}", exc)
            self._record(
                "notify_failed",
                title=title,
                notify_type=notify_type,
                error=str(exc),
            )
            return False
        self._record(
            "notify_sent",
            title=title,
            notify_type=notify_type,
            ok=ok,
        )
        return ok
