from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Protocol


class LoggerLike(Protocol):
    def debug(self, message: str, *args: object) -> None: ...
    def info(self, message: str, *args: object) -> None: ...
    def exception(self, message: str, *args: object) -> None: ...


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
COLORS = {
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "magenta": "\033[35m",
    "gray": "\033[90m",
}


def _brace_format(message: str, args: tuple[object, ...]) -> str:
    if not args:
        return message
    try:
        return message.format(*args)
    except Exception:
        return f"{message} {' '.join(str(arg) for arg in args)}"


class StdLoggerAdapter:
    def __init__(self) -> None:
        self._logger = logging.getLogger("mylab")

    def debug(self, message: str, *args: object) -> None:
        self._logger.debug(_brace_format(message, args))

    def info(self, message: str, *args: object) -> None:
        self._logger.info(_brace_format(message, args))

    def exception(self, message: str, *args: object) -> None:
        self._logger.exception(_brace_format(message, args))


def _supports_color() -> bool:
    return sys.stderr.isatty()


def colorize(text: str, color: str, *, bold: bool = False, dim: bool = False) -> str:
    if not _supports_color():
        return text
    prefix = ""
    if bold:
        prefix += BOLD
    if dim:
        prefix += DIM
    prefix += COLORS.get(color, "")
    return f"{prefix}{text}{RESET}"


def emit_progress(
    kind: str, title: str, details: str = "", *, color: str = "blue"
) -> None:
    prefix = colorize(kind, color, bold=True)
    message = f"{prefix} {title}"
    if details:
        message += f" {colorize(details, 'gray')}"
    print(message, file=sys.stderr, flush=True)


try:
    from loguru import logger as _loguru_logger
except ModuleNotFoundError:
    _LOGURU_AVAILABLE = False
    logger: LoggerLike = StdLoggerAdapter()
else:
    _LOGURU_AVAILABLE = True
    logger = _loguru_logger


def configure_logging(log_dir: Path | None = None) -> None:
    if _LOGURU_AVAILABLE:
        _loguru_logger.remove()
        _loguru_logger.add(
            sys.stderr,
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        )
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            _loguru_logger.add(
                log_dir / "mylab.log",
                level="DEBUG",
                rotation="10 MB",
                retention=10,
                encoding="utf-8",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
            )
        return

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "mylab.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


__all__ = ["configure_logging", "logger"]
