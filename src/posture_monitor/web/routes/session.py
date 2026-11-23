"""Nhóm route điều khiển phiên học: ``GET /api/session``, ``POST /api/session/start|stop``."""

from __future__ import annotations

from typing import Mapping

from flask import Flask, Response, jsonify, request

from ...domain.study_session import (
    MAX_MINUTES as SESSION_MAX_MINUTES,
    MIN_MINUTES as SESSION_MIN_MINUTES,
    StudySessionError,
    payload as session_payload,
)
from ..context import WebContext, json_error


def register_session_routes(app: Flask, ctx: WebContext) -> None:
    """Đăng ký các route của phiên học đếm ngược."""

    def _session_unavailable() -> Response:
        return json_error(
            "Phiên học chưa được bật trong lần chạy này nên chưa bấm được "
            "Bắt đầu/Dừng.",
            503,
        )

    @app.get("/api/session")
    def api_session_get() -> Response:
        if ctx.study_session is None:
            return _session_unavailable()
        data = session_payload(ctx.study_session.snapshot())
        data["default_minutes"] = int(ctx.study_session.default_minutes)
        data["min_minutes"] = SESSION_MIN_MINUTES
        data["max_minutes"] = SESSION_MAX_MINUTES
        return jsonify(data)

    @app.post("/api/session/start")
    def api_session_start() -> Response:
        if ctx.study_session is None:
            return _session_unavailable()
        body = request.get_json(silent=True)
        minutes = None
        if isinstance(body, Mapping) and body.get("minutes") is not None:
            minutes = body["minutes"]
        try:
            snapshot = ctx.study_session.start(minutes)
        except StudySessionError as exc:
            return json_error(str(exc), 400)
        data = session_payload(snapshot)
        data["ok"] = True
        data["message"] = (
            f"Đã bắt đầu phiên học {snapshot.minutes} phút. Hệ thống đang theo dõi."
        )
        return jsonify(data)

    @app.post("/api/session/stop")
    def api_session_stop() -> Response:
        if ctx.study_session is None:
            return _session_unavailable()
        snapshot = ctx.study_session.stop()
        data = session_payload(snapshot)
        data["ok"] = True
        data["message"] = "Đã dừng phiên học. Hệ thống tạm ngừng phân tích."
        return jsonify(data)
