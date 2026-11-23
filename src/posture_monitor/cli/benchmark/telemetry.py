"""Đo nhiệt độ SoC, cờ throttle (``vcgencmd``), thông tin phần cứng & RSS RAM."""

from __future__ import annotations

import math
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

SAMPLE_INTERVAL_S = 5.0
WARMUP_FRAMES = 5
MEMORY_EVERY_FRAMES = 10
MAX_FRAME_ERRORS = 10
BYTES_PER_MIB = 1024 * 1024

MIN_FPS = 5.0
MAX_TEMP_C = 80.0
MAX_RAM_MB = 1024.0

THROTTLE_ACTIVE = 0x4
THROTTLE_ACTIVE_OCCURRED = 0x40000

THROTTLE_BITS = (
    (0x1, "under-voltage (đang thiếu áp)"),
    (0x2, "freq capped (đang bị hạ xung)"),
    (0x4, "đang throttle (đang bị bóp hiệu năng)"),
    (0x10000, "đã từng xảy ra under-voltage"),
    (0x20000, "đã từng xảy ra freq capped"),
    (0x40000, "đã từng xảy ra throttle"),
)

_TEMP_RE = re.compile(r"temp=(-?\d+(?:\.\d+)?)")
_THROTTLE_RE = re.compile(r"throttled=(0x[0-9a-fA-F]+)")


class BenchmarkError(RuntimeError):
    """Không thể đo (không mở được nguồn, thiếu model, sai tham số môi trường)."""


class _Command:
    """Bọc một lệnh hệ thống ngoài (như ``vcgencmd``) và ghi nhớ nếu máy không có lệnh."""

    def __init__(self, *argv: str) -> None:
        self._argv = argv
        self._missing: str | None = None

    def run(self, timeout: float = 2.0) -> tuple[str | None, str | None]:
        if self._missing is not None:
            return None, self._missing
        try:
            completed = subprocess.run(
                self._argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            self._missing = (
                f"Không có lệnh '{self._argv[0]}' trên máy này "
                "(chỉ Raspberry Pi OS mới có)."
            )
            return None, self._missing
        except (OSError, subprocess.SubprocessError) as exc:
            return None, f"Không chạy được '{' '.join(self._argv)}': {exc}"

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            return None, (
                f"'{' '.join(self._argv)}' thoát với mã {completed.returncode}"
                + (f": {detail}" if detail else "")
            )
        return completed.stdout.strip(), None


def parse_temp(text: str | None) -> float | None:
    if not text:
        return None
    match = _TEMP_RE.search(text)
    if match is None:
        return None
    value = float(match.group(1))
    return value if math.isfinite(value) else None


def parse_throttled(text: str | None) -> int | None:
    if not text:
        return None
    match = _THROTTLE_RE.search(text)
    if match is None:
        return None
    try:
        return int(match.group(1), 16)
    except ValueError:  # pragma: no cover
        return None


def describe_throttle(value: int) -> dict[str, Any]:
    flags = [
        {"bit": f"0x{bit:x}", "meaning": meaning}
        for bit, meaning in THROTTLE_BITS
        if value & bit
    ]
    return {
        "raw": f"0x{value:x}",
        "flags": flags,
        "any_set": value != 0,
        "invalidates_fps": bool(value & (THROTTLE_ACTIVE | THROTTLE_ACTIVE_OCCURRED)),
    }


def compute_stats(values: Sequence[float]) -> dict[str, float] | None:
    data = [
        float(value)
        for value in values
        if value is not None and math.isfinite(float(value))
    ]
    if not data:
        return None
    array = np.asarray(data, dtype=float)
    return {
        "count": int(array.size),
        "min": float(array.min()),
        "median": float(np.median(array)),
        "p95": float(np.percentile(array, 95)),
        "max": float(array.max()),
        "mean": float(array.mean()),
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _cpu_model() -> str:
    cpuinfo = _read_text(Path("/proc/cpuinfo"))
    for line in cpuinfo.splitlines():
        if line.lower().startswith(("model name", "hardware", "model")):
            _, _, value = line.partition(":")
            value = value.strip()
            if value:
                return value
    return platform.processor() or "không rõ"


def _cpu_count() -> int | None:
    try:
        return os.cpu_count()
    except Exception:  # noqa: BLE001
        return None


def host_info() -> dict[str, Any]:
    model = _read_text(Path("/proc/device-tree/model")).strip("\x00").strip()
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu": model or _cpu_model(),
        "cpu_count": _cpu_count(),
        "is_raspberry_pi": "raspberry pi" in model.lower(),
    }


def rss_mib(psutil_mod: Any) -> float | None:
    if psutil_mod is None:
        return None
    try:
        return psutil_mod.Process().memory_info().rss / BYTES_PER_MIB
    except Exception:  # noqa: BLE001
        return None
