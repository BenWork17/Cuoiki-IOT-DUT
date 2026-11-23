"""Điều khiển PTZ của camera IP qua ONVIF (spec v2 §5.10).

Camera IP gắn cố định không phải lúc nào cũng nhìn đúng bàn học, nên dashboard
có bốn nút xoay trái/phải/lên/xuống. Module này là chỗ duy nhất trong dự án
nói chuyện với ONVIF; phần web chỉ gọi :meth:`PtzController.move_direction`.

Thiết kế:

- **Lazy thật.** ``__init__`` chỉ lưu cấu hình, không mở socket. Phiên ONVIF
  chỉ được mở ở lần ``move`` đầu tiên và được **cache** cho các lần sau.
- **Khoá ``threading.Lock``.** Flask dev server chạy đa luồng; hai cú bấm liên
  tiếp không được chồng lên nhau trên cùng một phiên SOAP.
- **Chặn trên ``duration_s``.** Một request không được giữ khoá lâu hơn
  :data:`MAX_MOVE_DURATION_S`; mặc định dùng :data:`DEFAULT_MOVE_DURATION_S`.
- **Thư viện là tuỳ chọn.** ``rtsp-backchannel`` không có mặt trên máy thì
  module vẫn import được, và mọi lỗi hiện ra bằng tiếng Việt (spec §11).

Mọi thông điệp lỗi/log có thể chứa ``host``/URL đều đi qua
:func:`posture_monitor.core.config.redact_camera_source`.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from ..core.config import (
    CAMERA_SOURCE_ENV,
    ONVIF_PASSWORD_ENV,
    onvif_credentials,
    redact_camera_source,
)
from ..core.logging_setup import get_logger

_logger = get_logger(__name__)

#: Hướng xoay → vector vận tốc ``(x, y)`` theo quy ước ONVIF
#: (``x`` dương = phải, ``y`` dương = lên; cả hai trong khoảng -1..1).
DIRECTION_VECTORS: dict[str, tuple[float, float]] = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "up": (0.0, 1.0),
    "down": (0.0, -1.0),
}

#: Thời gian xoay mặc định cho một cú bấm (giây).
DEFAULT_MOVE_DURATION_S = 0.5

#: Chặn trên thời gian xoay của **một** request.
MAX_MOVE_DURATION_S = 3.0

#: Chặn dưới thời gian xoay; dưới mức này camera coi như đứng yên.
MIN_MOVE_DURATION_S = 0.05

#: Thông điệp dùng chung khi thiếu thư viện, để test và route cùng so một chuỗi.
MISSING_LIBRARY_MESSAGE = (
    "Chưa cài thư viện điều khiển PTZ (rtsp-backchannel). Chạy "
    "'pip install rtsp-backchannel==0.5.2' rồi khởi động lại."
)


class PtzError(RuntimeError):
    """Lỗi điều khiển PTZ; thông điệp tiếng Việt, đã che bí mật.

    ``status`` là mã HTTP gợi ý cho route web: cấu hình sai (400), thiếu thư
    viện (503), camera không hỗ trợ (501), không kết nối/nhận lệnh được (502).
    """

    def __init__(self, message: str, *, status: int = 503) -> None:
        super().__init__(message)
        self.status = status


def _load_library() -> Mapping[str, Any]:
    """Nạp ``rtsp_backchannel`` khi thực sự cần."""
    try:
        import rtsp_backchannel  # noqa: PLC0415 - cố ý import muộn
    except ImportError as exc:
        raise PtzError(MISSING_LIBRARY_MESSAGE, status=503) from exc
    return rtsp_backchannel


def _is_unsupported_ptz(exc: BaseException) -> bool:
    """``True`` nếu ``exc`` là tín hiệu "camera không hỗ trợ Continuous"."""
    text = str(exc).lower()
    return "not supported" in text or "không hỗ trợ" in text


def _clamp_duration(duration_s: float | None) -> float:
    """Ép ``duration_s`` vào :data:`MIN_MOVE_DURATION_S`..:data:`MAX_MOVE_DURATION_S`."""
    if duration_s is None:
        return DEFAULT_MOVE_DURATION_S
    try:
        value = float(duration_s)
    except (TypeError, ValueError):
        return DEFAULT_MOVE_DURATION_S
    if value != value:
        return DEFAULT_MOVE_DURATION_S
    return max(MIN_MOVE_DURATION_S, min(MAX_MOVE_DURATION_S, value))


class _LibrarySession:
    """Bọc ``PtzSession`` thật, nhận vector dạng ``(dx, dy)``."""

    def __init__(self, session: Any, vector_type: Any) -> None:
        self._session = session
        self._vector_type = vector_type

    def continuous_move(
        self, *, pan_tilt: tuple[float, float], timeout_ms: float
    ) -> None:
        dx, dy = pan_tilt
        self._session.continuous_move(
            pan_tilt=self._vector_type(float(dx), float(dy)),
            timeout_ms=timeout_ms,
        )

    def stop(self, *, pan_tilt: bool = True, zoom: bool = True) -> None:
        self._session.stop(pan_tilt=pan_tilt, zoom=zoom)

    def close(self) -> None:
        self._session.close()


class PtzController:
    """Quản lý một phiên ONVIF PTZ dùng chung cho mọi request web."""

    def __init__(
        self,
        host: str,
        *,
        port: int = 80,
        user: str = "",
        password: str = "",
        profile_token: str | None = None,
        timeout: float = 8.0,
        opener: Callable[[], Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.user = user
        self._password = password
        self.profile_token = profile_token
        self.timeout = float(timeout)
        self._opener = opener or self._open_session_default
        self._sleeper = sleeper or time.sleep
        self._lock = threading.Lock()
        self._session: Any | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Vòng đời phiên
    # ------------------------------------------------------------------
    def _device_url(self) -> str:
        """URL ONVIF device service của camera."""
        return f"http://{self.host}:{self.port}/onvif/device_service"

    def _open_session_default(self) -> Any:
        """Mở phiên ONVIF thật (cần mạng). Chỉ gọi từ ``move``."""
        library = _load_library()
        options = library.PtzSessionOptions(
            host=self.host,
            user=self.user,
            password=self._password,
            profile_token=self.profile_token,
            device_urls=[self._device_url()],
            timeout=self.timeout,
        )
        return _LibrarySession(
            library.open_ptz_session(options), library.PtzVector
        )

    def _ensure_session(self) -> Any:
        """Trả phiên đang cache, mở mới khi chưa có. Gọi khi đã giữ khoá."""
        if self._closed:
            raise PtzError("Điều khiển PTZ đã bị đóng.", status=503)
        if self._session is None:
            try:
                self._session = self._opener()
            except PtzError:
                raise
            except Exception as exc:  # noqa: BLE001 - mọi lỗi mạng/ONVIF
                _logger.warning(
                    "Không mở được phiên PTZ tới %s: %s",
                    redact_camera_source(self._device_url()),
                    redact_camera_source(str(exc)),
                )
                raise PtzError(
                    "Không kết nối được tới camera để điều khiển PTZ "
                    f"({redact_camera_source(self.host)}). Kiểm tra camera đã "
                    f"bật, đúng địa chỉ, và đã đặt {ONVIF_PASSWORD_ENV}.",
                    status=502,
                ) from exc
        return self._session

    def _drop_session(self) -> None:
        """Bỏ phiên hỏng để lần ``move`` sau mở lại. Gọi khi đã giữ khoá."""
        session, self._session = self._session, None
        if session is None:
            return
        try:
            session.close()
        except Exception:  # noqa: BLE001 - dọn dẹp best-effort
            _logger.debug("Bỏ qua lỗi khi đóng phiên PTZ hỏng.", exc_info=True)

    def close(self) -> None:
        """Đóng phiên (nếu có) và khoá vĩnh viễn đối tượng. Gọi lại không lỗi."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - đóng phải luôn thành công
                _logger.debug("Bỏ qua lỗi khi đóng phiên PTZ.", exc_info=True)

    # ------------------------------------------------------------------
    # Di chuyển
    # ------------------------------------------------------------------
    def move(
        self, dx: float, dy: float, duration_s: float | None = None
    ) -> float:
        """Xoay camera theo vector ``(dx, dy)`` trong ``duration_s`` giây."""
        if isinstance(dx, bool) or isinstance(dy, bool) or not (
            isinstance(dx, (int, float)) and isinstance(dy, (int, float))
        ):
            raise PtzError("Vector xoay phải là số.", status=400)
        if not (-1.0 <= float(dx) <= 1.0 and -1.0 <= float(dy) <= 1.0):
            raise PtzError("Vector xoay phải nằm trong khoảng -1..1.", status=400)
        if float(dx) == 0.0 and float(dy) == 0.0:
            raise PtzError("Vector xoay bằng 0 thì camera không xoay.", status=400)

        duration = _clamp_duration(duration_s)

        with self._lock:
            session = self._ensure_session()
            timeout_ms = max(1.0, (duration + 1.0) * 1000.0)

            try:
                session.continuous_move(
                    pan_tilt=(float(dx), float(dy)), timeout_ms=timeout_ms
                )
            except RuntimeError as exc:
                if not _is_unsupported_ptz(exc):
                    self._drop_session()
                    _logger.warning(
                        "Lệnh PTZ thất bại: %s", redact_camera_source(str(exc))
                    )
                    raise PtzError(
                        "Camera không nhận lệnh xoay. Kiểm tra kết nối mạng và "
                        "tài khoản ONVIF.",
                        status=502,
                    ) from exc
                self._drop_session()
                _logger.warning(
                    "Camera từ chối lệnh PTZ liên tục: %s",
                    redact_camera_source(str(exc)),
                )
                raise PtzError(
                    "Camera không hỗ trợ xoay liên tục qua ONVIF (chỉ hỗ trợ "
                    "đi tới vị trí hoặc preset).",
                    status=501,
                ) from exc
            except Exception as exc:  # noqa: BLE001 - SOAP/timeout/mạng
                self._drop_session()
                _logger.warning(
                    "Lệnh PTZ thất bại: %s", redact_camera_source(str(exc))
                )
                raise PtzError(
                    "Camera không nhận lệnh xoay. Kiểm tra kết nối mạng và "
                    "tài khoản ONVIF.",
                    status=502,
                ) from exc

            try:
                self._sleeper(duration)
            finally:
                try:
                    session.stop(pan_tilt=True, zoom=True)
                except Exception as exc:  # noqa: BLE001 - stop là best-effort
                    self._drop_session()
                    _logger.warning(
                        "Không dừng được camera sau khi xoay: %s",
                        redact_camera_source(str(exc)),
                    )

        return duration

    def move_direction(
        self, direction: str, duration_s: float | None = None
    ) -> float:
        """Xoay theo tên hướng (``left``/``right``/``up``/``down``)."""
        key = str(direction).strip().lower()
        if key not in DIRECTION_VECTORS:
            raise PtzError(
                "Hướng xoay phải là 'left', 'right', 'up' hoặc 'down', nhận "
                f"được {direction!r}.",
                status=400,
            )
        dx, dy = DIRECTION_VECTORS[key]
        return self.move(dx, dy, duration_s)

    def __repr__(self) -> str:
        return (
            f"PtzController(host={redact_camera_source(self.host)!r}, "
            f"port={self.port}, user={self.user!r})"
        )


