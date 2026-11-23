"""Cấu hình logging dùng chung cho toàn dự án (stderr + xoay vòng file + RAM buffer)."""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .log_buffer import LogBuffer

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)-28s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
ROOT_LOGGER_NAME = "posture_monitor"

_buffer: LogBuffer | None = None
_buffer_lock = threading.Lock()


def get_log_buffer() -> LogBuffer:
    """Trả :class:`LogBuffer` dùng chung duy nhất của tiến trình (khởi tạo lười)."""
    global _buffer
    if _buffer is not None:
        return _buffer
    with _buffer_lock:
        if _buffer is None:
            _buffer = LogBuffer()
        return _buffer


def reset_log_buffer() -> None:
    """Xoá nội dung buffer dùng chung nhưng giữ nguyên instance."""
    get_log_buffer().clear()


def setup_logging(
    level: str | int = "INFO",
    log_file: str | Path | None = None,
    *,
    with_buffer: bool = True,
) -> logging.Logger:
    """Khởi tạo logger gốc ``posture_monitor`` và trả về nó."""
    if isinstance(level, int):
        numeric_level = level
    else:
        numeric_level = logging.getLevelName(str(level).upper())
        if not isinstance(numeric_level, int):
            numeric_level = logging.INFO

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(numeric_level)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    console = logging.StreamHandler(stream=sys.stderr)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_file is not None:
        target = Path(log_file)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                target, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("Không mở được file log '%s': %s", target, exc)

    if with_buffer:
        buffer_handler = get_log_buffer()
        buffer_handler.setLevel(numeric_level)
        logger.addHandler(buffer_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Lấy logger con dưới nhánh ``posture_monitor``."""
    if name == ROOT_LOGGER_NAME or name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
