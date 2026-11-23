"""Gói giao diện dòng lệnh ``cli`` cho ``posture_monitor``."""

from __future__ import annotations

import time

import cv2

from ..camera.capture import capture_from_config
from ..core.config import ConfigError, load_config, redact_camera_source
from ..core.logging_setup import setup_logging
from .cmd_calibrate import cmd_calibrate
from .cmd_replay import cmd_replay
from .cmd_run import _print_status, _save_one_overlay, cmd_benchmark, cmd_run
from .cmd_speak_test import (
    _print_speak_test_header,
    _print_speak_test_list,
    cmd_speak_test,
)
from .dashboard_host import (
    _build_face_processor,
    _create_people_service,
    _create_speaker,
    _create_study_session,
    _Dashboard,
    _serve_web,
)
from .main import main
from .monitor_runner import (
    MonitorRunner,
    _loc_nhan_tu_the,
    _monitor_loop,
    _presence_state,
    _warn_phone_threshold_mismatch,
)
from .parser import (
    QUIT_KEYS,
    SAVE_OVERLAY_MAX_FRAMES,
    SPEAK_TEST_GAP_S,
    SPEAK_TEST_KINDS,
    WINDOW_NAME,
    build_parser,
)

__all__ = [
    "ConfigError",
    "MonitorRunner",
    "QUIT_KEYS",
    "SAVE_OVERLAY_MAX_FRAMES",
    "SPEAK_TEST_GAP_S",
    "SPEAK_TEST_KINDS",
    "WINDOW_NAME",
    "_Dashboard",
    "_build_face_processor",
    "_create_people_service",
    "_create_speaker",
    "_create_study_session",
    "_loc_nhan_tu_the",
    "_monitor_loop",
    "_presence_state",
    "_print_speak_test_header",
    "_print_speak_test_list",
    "_print_status",
    "_save_one_overlay",
    "_serve_web",
    "_warn_phone_threshold_mismatch",
    "build_parser",
    "capture_from_config",
    "cmd_benchmark",
    "cmd_calibrate",
    "cmd_replay",
    "cmd_run",
    "cmd_speak_test",
    "cv2",
    "load_config",
    "main",
    "redact_camera_source",
    "setup_logging",
    "time",
]
