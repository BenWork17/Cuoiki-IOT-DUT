"""Nhóm route âm thanh & xoay camera: ``/api/speak``, ``/api/voice``, ``/api/ptz``."""

from __future__ import annotations

from typing import Mapping

from flask import Flask, Response, jsonify, request

from ...camera import control as camera_control
from ...camera.audio import (
    DEFAULT_TONE_DURATION_S,
    DEFAULT_TONE_HZ,
    CameraAudioBusy,
    CameraAudioConfigError,
    CameraAudioError,
    CameraAudioInputError,
    CameraAudioUnavailable,
)
from ...core.labels import VOICE_LABELS, VOICES
from ...core.logging_setup import get_logger
from ..constants import (
    PTZ_DEFAULT_DURATION_S,
    PTZ_DIRECTION_TEXT,
    PTZ_DIRECTIONS,
    SPEAKER_DISABLED_MESSAGE,
)
from ..context import WebContext, json_error

_logger = get_logger("posture_monitor.web.routes.media")


def register_media_routes(app: Flask, ctx: WebContext) -> None:
    """Đăng ký ``POST /api/speak``, ``GET/POST /api/voice`` và ``POST /api/ptz``."""

    @app.post("/api/speak")
    def api_speak() -> Response:
        body = request.get_json(silent=True)
        if body is None:
            if request.get_data(cache=True):
                return json_error(
                    "Thân request của /api/speak không phải JSON hợp lệ.", 400
                )
            body = {}
        if not isinstance(body, Mapping):
            return json_error(
                "Thân request của /api/speak phải là một đối tượng JSON.", 400
            )

        try:
            controller = ctx.resolve_speak_controller()
        except CameraAudioConfigError as exc:
            return json_error(str(exc), 403)

        file_path = body.get("file")
        if file_path is not None and not isinstance(file_path, str):
            return json_error("'file' phải là chuỗi đường dẫn.", 400)

        try:
            if file_path:
                result = controller.speak_file(file_path)
            else:
                tone_hz = body.get("tone_hz", DEFAULT_TONE_HZ)
                duration = body.get("duration", DEFAULT_TONE_DURATION_S)
                result = controller.speak_tone(tone_hz, duration)
        except CameraAudioInputError as exc:
            return json_error(str(exc), 400)
        except CameraAudioBusy as exc:
            return json_error(str(exc), 409)
        except CameraAudioUnavailable as exc:
            return json_error(str(exc), 503)
        except CameraAudioError as exc:
            return json_error(str(exc), 502)

        payload = {"ok": True, "message": "Đã phát tiếng ra loa camera."}
        payload.update(result.as_dict())
        return jsonify(payload)

    @app.get("/api/voice")
    def api_voice() -> Response:
        if ctx.speaker is None:
            return jsonify(
                {
                    "ok": True,
                    "available": False,
                    "voice": None,
                    "voices": {},
                    "fallbacks": {},
                    "message": SPEAKER_DISABLED_MESSAGE,
                }
            )
        try:
            report = ctx.speaker.voice_report()
        except Exception as exc:  # noqa: BLE001
            _logger.error("Không đọc được trạng thái giọng đọc: %s", exc)
            return json_error("Không đọc được trạng thái giọng đọc.", 503)
        payload = {"ok": True, "available": True}
        payload.update(report)
        return jsonify(payload)

    @app.post("/api/voice")
    def api_voice_set() -> Response:
        if ctx.speaker is None:
            return json_error(SPEAKER_DISABLED_MESSAGE, 503)
        body = request.get_json(silent=True)
        if not isinstance(body, Mapping):
            return json_error(
                'Thân request phải là một đối tượng JSON dạng {"voice": "nam"|"nu"|"espeak"}.',
                400,
            )
        requested = body.get("voice")
        if not isinstance(requested, str) or not requested.strip():
            return json_error("Thiếu khóa 'voice' (chuỗi) trong request.", 400)

        if requested.strip().lower() not in VOICES:
            return json_error(
                f"Giọng '{requested}' không hợp lệ; chọn một trong "
                f"{', '.join(VOICE_LABELS[v] for v in VOICES)}.",
                400,
            )
        try:
            report = ctx.speaker.set_voice(requested)
        except Exception as exc:  # noqa: BLE001
            _logger.error("Không đổi được giọng đọc: %s", exc)
            return json_error("Không đổi được giọng đọc.", 503)
        payload = {
            "ok": True,
            "available": True,
            "message": f"Đã đổi sang {VOICE_LABELS[report['voice']].lower()}.",
        }
        payload.update(report)
        return jsonify(payload)

    @app.post("/api/ptz")
    def api_ptz() -> Response:
        body = request.get_json(silent=True)
        if not isinstance(body, Mapping):
            return json_error(
                'Thân request phải là JSON dạng {"direction": "left"|"right"|"up"|"down"}.',
                400,
            )

        direction = body.get("direction")
        if not isinstance(direction, str) or direction.strip().lower() not in PTZ_DIRECTIONS:
            return json_error(
                "Hướng xoay phải là 'left', 'right', 'up' hoặc 'down'.", 400
            )
        direction = direction.strip().lower()

        duration = body.get("duration", PTZ_DEFAULT_DURATION_S)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            return json_error("Thời gian xoay phải là một số (giây).", 400)
        if float(duration) < 0:
            return json_error("Thời gian xoay không được âm.", 400)

        try:
            controller = ctx.resolve_ptz()
            moved_s = controller.move_direction(direction, float(duration))
        except camera_control.PtzError as exc:
            return json_error(str(exc), int(getattr(exc, "status", 503)))
        except Exception:  # noqa: BLE001
            _logger.exception("Lỗi không lường trước khi điều khiển PTZ.")
            return json_error(
                "Không điều khiển được camera. Xem log để biết chi tiết.", 500
            )

        return jsonify(
            {
                "ok": True,
                "direction": direction,
                "duration": moved_s,
                "message": f"Đã xoay camera sang {PTZ_DIRECTION_TEXT[direction]}.",
            }
        )
