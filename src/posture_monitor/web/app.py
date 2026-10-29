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

from .. import camera_control
from ..classifier import LABEL_ORDER
from ..logging_setup import get_logger
from .people_service import PeopleService, PeopleServiceError
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

#: Hướng PTZ hợp lệ, khớp khóa của ``camera_control.DIRECTION_VECTORS``.
#: Route từ chối hướng lạ trước khi chạm camera.
PTZ_DIRECTIONS = ("left", "right", "up", "down")

#: Thời gian xoay mặc định cho một cú bấm (giây), dùng khi client không gửi
#: ``duration``. Chặn trên/dưới thuộc về ``camera_control`` — một nguồn sự
#: thật duy nhất, tránh hai nơi ép hai kiểu.
PTZ_DEFAULT_DURATION_S = 0.5

#: Nhãn tiếng Việt của từng hướng, dùng cho thông điệp trả về UI.
PTZ_DIRECTION_TEXT = {
    "left": "trái",
    "right": "phải",
    "up": "lên",
    "down": "xuống",
}

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

#: Câu trả về khi phiên chạy không được tiêm dịch vụ người học.
#: Trang chủ vẫn render bình thường; chỉ các khối liên quan hiện câu này
#: thay cho lỗi, và mọi route người học trả 503 (không phải 500).
PEOPLE_DISABLED_MESSAGE = (
    "Tính năng người học chưa được bật trong phiên chạy này."
)