def from_config(config: Any) -> PtzController:
    """Tạo :class:`PtzController` từ ``config.camera.onvif``."""
    camera = getattr(config, "camera", None)
    onvif = getattr(camera, "onvif", None)
    if onvif is None or not getattr(onvif, "enabled", False):
        raise PtzError(
            "Điều khiển PTZ đang tắt hoặc chưa cấu hình. Đặt "
            "POSTURE_CAMERA_SOURCE thành URL RTSP của camera (host sẽ được "
            "suy ra), hoặc bật 'camera.onvif.enabled: true' và điền "
            "'camera.onvif.host' trong config.yaml.",
            status=503,
        )
    host = str(getattr(onvif, "host", "")).strip()
    if not host:
        raise PtzError(
            "Chưa xác định được 'camera.onvif.host'. Đặt "
            "POSTURE_CAMERA_SOURCE thành URL RTSP của camera, hoặc điền "
            "'camera.onvif.host' trong config.yaml.",
            status=503,
        )

    source = str(getattr(camera, "source", "") or "")
    user, password = onvif_credentials(onvif, source)
    if not password:
        raise PtzError(
            "Chưa có mật khẩu ONVIF. Đặt biến môi trường "
            f"{ONVIF_PASSWORD_ENV}, hoặc đặt biến môi trường "
            f"{CAMERA_SOURCE_ENV} thành URL RTSP có kèm tài khoản.",
            status=503,
        )
    return PtzController(
        host,
        port=int(getattr(onvif, "port", 80)),
        user=user or str(getattr(onvif, "user", "")),
        password=password,
    )
