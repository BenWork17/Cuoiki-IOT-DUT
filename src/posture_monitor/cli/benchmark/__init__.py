"""Gói con ``cli.benchmark`` — chia nhỏ module benchmark 1.855 dòng thành 4 tầng rõ ràng."""

from __future__ import annotations

try:
    import psutil
except Exception:  # noqa: BLE001
    psutil = None  # type: ignore[assignment]

from ...camera.capture import capture_from_config
from ...vision.pose import PoseEstimator
from .profiles import (
    DEFAULT_PROFILE,
    FACE_MISSING_MESSAGE,
    PHONE_MISSING_MESSAGE,
    PROFILES,
    _build_face_extra,
    _build_phone_extra,
    _ExtraModel,
    build_extras as _build_extras,
    normalise_profile,
)
from .report import REPORT_VERSION, build_parser, format_report
from .runner import main, run_benchmark
from .sources import (
    IMAGE_SUFFIXES,
    SOURCE_KINDS,
    FrameListSource,
    StaticImageSource,
    _source_meta,
)
from .telemetry import (
    BYTES_PER_MIB,
    MAX_FRAME_ERRORS,
    MAX_RAM_MB,
    MAX_TEMP_C,
    MEMORY_EVERY_FRAMES,
    MIN_FPS,
    SAMPLE_INTERVAL_S,
    THROTTLE_ACTIVE,
    THROTTLE_ACTIVE_OCCURRED,
    THROTTLE_BITS,
    WARMUP_FRAMES,
    BenchmarkError,
    _Command,
    compute_stats as _stats,
    describe_throttle as _describe_throttle,
    parse_temp as _parse_temp,
    parse_throttled as _parse_throttled,
)

__all__ = [
    "BYTES_PER_MIB",
    "BenchmarkError",
    "DEFAULT_PROFILE",
    "FACE_MISSING_MESSAGE",
    "FrameListSource",
    "IMAGE_SUFFIXES",
    "MAX_FRAME_ERRORS",
    "MAX_RAM_MB",
    "MAX_TEMP_C",
    "MEMORY_EVERY_FRAMES",
    "MIN_FPS",
    "PHONE_MISSING_MESSAGE",
    "PROFILES",
    "PoseEstimator",
    "REPORT_VERSION",
    "SAMPLE_INTERVAL_S",
    "SOURCE_KINDS",
    "StaticImageSource",
    "THROTTLE_ACTIVE",
    "THROTTLE_ACTIVE_OCCURRED",
    "THROTTLE_BITS",
    "WARMUP_FRAMES",
    "_Command",
    "_ExtraModel",
    "_build_extras",
    "_build_face_extra",
    "_build_phone_extra",
    "_describe_throttle",
    "_parse_temp",
    "_parse_throttled",
    "_source_meta",
    "_stats",
    "build_parser",
    "capture_from_config",
    "format_report",
    "main",
    "normalise_profile",
    "psutil",
    "run_benchmark",
]