#: Ba khóa công khai của một người học. **Danh sách trắng** là lớp chặn
#: quyền riêng tư: kể cả dịch vụ lỡ trả thêm ``embedding``/``vector`` thì
#: route cũng không đẩy chúng ra HTTP (spec §5.13.1, §8.3).
PUBLIC_PERSON_FIELDS = ("id", "name", "created_ts")


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
    ptz=None,
    *,
    people: PeopleService | None = None,
) -> Flask:
    """Tạo ứng dụng Flask.

    Args:
        config: :class:`posture_monitor.config.Config`; chỉ đọc ``web`` (cổng,
            stream), ``sensors`` (ngưỡng hiển thị), ``camera.onvif`` (điều
            khiển PTZ) và ``camera.speaker`` (loa camera). Có thể là ``None``
            khi test, dùng mặc định của spec.
        state: :class:`DashboardState` dùng chung với vòng lặp chính; ``None``
            thì tạo mới (tiện cho test và cho ``/stream`` bị tắt).
        storage: :class:`posture_monitor.storage.Storage`; ``None`` thì
            ``/api/history`` trả kết quả rỗng thay vì lỗi.
        speak_controller: :class:`posture_monitor.camera_audio.SpeakController`
            cho ``POST /api/speak``. ``None`` thì dựng từ ``config.camera.speaker``
            ở lần gọi đầu tiên (để thiếu cấu hình không làm sập lúc khởi động).
            Tham số thêm ở cuối, có mặc định — lời gọi cũ không phải đổi.
        ptz: :class:`posture_monitor.camera_control.PtzController` (hoặc đối
            tượng có ``move_direction``). ``None`` thì tạo từ
            ``config.camera.onvif`` ở lần gọi ``/api/ptz`` đầu tiên — nhờ vậy
            không mở phiên ONVIF khi người dùng chưa từng bấm nút xoay, và
            test tiêm được bản giả mà không cần camera.
        people: dịch vụ người học theo :class:`PeopleService` (spec v3 §5.16).
            Keyword-only, mặc định ``None``: khi chưa nối dây, mọi route
            ``/api/people*``, ``/api/enroll*``, ``/api/select``,
            ``/api/schedule``, ``/api/signals`` trả 503 kèm thông điệp tiếng
            Việt, và trang chủ vẫn render bình thường.

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
    app.config["PEOPLE"] = people
    people_enabled = people is not None

    _speak_lock = threading.Lock()
    _speak_state: dict[str, SpeakController | None] = {"controller": speak_controller}

    def _resolve_speak_controller() -> SpeakController:
        """Controller cho ``/api/speak``; dựng một lần từ ``camera.speaker``.

        Cố ý trễ: thiếu mục ``camera.speaker`` phải làm hỏng **một** request
        với lỗi tiếng Việt, không làm sập dashboard lúc khởi động. Khóa chỉ
        bảo vệ việc dựng, không giữ trong lúc phát (controller tự lo việc đó).
        """
        if _speak_state["controller"] is not None:
            return _speak_state["controller"]
        with _speak_lock:
            if _speak_state["controller"] is None:
                _speak_state["controller"] = SpeakController.from_config(config)
            return _speak_state["controller"]

    app.config["PTZ_CONTROLLER"] = ptz
    # Bảo vệ bước tạo controller lười: hai request đồng thời không được mở hai
    # phiên ONVIF (mỗi phiên tốn vài round-trip SOAP xuống camera).
    ptz_create_lock = threading.Lock()

    def _get_ptz():
        """Trả controller PTZ, tạo một lần từ cấu hình nếu chưa được tiêm."""
        controller = app.config.get("PTZ_CONTROLLER")
        if controller is not None:
            return controller
        with ptz_create_lock:
            controller = app.config.get("PTZ_CONTROLLER")
            if controller is None:
                controller = camera_control.from_config(config)
                app.config["PTZ_CONTROLLER"] = controller
        return controller

    @app.get("/")
    def index() -> str:
        """Dashboard tiếng Việt, dùng được trên màn hình điện thoại."""
        return render_template(
            "index.html",
            stream_enabled=stream_enabled,
            min_distance_cm=min_distance,
            people_enabled=people_enabled,
            people_disabled_message=PEOPLE_DISABLED_MESSAGE,
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

    @app.post("/api/ptz")
    def api_ptz() -> Response:
        """Xoay camera theo một hướng trong một khoảng ngắn.

        Thân JSON: ``{"direction": "left"|"right"|"up"|"down",
        "duration": <giây, tuỳ chọn>}``. Giá trị âm hoặc không phải số bị trả
        400 ngay; giá trị quá lớn được ``camera_control`` ép về chặn trên của
        nó (không phải lỗi: UI bấm giữ cũng chỉ cần xoay ngắn), và câu trả lời
        chứa ``duration`` **thực tế** đã xoay.

        Luôn trả JSON. Lỗi cấu hình/thiếu thư viện/camera không hỗ trợ được
        quy về mã HTTP tương ứng và thông điệp tiếng Việt; mật khẩu camera
        không bao giờ đi qua đây (xem ``camera_control``).
        """
        body = request.get_json(silent=True)
        if not isinstance(body, Mapping):
            return _json_error(
                "Thân request phải là JSON dạng "
                '{"direction": "left"|"right"|"up"|"down"}.',
                400,
            )

        direction = body.get("direction")
        if not isinstance(direction, str) or direction.strip().lower() not in (
            PTZ_DIRECTIONS
        ):
            return _json_error(
                "Hướng xoay phải là 'left', 'right', 'up' hoặc 'down'.",
                400,
            )
        direction = direction.strip().lower()

        duration = body.get("duration", PTZ_DEFAULT_DURATION_S)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            return _json_error("Thời gian xoay phải là một số (giây).", 400)
        if float(duration) < 0:
            return _json_error("Thời gian xoay không được âm.", 400)

        try:
            controller = _get_ptz()
            moved_s = controller.move_direction(direction, float(duration))
        except camera_control.PtzError as exc:
            return _json_error(str(exc), int(getattr(exc, "status", 503)))
        except Exception:  # noqa: BLE001 - web không được sập vì camera
            _logger.exception("Lỗi không lường trước khi điều khiển PTZ.")
            return _json_error(
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

    @app.get("/stream")
    def stream() -> Response:
        """MJPEG camera, phục vụ từ khung mới nhất **trong bộ nhớ**.

        Khung hình đi thẳng ``DashboardState`` → trình duyệt: không ghi ra
        đĩa, không lưu lịch sử ảnh (spec v2 §11.5 cấm *lưu/truyền* ảnh;
        hiển thị trực tiếp trong LAN, không lưu, là việc khác). Bật/tắt bằng
        ``web.stream_enabled``; tắt thì trả 403 kèm thông điệp tiếng Việt.
        """
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

    # ------------------------------------------------------------------
    # Người học (spec v3 §5.16). Mọi route dưới đây đều đi qua một lớp
    # chuyển đổi lỗi chung: lỗi nghiệp vụ -> 400, lỗi hệ thống -> 503.
    # Không route nào trả embedding (spec §5.13.1, §8.3).
    # ------------------------------------------------------------------
    def _people_unavailable() -> Response:
        """503 khi phiên chạy không được tiêm dịch vụ người học."""
        return _json_error(PEOPLE_DISABLED_MESSAGE, 503)

    def _people_call(call: Callable[[], Any]) -> tuple[bool, Any]:
        """Gọi dịch vụ; trả ``(True, kết_quả)`` hoặc ``(False, response_lỗi)``.

        ``PeopleServiceError`` là lỗi người dùng sửa được (tên rỗng, không
        tìm thấy người…) nên thành 400. Mọi lỗi khác là sự cố hệ thống: ghi
        log đầy đủ ở phía máy chủ nhưng chỉ trả câu tiếng Việt chung — traceback
        không bao giờ đi ra client.
        """
        try:
            return True, call()
        except PeopleServiceError as exc:
            return False, _json_error(str(exc), 400)
        except Exception:  # noqa: BLE001 - web không được sập vì dịch vụ
            _logger.exception("Lỗi không lường trước từ dịch vụ người học.")
            return False, _json_error(
                "Dịch vụ người học đang gặp sự cố. Xem log để biết chi tiết.",
                503,
            )

    @app.get("/api/people")
    def api_people() -> Response:
        """Danh sách người đã đăng ký + ai đang được chọn cho phiên này."""
        if people is None:
            return _people_unavailable()
        ok, result = _people_call(
            lambda: (
                [_public_person(item) for item in people.list_people()],
                people.selected_person(),
            )
        )
        if not ok:
            return result
        directory, selected = result
        return jsonify({"people": directory, "selected": selected})

    @app.post("/api/people")
    def api_people_add() -> Response:
        """Bắt đầu đăng ký một người mới: ``{"name": "..."}`` → 201."""
        if people is None:
            return _people_unavailable()
        body = request.get_json(silent=True)
        if not isinstance(body, Mapping):
            return _json_error(
                'Thân request phải là JSON dạng {"name": "..."}.', 400
            )
        name = body.get("name")
        if not isinstance(name, str):
            return _json_error("Tên người học phải là chữ.", 400)
        name = name.strip()
        if not name:
            return _json_error("Tên người học không được để trống.", 400)

        ok, result = _people_call(lambda: people.start_enroll(name))
        if not ok:
            return result
        payload = {"ok": True, "name": name}
        payload.update(result)
        return jsonify(payload), 201

    @app.delete("/api/people/<person_id>")
    def api_people_delete(person_id: str) -> Response:
        """Xoá một người học (bản ghi + vector); 404 nếu không tồn tại."""
        if people is None:
            return _people_unavailable()
        ok, result = _people_call(lambda: people.delete_person(person_id))
        if not ok:
            return result
        if not result:
            return _json_error(
                f"Không tìm thấy người học có mã {person_id!r}.", 404
            )
        return jsonify({"ok": True, "message": "Đã xoá người học."})

    @app.get("/api/enroll/<enroll_id>")
    def api_enroll_status(enroll_id: str) -> Response:
        """Tiến độ một phiên đăng ký: bước hiện tại, số mẫu, lỗi (nếu có)."""
        if people is None:
            return _people_unavailable()
        ok, result = _people_call(lambda: people.enroll_status(enroll_id))
        if not ok:
            return result
        return jsonify({"ok": True, "enroll_id": enroll_id, **dict(result)})

    @app.post("/api/enroll/<enroll_id>/cancel")
    def api_enroll_cancel(enroll_id: str) -> Response:
        """Huỷ phiên đăng ký; không ghi gì thêm."""
        if people is None:
            return _people_unavailable()
        ok, result = _people_call(lambda: people.cancel_enroll(enroll_id))
        if not ok:
            return result
        if not result:
            return _json_error(
                f"Không có phiên đăng ký nào đang chạy với mã {enroll_id!r}.",
                404,
            )
        return jsonify({"ok": True, "message": "Đã huỷ phiên đăng ký."})

    @app.post("/api/select")
    def api_select() -> Response:
        """Chọn người đang học cho phiên này; ``person_id: null`` = bỏ chọn."""
        if people is None:
            return _people_unavailable()
        body = request.get_json(silent=True)
        if not isinstance(body, Mapping) or "person_id" not in body:
            return _json_error(
                'Thân request phải có khóa "person_id" (chuỗi hoặc null).',
                400,
            )
        person_id = body["person_id"]
        if person_id is not None and not isinstance(person_id, str):
            return _json_error('"person_id" phải là chuỗi hoặc null.', 400)

        ok, result = _people_call(lambda: people.select_person(person_id))
        if not ok:
            return result
        if not result:
            return _json_error(
                f"Không tìm thấy người học có mã {person_id!r}.", 404
            )
        message = (
            "Đã bỏ chọn người đang học."
            if person_id is None
            else "Đã chọn người đang học."
        )
        return jsonify({"ok": True, "selected": person_id, "message": message})

    @app.get("/api/signals")
    def api_signals() -> Response:
        """Tín hiệu thô gần nhất (presence/phone/identity) + tuổi tín hiệu.

        Dịch vụ đã hứa không trả embedding; lớp này soát lại lần nữa để một
        lần nối dây lơ đãng không biến dashboard thành đường rò vector.
        """
        if people is None:
            return _people_unavailable()
        ok, result = _people_call(people.signals)
        if not ok:
            return result
        return jsonify(_scrub_biometrics(dict(result)))

    @app.get("/api/schedule")
    def api_schedule_get() -> Response:
        """Khung giờ học hiện tại."""
        if people is None:
            return _people_unavailable()
        ok, result = _people_call(people.get_schedule)
        if not ok:
            return result
        return jsonify({"ok": True, "schedule": result})

    @app.put("/api/schedule")
    def api_schedule_put() -> Response:
        """Ghi khung giờ học; dịch vụ kiểm tra và báo lỗi tiếng Việt."""
        if people is None:
            return _people_unavailable()
        body = request.get_json(silent=True)
        if not isinstance(body, Mapping):
            return _json_error(
                "Thân request phải là một đối tượng JSON mô tả giờ học.", 400
            )
        ok, result = _people_call(lambda: people.put_schedule(dict(body)))
        if not ok:
            return result
        return jsonify({"ok": True, "schedule": result})

    @app.errorhandler(404)
    def not_found(error):  # pragma: no cover - Flask tự lo phần HTML
        if request.path.startswith("/api/"):
            return _json_error("Không có API này.", 404)
        return error

    return app


def _mjpeg(dashboard: DashboardState):
    """Sinh luồng MJPEG từ khung mới nhất của vòng lặp chính.

    Nếu chưa có khung nào — hoặc không có khung **mới** trong
    ``STREAM_WAIT_S`` giây — trả placeholder rồi tiếp tục chờ. Không treo im
    lặng và không tự mở camera.

    Placeholder khi khung cũ là cố ý: lặp lại khung cuối mãi mãi sẽ hiện một
    ảnh đứng mà người xem tưởng vẫn là hình sống. Camera đứt giữa chừng phải
    nhìn ra được.
    """
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    placeholder = (
        b"--frame\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        + "Chưa có khung hình từ camera.\r\n".encode("utf-8")
    )
    seq = 0
    while True:
        new_seq, frame = dashboard.wait_frame(seq)
        if frame is None or new_seq == seq:
            # Không có khung nào, hoặc hết giờ chờ mà chưa có khung mới.
            yield placeholder
            seq = new_seq
            continue
        seq = new_seq
        yield boundary + frame + b"\r\n"


def _public_person(item: Mapping[str, Any]) -> dict[str, Any]:
    """Lọc một bản ghi người học xuống đúng ba khóa công khai.

    Danh sách trắng chứ không phải danh sách đen: thêm một trường nội bộ vào
    dịch vụ (embedding, đường dẫn ảnh…) không tự động rò ra HTTP. Đây là lớp
    chặn §8.3 "không route nào trả vector", độc lập với việc dịch vụ có giữ
    lời hứa hay không.
    """
    return {key: item.get(key) for key in PUBLIC_PERSON_FIELDS}


#: Tên khóa mang dữ liệu sinh trắc học; so khớp không phân biệt hoa thường và
#: ở mọi cấp lồng, vì một dict lồng sai vẫn là rò rỉ.
_BIOMETRIC_KEYS = ("embedding", "embeddings", "vector", "vectors", "feature")


def _scrub_biometrics(value: Any) -> Any:
    """Bỏ mọi khóa sinh trắc học khỏi cấu trúc JSON trước khi trả cho client."""
    if isinstance(value, Mapping):
        return {
            key: _scrub_biometrics(item)
            for key, item in value.items()
            if str(key).lower() not in _BIOMETRIC_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_scrub_biometrics(item) for item in value]
    return value


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
