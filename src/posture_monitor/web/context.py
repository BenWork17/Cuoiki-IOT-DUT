"""Ngữ cảnh dùng chung và các hàm tiện ích kiểm tra tham số cho các nhóm route Flask."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from flask import Flask, Response, jsonify

from ..camera import control as camera_control
from ..camera.audio import SpeakController
from .people_service import PeopleService
from .state import DashboardState


def json_error(message: str, status: int) -> Response:
    """Trả phản hồi lỗi JSON kèm thông điệp tiếng Việt."""
    response = jsonify({"ok": False, "message": message})
    response.status_code = status
    return response


def parse_limit_arg(
    raw_limit: str | None,
    *,
    default: int,
    max_limit: int,
    unit_hint: str = "bản ghi",
) -> tuple[int | None, Response | None]:
    """Đọc và kiểm tra tham số truy vấn ``limit`` dùng chung cho ``/api/logs`` và ``/api/violations``."""
    if raw_limit is None or str(raw_limit).strip() == "":
        return default, None
    try:
        limit = int(str(raw_limit).strip())
    except (TypeError, ValueError):
        return None, json_error(
            f"Tham số 'limit' phải là số nguyên, nhận được {raw_limit!r}.", 400
        )
    if limit <= 0:
        return None, json_error(
            f"'limit' phải là số dương — cần ít nhất một {unit_hint}.", 400
        )
    if limit > max_limit:
        return None, json_error(
            f"'limit' tối đa là {max_limit}, nhận được {limit}.", 400
        )
    return limit, None


def static_version(static_dir: Path | None = None) -> str:
    """Dấu phiên bản mtime của tệp tĩnh giúp trình duyệt luôn nạp CSS/JS mới."""
    folder = static_dir or (Path(__file__).resolve().parent / "static")
    newest = 0.0
    try:
        for name in ("style.css", "app.js", "fonts.css"):
            try:
                newest = max(newest, (folder / name).stat().st_mtime)
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        return "0"
    return str(int(newest)) if newest else "0"


@dataclass
class WebContext:
    """ Đóng gói toàn bộ phụ thuộc của một instance ứng dụng Flask."""

    app: Flask
    config: Any
    dashboard: DashboardState
    storage: Any
    stream_enabled: bool
    min_distance: float
    people: PeopleService | None
    speaker: Any
    study_session: Any
    logs_buffer_provider: Callable[[], Any]
    _speak_controller: SpeakController | None = None
    _speak_lock: threading.Lock = field(default_factory=threading.Lock)
    _ptz_lock: threading.Lock = field(default_factory=threading.Lock)

    def resolve_speak_controller(self) -> SpeakController:
        """Khởi tạo lười :class:`SpeakController` từ ``config.camera.speaker``."""
        if self._speak_controller is not None:
            return self._speak_controller
        with self._speak_lock:
            if self._speak_controller is None:
                self._speak_controller = SpeakController.from_config(self.config)
            return self._speak_controller

    def resolve_ptz(self) -> Any:
        """Khởi tạo lười bộ điều khiển ONVIF PTZ một lần duy nhất."""
        controller = self.app.config.get("PTZ_CONTROLLER")
        if controller is not None:
            return controller
        with self._ptz_lock:
            controller = self.app.config.get("PTZ_CONTROLLER")
            if controller is None:
                controller = camera_control.from_config(self.config)
                self.app.config["PTZ_CONTROLLER"] = controller
        return controller
