"""Nhóm route nền tảng: trang chủ HTML, trạng thái, lịch sử biểu đồ, hiệu chỉnh và tắt tiếng."""

from __future__ import annotations

from typing import Mapping

from flask import Flask, Response, jsonify, render_template, request

from ...core.logging_setup import get_logger
from ...domain.study_session import (
    DEFAULT_MINUTES as SESSION_DEFAULT_MINUTES,
    MAX_MINUTES as SESSION_MAX_MINUTES,
    MIN_MINUTES as SESSION_MIN_MINUTES,
)
from ..constants import PEOPLE_DISABLED_MESSAGE
from ..context import WebContext, json_error, static_version

_logger = get_logger("posture_monitor.web.routes.core")


def register_core_routes(app: Flask, ctx: WebContext) -> None:
    """Đăng ký ``/``, ``/api/status``, ``/api/history``, ``/api/calibrate``, ``/api/mute``."""

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            stream_enabled=ctx.stream_enabled,
            min_distance_cm=ctx.min_distance,
            people_enabled=ctx.people is not None,
            people_disabled_message=PEOPLE_DISABLED_MESSAGE,
            speaker_enabled=ctx.speaker is not None,
            session_enabled=ctx.study_session is not None,
            session_default_minutes=(
                int(ctx.study_session.default_minutes)
                if ctx.study_session is not None
                else SESSION_DEFAULT_MINUTES
            ),
            session_min_minutes=SESSION_MIN_MINUTES,
            session_max_minutes=SESSION_MAX_MINUTES,
            asset_version=static_version(),
        )

    @app.get("/api/status")
    def api_status() -> Response:
        payload = ctx.dashboard.snapshot()
        payload["stream_enabled"] = ctx.stream_enabled
        payload["min_distance_cm"] = ctx.min_distance
        return jsonify(payload)

    @app.get("/api/history")
    def api_history() -> Response:
        range_key = request.args.get("range", "today")
        if range_key not in ("today", "7d"):
            return json_error("Tham số 'range' phải là 'today' hoặc '7d'.", 400)
        if ctx.storage is None:
            return jsonify(
                {
                    "range": range_key,
                    "unit": "hour" if range_key == "today" else "day",
                    "labels": [],
                    "good_pct": [],
                    "avg_score": [],
                    "absent_s": [],
                    "distance_cm_avg": [],
                    "has_data": False,
                    "message": "Chưa bật lưu trữ nên chưa có số liệu.",
                }
            )
        try:
            return jsonify(ctx.storage.history(range_key))
        except Exception as exc:  # noqa: BLE001
            _logger.error("Không lấy được lịch sử cho dashboard: %s", exc)
            return json_error("Không đọc được số liệu đã lưu.", 503)

    @app.post("/api/calibrate")
    def api_calibrate() -> Response:
        ctx.dashboard.request_calibration()
        return jsonify(
            {
                "ok": True,
                "message": "Đã gửi yêu cầu hiệu chỉnh. Hãy ngồi thẳng trong 5 giây tới.",
                "calibration_pending": True,
            }
        )

    @app.post("/api/mute")
    def api_mute() -> Response:
        body = request.get_json(silent=True) or {}
        if isinstance(body, Mapping) and "muted" in body:
            muted = ctx.dashboard.set_muted(bool(body["muted"]))
        else:
            muted = ctx.dashboard.toggle_mute()
        return jsonify(
            {
                "ok": True,
                "muted": muted,
                "message": (
                    "Đã tắt tiếng cảnh báo."
                    if muted
                    else "Đã bật lại tiếng cảnh báo."
                ),
            }
        )
