"""Ứng dụng Flask của dashboard (spec v2 §5.10).

Kiến trúc: :class:`DashboardState` là **cầu nối duy nhất** giữa vòng lặp
camera và web.

- Vòng lặp chính gọi :meth:`DashboardState.update` mỗi khung (hoặc mỗi giây)
  để đẩy trạng thái hiện tại lên.
- Web đọc lại bằng :meth:`DashboardState.snapshot`; không bao giờ chạm camera.

Lệnh từ web xuống vòng lặp (mute, calibrate) dùng đúng đối tượng đó:

- :attr:`DashboardState.muted` — vòng lặp đọc mỗi khung để quyết định có bật
  buzzer/rung hay không.
- :meth:`DashboardState.request_calibration` đặt cờ; vòng lặp gọi
  :meth:`DashboardState.consume_calibration_request` để lấy và xoá cờ (đọc
  một lần, không lặp lại hiệu chỉnh).

Dữ liệu lịch sử cho biểu đồ đọc từ :class:`posture_monitor.storage.Storage`
(không bắt buộc — thiếu thì API trả kết quả rỗng thay vì lỗi).

**Không mở ra Internet.** ``web.host`` mặc định ``0.0.0.0`` để xem từ điện
thoại trong cùng mạng LAN; không NAT/forward cổng này ra ngoài (spec §5.10).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from flask import Flask, Response, jsonify, render_template, request

from ..classifier import LABEL_ORDER
from ..logging_setup import get_logger
from ..camera_audio import (
    CameraAudioBusy,
    CameraAudioConfigError,
    CameraAudioError,
    CameraAudioInputError,
    CameraAudioUnavailable,
    DEFAULT_TONE_DURATION_S,
    DEFAULT_TONE_HZ,
    SpeakController,
)

_logger = get_logger(__name__)

#: Nhãn tiếng Việt của trạng thái (spec v2 §5.6), dùng cho UI và API.
STATE_TEXT = {
    "GOOD": "Tư thế tốt",
    "WARN": "Cần chú ý",
    "BAD": "Tư thế sai",
    "ABSENT": "Không thấy người",
}

#: Nhãn tiếng Việt của từng nhãn phân loại (spec v2 §5.5).
LABEL_TEXT = {
    "HEAD_DOWN": "Cúi đầu",
    "TOO_CLOSE": "Ngồi quá gần",
    "SHOULDER_TILT": "Nghiêng vai",
    "HEAD_TILT": "Nghiêng đầu",
    "LEAN": "Ngả người",
    "LOOK_AWAY": "Nhìn ra chỗ khác",
    "ABSENT": "Vắng mặt",
    "GOOD": "Đúng tư thế",
}

#: Số giây không có cập nhật thì coi là "dữ liệu cũ" (vòng lặp có thể đã dừng).
STALE_AFTER_S = 10.0

#: Khoảng chờ tối đa giữa hai khung khi phục vụ ``/stream``.
STREAM_WAIT_S = 2.0

#: Khoảng nghỉ giữa hai lần kiểm tra khung mới trong ``/stream``.
STREAM_POLL_S = 0.05


class DashboardState:
    """Trạng thái chia sẻ giữa vòng lặp chính và web, an toàn đa luồng.

    Vòng lặp chính **ghi** (``update``, ``set_frame``, ``set_muted``); Flask
    **đọc** (``snapshot``, ``latest_frame``, ``muted``). Mọi truy cập đi qua
    một khóa, nên web không bao giờ thấy dict đang bị sửa dở.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {
            "state": "ABSENT",
            "labels": [],
            "score": 0.0,
            "sitting_s": 0.0,
            "distance_cm": None,
            "alert": None,
            "message": "",
        }
        self._updated_at: float | None = None
        self._muted = False
        self._calibration_requested = False
        self._frame: bytes | None = None
        self._frame_seq = 0

    # ------------------------------------------------------------------
    # Cập nhật từ vòng lặp chính
    # ------------------------------------------------------------------
    def update(self, status: Mapping[str, Any] | None = None, **fields) -> None:
        """Cập nhật trạng thái hiện tại (nhận dict và/hoặc keyword).

        Chỉ các khóa đã biết mới được nhận; khóa lạ bị bỏ qua kèm log DEBUG để
        Peer nối dây không âm thầm đẩy sai tên trường.
        """
        merged: dict[str, Any] = {}
        if status:
            merged.update(dict(status))
        merged.update(fields)

        with self._lock:
            for key, value in merged.items():
                if key in self._status:
                    self._status[key] = value
                else:
                    _logger.debug("Bỏ qua trường trạng thái lạ: %s", key)
            # Chuẩn hóa để JSON luôn cùng kiểu, bất kể nguồn đẩy vào.
            self._status["labels"] = [
                str(label) for label in (self._status["labels"] or [])
            ]
            self._status["state"] = str(self._status["state"] or "ABSENT")
            self._updated_at = float(self._clock())

    def snapshot(self) -> dict[str, Any]:
        """Bản sao trạng thái hiện tại, kèm thông tin dẫn xuất cho UI."""
        with self._lock:
            status = dict(self._status)
            status["labels"] = list(self._status["labels"])
            updated_at = self._updated_at
            muted = self._muted
            pending = self._calibration_requested

        labels = status["labels"]
        state = status["state"]
        age = None if updated_at is None else max(0.0, self._clock() - updated_at)

        status.update(
            {
                "state_text": STATE_TEXT.get(state, state),
                "label_texts": [
                    LABEL_TEXT.get(label, label)
                    for label in LABEL_ORDER
                    if label in labels
                ],
                "muted": muted,
                "calibration_pending": pending,
                "data_age_s": None if age is None else round(age, 1),
                "stale": age is None or age > STALE_AFTER_S,
            }
        )
        return status

    def set_frame(self, jpeg: bytes | None) -> None:
        """Đặt khung JPEG mới nhất cho ``/stream`` (chỉ khi bật stream)."""
        with self._lock:
            self._frame = jpeg
            self._frame_seq += 1

    def latest_frame(self) -> tuple[int, bytes | None]:
        """Trả ``(số_thứ_tự, khung)`` để ``/stream`` biết khi nào có khung mới."""
        with self._lock:
            return self._frame_seq, self._frame

    # ------------------------------------------------------------------
    # Tiếng (mute)
    # ------------------------------------------------------------------
    @property
    def muted(self) -> bool:
        """Vòng lặp chính đọc thuộc tính này để bỏ qua buzzer/rung."""
        with self._lock:
            return self._muted

    def set_muted(self, muted: bool) -> bool:
        """Đặt trạng thái tiếng; trả giá trị sau khi đặt."""
        value = bool(muted)
        with self._lock:
            self._muted = value
        _logger.info("Tiếng cảnh báo: %s", "TẮT" if value else "BẬT")
        return value

    def toggle_mute(self) -> bool:
        """Đảo trạng thái tiếng; trả giá trị mới."""
        with self._lock:
            self._muted = not self._muted
            value = self._muted
        _logger.info("Tiếng cảnh báo: %s", "TẮT" if value else "BẬT")
        return value

    # ------------------------------------------------------------------
    # Yêu cầu hiệu chỉnh
    # ------------------------------------------------------------------
    def request_calibration(self) -> None:
        """Đặt cờ yêu cầu hiệu chỉnh lại (do người dùng bấm trên web)."""
        with self._lock:
            self._calibration_requested = True
        _logger.info("Đã nhận yêu cầu hiệu chỉnh lại từ dashboard.")

    def consume_calibration_request(self) -> bool:
        """Lấy và xoá cờ hiệu chỉnh; ``True`` nếu có yêu cầu đang chờ."""
        with self._lock:
            pending = self._calibration_requested
            self._calibration_requested = False
        return pending

    def wait_frame(
        self, last_seq: int, timeout: float = STREAM_WAIT_S
    ) -> tuple[int, bytes | None]:
        """Chờ tới khi có khung mới hoặc hết ``timeout``.

        Không giữ khóa trong lúc ngủ, nên vòng lặp chính không bị chặn.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            seq, frame = self.latest_frame()
            if seq != last_seq and frame is not None:
                return seq, frame
            if time.monotonic() >= deadline:
                return seq, frame
            time.sleep(STREAM_POLL_S)


def create_app(
    config=None,
    state: DashboardState | None = None,
    storage=None,
    speak_controller: SpeakController | None = None,
) -> Flask:
    """Tạo ứng dụng Flask.

    Args:
        config: :class:`posture_monitor.config.Config`; chỉ đọc ``web`` (cổng,
            stream), ``sensors`` (ngưỡng hiển thị) và ``camera.onvif`` (loa
            camera). Có thể là ``None`` khi test, dùng mặc định của spec.
        state: :class:`DashboardState` dùng chung với vòng lặp chính; ``None``
            thì tạo mới (tiện cho test và cho ``/stream`` bị tắt).
        storage: :class:`posture_monitor.storage.Storage`; ``None`` thì
            ``/api/history`` trả kết quả rỗng thay vì lỗi.
        speak_controller: :class:`posture_monitor.camera_audio.SpeakController`
            cho ``POST /api/speak``. ``None`` thì dựng từ ``config.camera.onvif``
            ở lần gọi đầu tiên (để thiếu cấu hình không làm sập lúc khởi động).
            Tham số thêm ở cuối, có mặc định — lời gọi cũ không phải đổi.

    Returns:
        :class:`flask.Flask` đã gắn đủ route.
    """
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    # JSON không sắp xếp khóa để giữ thứ tự dễ đọc khi debug bằng mắt.
    app.json.sort_keys = False

    dashboard = state or DashboardState()
    web_cfg = getattr(config, "web", None)
    sensors_cfg = getattr(config, "sensors", None)
    stream_enabled = bool(getattr(web_cfg, "stream_enabled", False))
    min_distance = float(getattr(sensors_cfg, "min_distance_cm", 35.0))

    app.config["DASHBOARD_STATE"] = dashboard
    app.config["STORAGE"] = storage
    app.config["STREAM_ENABLED"] = stream_enabled
    app.config["MIN_DISTANCE_CM"] = min_distance
    app.config["SPEAK_CONTROLLER"] = speak_controller

    _speak_lock = threading.Lock()
    _speak_state: dict[str, SpeakController | None] = {"controller": speak_controller}

    def _resolve_speak_controller() -> SpeakController:
        """Controller cho ``/api/speak``; dựng một lần từ ``camera.onvif``.

        Cố ý trễ: thiếu mục ``camera.onvif`` phải làm hỏng **một** request
        với lỗi tiếng Việt, không làm sập dashboard lúc khởi động. Khóa chỉ
        bảo vệ việc dựng, không giữ trong lúc phát (controller tự lo việc đó).
        """
        if _speak_state["controller"] is not None:
            return _speak_state["controller"]
        with _speak_lock:
            if _speak_state["controller"] is None:
                _speak_state["controller"] = SpeakController.from_config(config)
            return _speak_state["controller"]

    @app.get("/")
    def index() -> str:
        """Dashboard tiếng Việt, dùng được trên màn hình điện thoại."""
        return render_template(
            "index.html",
            stream_enabled=stream_enabled,
            min_distance_cm=min_distance,
        )

    @app.get("/api/status")
    def api_status() -> Response:
        """JSON trạng thái hiện tại; web tự gọi lại mỗi giây."""
        payload = dashboard.snapshot()
        payload["stream_enabled"] = stream_enabled
        payload["min_distance_cm"] = min_distance
        return jsonify(payload)

    @app.get("/api/history")
    def api_history() -> Response:
        """JSON số liệu biểu đồ; ``range=today`` (mặc định) hoặc ``7d``."""
        range_key = request.args.get("range", "today")
        if range_key not in ("today", "7d"):
            return _json_error(
                "Tham số 'range' phải là 'today' hoặc '7d'.", 400
            )
        if storage is None:
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
            return jsonify(storage.history(range_key))
        except Exception as exc:  # noqa: BLE001 - web không được sập vì DB
            _logger.error("Không lấy được lịch sử cho dashboard: %s", exc)
            return _json_error("Không đọc được số liệu đã lưu.", 503)

    @app.post("/api/calibrate")
    def api_calibrate() -> Response:
        """Đặt cờ để vòng lặp chính chạy hiệu chỉnh lại."""
        dashboard.request_calibration()
        return jsonify(
            {
                "ok": True,
                "message": "Đã gửi yêu cầu hiệu chỉnh. Hãy ngồi thẳng trong "
                "5 giây tới.",
                "calibration_pending": True,
            }
        )

    @app.post("/api/mute")
    def api_mute() -> Response:
        """Bật/tắt tiếng cảnh báo.

        Thân request tùy chọn: ``{"muted": true|false}``. Không có thân thì
        đảo trạng thái hiện tại — tiện cho nút bấm trên điện thoại.
        """
        body = request.get_json(silent=True) or {}
        if isinstance(body, Mapping) and "muted" in body:
            muted = dashboard.set_muted(bool(body["muted"]))
        else:
            muted = dashboard.toggle_mute()
        return jsonify(
            {
                "ok": True,
                "muted": muted,
                "message": "Đã tắt tiếng cảnh báo."
                if muted
                else "Đã bật lại tiếng cảnh báo.",
            }
        )

    @app.post("/api/speak")
    def api_speak() -> Response:
        """Phát tiếng ra loa của camera IP (RTSP backchannel).

        Thân JSON, mọi khóa đều tùy chọn::

            {"tone_hz": 880, "duration": 0.5, "file": "duong_dan.mp3"}

        - Không có ``file``: phát tiếng bíp ``tone_hz``/``duration`` — đường
          này tự sinh G.711 nên **không cần ffmpeg**.
        - Có ``file``: phát file đó; cần ffmpeg trên máy chạy dashboard.

        Trả 200 kèm tóm tắt lần phát; lỗi tham số 400, đang phát 409, chưa
        cấu hình loa 403 (giống ``/stream`` khi bị tắt trong config), thiếu
        thư viện/ffmpeg 503, camera lỗi 502. Thông điệp tiếng Việt và không bao
        giờ chứa mật khẩu camera.
        """
        body = request.get_json(silent=True)
        if body is None:
            # Thân rỗng là hợp lệ (dùng tiếng bíp mặc định), nhưng thân có
            # nội dung mà không đọc được thì phải báo lỗi — nếu không, một
            # request JSON hỏng sẽ lặng lẽ phát bíp ngoài ý muốn.
            if request.get_data(cache=True):
                return _json_error(
                    "Thân request của /api/speak không phải JSON hợp lệ.", 400
                )
            body = {}
        if not isinstance(body, Mapping):
            return _json_error(
                "Thân request của /api/speak phải là một đối tượng JSON.", 400
            )

        try:
            controller = _resolve_speak_controller()
        except CameraAudioConfigError as exc:
            return _json_error(str(exc), 403)

        file_path = body.get("file")
        if file_path is not None and not isinstance(file_path, str):
            return _json_error("'file' phải là chuỗi đường dẫn.", 400)

        try:
            if file_path:
                result = controller.speak_file(file_path)
            else:
                tone_hz = body.get("tone_hz", DEFAULT_TONE_HZ)
                duration = body.get("duration", DEFAULT_TONE_DURATION_S)
                result = controller.speak_tone(tone_hz, duration)
        except CameraAudioInputError as exc:
            return _json_error(str(exc), 400)
        except CameraAudioBusy as exc:
            return _json_error(str(exc), 409)
        except CameraAudioUnavailable as exc:
            return _json_error(str(exc), 503)
        except CameraAudioError as exc:
            return _json_error(str(exc), 502)

        payload = {"ok": True, "message": "Đã phát tiếng ra loa camera."}
        payload.update(result.as_dict())
        return jsonify(payload)

    @app.get("/stream")
    def stream() -> Response:
        """MJPEG camera; **tắt mặc định** vì tốn CPU và ảnh hưởng riêng tư."""
        if not stream_enabled:
            return _json_error(
                "Tính năng xem trực tiếp đang tắt. Bật 'web.stream_enabled: "
                "true' trong config.yaml nếu thật sự cần (tốn CPU và ảnh "
                "hưởng quyền riêng tư).",
                403,
            )
        return Response(
            _mjpeg(dashboard),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    @app.errorhandler(404)
    def not_found(error):  # pragma: no cover - Flask tự lo phần HTML
        if request.path.startswith("/api/"):
            return _json_error("Không có API này.", 404)
        return error

    return app


def _mjpeg(dashboard: DashboardState):
    """Sinh luồng MJPEG từ khung mới nhất của vòng lặp chính.

    Nếu chưa có khung nào trong ``STREAM_WAIT_S`` giây, trả placeholder một
    lần rồi tiếp tục chờ — không treo im lặng và không tự mở camera.
    """
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    seq = 0
    while True:
        seq, frame = dashboard.wait_frame(seq)
        if frame is None:
            yield (
                b"--frame\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
                + "Chưa có khung hình từ camera.\r\n".encode("utf-8")
            )
            continue
        yield boundary + frame + b"\r\n"


def _json_error(message: str, status: int) -> Response:
    """Lỗi dạng JSON kèm thông báo tiếng Việt cho UI hiện lên."""
    response = jsonify({"ok": False, "message": message})
    response.status_code = status
    return response


def run_server(app: Flask, config=None, **kwargs) -> None:
    """Chạy server theo ``config.web.host`` / ``config.web.port``.

    Chỉ dùng ``threaded=True`` (mặc định của Flask dev server) để trang web
    không chặn vòng lặp chính khi cùng tiến trình. Đây là server phát triển;
    trong LAN gia đình là đủ, không dùng để mở ra Internet (spec §5.10).
    """
    web_cfg = getattr(config, "web", None)
    host = str(getattr(web_cfg, "host", "0.0.0.0"))
    port = int(getattr(web_cfg, "port", 8000))
    _logger.info(
        "Dashboard chạy tại http://%s:%d/ (chỉ trong LAN, không mở ra "
        "Internet)",
        "127.0.0.1" if host == "0.0.0.0" else host,
        port,
    )
    app.run(host=host, port=port, **kwargs)
