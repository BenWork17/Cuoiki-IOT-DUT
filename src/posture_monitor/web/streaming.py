"""Luồng hình trực tiếp MJPEG (``/stream``) và khung JPEG đơn lẻ (``/api/frame``)."""

from __future__ import annotations

import functools
import time

from flask import Flask, Response

from ..core.logging_setup import get_logger
from .constants import (
    FRAME_MISSING_MESSAGE,
    FRAME_WAIT_S,
    STREAM_DISABLED_MESSAGE,
    STREAM_STALE_WARN_S,
)
from .context import WebContext, json_error
from .state import DashboardState

_logger = get_logger("posture_monitor.web.streaming")


@functools.lru_cache(maxsize=1)
def _placeholder_jpeg() -> bytes | None:
    """Ảnh JPEG xám 320x240 giữ chỗ khi camera chưa gửi khung đầu tiên."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    frame = np.full((240, 320, 3), 32, dtype=np.uint8)
    ok, buffer = cv2.imencode(".jpg", frame)
    return buffer.tobytes() if ok else None


def mjpeg_stream(dashboard: DashboardState):
    """Sinh luồng ``multipart/x-mixed-replace`` từ khung mới nhất trong bộ nhớ."""
    from . import app as app_mod  # noqa: PLC0415

    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    seq = 0
    last_jpeg: bytes | None = None
    last_at = time.monotonic()
    warned_empty = False
    warned_stale = False
    while True:
        wait_s = getattr(app_mod, "STREAM_WAIT_S", 2.0)
        stale_warn_s = getattr(app_mod, "STREAM_STALE_WARN_S", STREAM_STALE_WARN_S)
        new_seq, frame = dashboard.wait_frame(seq, timeout=wait_s)
        if frame is not None and new_seq != seq:
            seq = new_seq
            last_jpeg = frame
            last_at = time.monotonic()
            warned_empty = False
            warned_stale = False
        if last_jpeg is None:
            if not warned_empty:
                warned_empty = True
                _logger.info(
                    "Luồng xem đang chờ khung đầu tiên từ camera; đang gửi ảnh "
                    "giữ chỗ, sẽ thay bằng hình thật ngay khi có khung."
                )
            placeholder = _placeholder_jpeg()
            if placeholder is not None:
                yield boundary + placeholder + b"\r\n"
            continue
        if not warned_stale and time.monotonic() - last_at >= stale_warn_s:
            warned_stale = True
            _logger.warning(
                "Không có khung mới trong %.0f giây; luồng xem đang lặp lại "
                "khung cuối. Kiểm tra camera/kết nối RTSP.",
                stale_warn_s,
            )
        yield boundary + last_jpeg + b"\r\n"


def register_streaming_routes(app: Flask, ctx: WebContext) -> None:
    """Đăng ký ``GET /stream`` và ``GET /api/frame``."""

    @app.get("/stream")
    def stream() -> Response:
        if not ctx.stream_enabled:
            return json_error(STREAM_DISABLED_MESSAGE, 403)
        return Response(
            mjpeg_stream(ctx.dashboard),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/api/frame")
    def api_frame() -> Response:
        from . import app as app_mod  # noqa: PLC0415

        if not ctx.stream_enabled:
            return json_error(STREAM_DISABLED_MESSAGE, 403)

        wait_s = getattr(app_mod, "FRAME_WAIT_S", FRAME_WAIT_S)
        _seq, frame = ctx.dashboard.wait_frame(-1, timeout=wait_s)
        if frame is None or len(frame) == 0:
            return json_error(FRAME_MISSING_MESSAGE, 503)

        response = Response(frame, mimetype="image/jpeg")
        response.headers["Cache-Control"] = "no-store"
        return response
