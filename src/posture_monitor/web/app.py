"""Nhà máy tạo ứng dụng Flask (:func:`create_app`) và máy chủ phát triển (:func:`run_server`).

Thay vì nhồi 24 route vào một hàm dài gần 1.000 dòng, module này chỉ khởi tạo
:class:`WebContext`, gắn các nhóm route từ :mod:`posture_monitor.web.routes`,
và re-export các hằng số/lớp công khai để giữ nguyên hợp đồng với bên ngoài.
"""

from __future__ import annotations

from typing import Any, Callable

from flask import Flask, request

from ..camera.audio import SpeakController
from ..core.logging_setup import get_log_buffer, get_logger
from .constants import (
    FRAME_MISSING_MESSAGE,
    FRAME_WAIT_S,
    LABEL_ORDER,
    LABEL_TEXT,
    LOGS_DEFAULT_LIMIT,
    LOGS_MAX_LIMIT,
    PEOPLE_DISABLED_MESSAGE,
    PTZ_DEFAULT_DURATION_S,
    PTZ_DIRECTION_TEXT,
    PTZ_DIRECTIONS,
    PUBLIC_PERSON_FIELDS,
    SPEAKER_DISABLED_MESSAGE,
    STALE_AFTER_S,
    STATE_TEXT,
    STREAM_DISABLED_MESSAGE,
    STREAM_POLL_S,
    STREAM_STALE_WARN_S,
    STREAM_WAIT_S,
    VIOLATION_KIND_TEXT,
    VIOLATION_KINDS,
    VIOLATIONS_DEFAULT_LIMIT,
    VIOLATIONS_MAX_LIMIT,
)
from .context import WebContext, json_error
from .people_service import PeopleService
from .privacy import public_person as _public_person
from .privacy import scrub_biometrics as _scrub_biometrics
from .routes import register_all_routes
from .state import DashboardState
from .streaming import _placeholder_jpeg
from .streaming import mjpeg_stream as _mjpeg

_logger = get_logger("posture_monitor.web.app")


def create_app(
    config: Any = None,
    state: DashboardState | None = None,
    storage: Any = None,
    speak_controller: SpeakController | None = None,
    ptz: Any = None,
    *,
    people: PeopleService | None = None,
    speaker: Any = None,
    study_session: Any = None,
    log_buffer_getter: Callable[[], Any] | None = None,
) -> Flask:
    """Dựng ứng dụng Flask của dashboard và gắn đầy đủ các nhóm route."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.json.sort_keys = False

    dashboard = state or DashboardState()
    web_cfg = getattr(config, "web", None)
    sensors_cfg = getattr(config, "sensors", None)
    stream_enabled = bool(getattr(web_cfg, "stream_enabled", False))
    min_distance = float(getattr(sensors_cfg, "min_distance_cm", 35.0))
    logs_provider = (
        log_buffer_getter if log_buffer_getter is not None else get_log_buffer
    )

    app.config["DASHBOARD_STATE"] = dashboard
    app.config["STORAGE"] = storage
    app.config["STREAM_ENABLED"] = stream_enabled
    app.config["MIN_DISTANCE_CM"] = min_distance
    app.config["SPEAK_CONTROLLER"] = speak_controller
    app.config["PEOPLE"] = people
    app.config["SPEAKER"] = speaker
    app.config["STUDY_SESSION"] = study_session
    app.config["PTZ_CONTROLLER"] = ptz

    ctx = WebContext(
        app=app,
        config=config,
        dashboard=dashboard,
        storage=storage,
        stream_enabled=stream_enabled,
        min_distance=min_distance,
        people=people,
        speaker=speaker,
        study_session=study_session,
        logs_buffer_provider=logs_provider,
        _speak_controller=speak_controller,
    )
    register_all_routes(app, ctx)

    @app.errorhandler(404)
    def not_found(error):  # pragma: no cover
        if request.path.startswith("/api/"):
            return json_error("Không có API này.", 404)
        return error

    return app


def run_server(app: Flask, config: Any = None, **kwargs: Any) -> None:
    """Chạy server phát triển theo ``config.web.host`` / ``config.web.port``."""
    web_cfg = getattr(config, "web", None)
    host = str(getattr(web_cfg, "host", "0.0.0.0"))
    port = int(getattr(web_cfg, "port", 8000))
    _logger.info(
        "Dashboard chạy tại http://%s:%d/ (chỉ trong LAN, không mở ra Internet)",
        "127.0.0.1" if host == "0.0.0.0" else host,
        port,
    )
    app.run(host=host, port=port, **kwargs)


__all__ = [
    "DashboardState",
    "FRAME_MISSING_MESSAGE",
    "FRAME_WAIT_S",
    "LABEL_ORDER",
    "LABEL_TEXT",
    "LOGS_DEFAULT_LIMIT",
    "LOGS_MAX_LIMIT",
    "PEOPLE_DISABLED_MESSAGE",
    "PTZ_DEFAULT_DURATION_S",
    "PTZ_DIRECTIONS",
    "PTZ_DIRECTION_TEXT",
    "PUBLIC_PERSON_FIELDS",
    "SPEAKER_DISABLED_MESSAGE",
    "STALE_AFTER_S",
    "STATE_TEXT",
    "STREAM_DISABLED_MESSAGE",
    "STREAM_POLL_S",
    "STREAM_STALE_WARN_S",
    "STREAM_WAIT_S",
    "VIOLATIONS_DEFAULT_LIMIT",
    "VIOLATIONS_MAX_LIMIT",
    "VIOLATION_KINDS",
    "VIOLATION_KIND_TEXT",
    "_mjpeg",
    "_placeholder_jpeg",
    "_public_person",
    "_scrub_biometrics",
    "create_app",
    "run_server",
]
