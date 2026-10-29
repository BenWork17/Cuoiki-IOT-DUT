"""Điều khiển PTZ của camera IP qua ONVIF (spec v2 §5.10).

Camera IP gắn cố định không phải lúc nào cũng nhìn đúng bàn học, nên dashboard
có bốn nút xoay trái/phải/lên/xuống. Module này là chỗ duy nhất trong dự án
nói chuyện với ONVIF; phần web chỉ gọi :meth:`PtzController.move_direction`.

Thiết kế:

- **Lazy thật.** ``__init__`` chỉ lưu cấu hình, không mở socket. Phiên ONVIF
  chỉ được mở ở lần ``move`` đầu tiên và được **cache** cho các lần sau. Mỗi
  lần mở phiên, thư viện phải gửi ``GetServices`` + ``GetNodes`` +
  ``GetProfiles`` xuống camera, nên mở lại mỗi request sẽ vừa chậm vừa làm
  camera bận.
- **Khoá ``threading.Lock``.** Flask dev server chạy đa luồng; hai cú bấm liên
  tiếp không được chồng lên nhau trên cùng một phiên SOAP.
- **Chặn trên ``duration_s``.** Một request không được giữ khoá lâu hơn
  :data:`MAX_MOVE_DURATION_S`; mặc định dùng :data:`DEFAULT_MOVE_DURATION_S`.
- **Thư viện là tuỳ chọn.** ``rtsp-backchannel`` không có mặt trên máy thì
  module vẫn import được, và mọi lỗi hiện ra bằng tiếng Việt (spec §11: không
  crash khi thiếu phần cứng/thư viện) — không traceback ra web.

Phần biết về thư viện nằm gọn trong :class:`_LibrarySession`; phần còn lại chỉ
làm việc với một giao diện nhỏ (``continuous_move``/``stop``/``close``), nên
test tiêm được phiên giả mà không cần cài ``rtsp-backchannel``.

Mọi thông điệp lỗi/log có thể chứa ``host``/URL đều đi qua
:func:`posture_monitor.config.redact_camera_source`.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from .config import (
    CAMERA_SOURCE_ENV,
    ONVIF_PASSWORD_ENV,
    onvif_credentials,
    redact_camera_source,
)
from .logging_setup import get_logger

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

#: Chặn trên thời gian xoay của **một** request. Phải đủ ngắn để một request
#: hỏng không giữ khoá quá lâu, nhưng vẫn dài hơn một cú bấm bình thường.
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

    ``status`` là mã HTTP gợi ý cho route web, để route không phải đoán lại
    loại lỗi: cấu hình sai (400), thiếu thư viện (503), camera không hỗ trợ
    (501), không kết nối/nhận lệnh được (502).
    """

    def __init__(self, message: str, *, status: int = 503) -> None:
        super().__init__(message)
        self.status = status


def _load_library() -> Mapping[str, Any]:
    """Nạp ``rtsp_backchannel`` khi thực sự cần.

    Không cache ở cấp module: nếu người dùng cài thư viện trong lúc chương
    trình đang chạy thì lần gọi sau vẫn thấy (import chậm này rất rẻ).

    Raises:
        PtzError: thư viện chưa được cài. Thông điệp tiếng Việt, không kèm
            traceback của ``ImportError``.
    """
    try:
        import rtsp_backchannel  # noqa: PLC0415 - cố ý import muộn
    except ImportError as exc:
        raise PtzError(MISSING_LIBRARY_MESSAGE, status=503) from exc
    return rtsp_backchannel


def _is_unsupported_ptz(exc: BaseException) -> bool:
    """``True`` nếu ``exc`` là tín hiệu "camera không hỗ trợ Continuous".

    Thư viện dùng ``RuntimeError("PTZ continuous pan/tilt is not supported")``
    cho trường hợp này, nhưng ``RuntimeError`` cũng là lớp cha của vài lỗi
    mạng. Chỉ coi là không hỗ trợ khi thông điệp nói đúng như vậy.
    """
    text = str(exc).lower()
    return "not supported" in text or "không hỗ trợ" in text


def _clamp_duration(duration_s: float | None) -> float:
    """Ép ``duration_s`` vào :data:`MIN_MOVE_DURATION_S`..:data:`MAX_MOVE_DURATION_S`.

    ``None`` → :data:`DEFAULT_MOVE_DURATION_S`. ``NaN``/vô cực/không phải số
    cũng về giá trị mặc định thay vì đẩy thẳng vào SOAP (camera sẽ từ chối
    hoặc, tệ hơn, hiểu ``PTNaNS`` thành chặn 0).
    """
    if duration_s is None:
        return DEFAULT_MOVE_DURATION_S
    try:
        value = float(duration_s)
    except (TypeError, ValueError):
        return DEFAULT_MOVE_DURATION_S
    # NaN không so sánh được với chính nó; vô cực thì vượt chặn trên.
    if value != value:
        return DEFAULT_MOVE_DURATION_S
    return max(MIN_MOVE_DURATION_S, min(MAX_MOVE_DURATION_S, value))


class _LibrarySession:
    """Bọc ``PtzSession`` thật, nhận vector dạng ``(dx, dy)``.

    Tách riêng để mọi chỗ biết về ``PtzVector``/``timeout_ms`` của thư viện
    chỉ nằm ở đây. Giao diện mà :class:`PtzController` dùng:

    - ``continuous_move(pan_tilt=(dx, dy), timeout_ms=...)``
    - ``stop(pan_tilt=True, zoom=True)``
    - ``close()``
    """

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
    """Quản lý một phiên ONVIF PTZ dùng chung cho mọi request web.

    Args:
        host: địa chỉ camera IP (ONVIF device service).
        port: cổng HTTP ONVIF (mặc định 80).
        user: tài khoản ONVIF.
        password: mật khẩu ONVIF. Đọc từ biến môi trường bởi
            :func:`posture_monitor.config.onvif_credentials` ở nơi tạo đối
            tượng,
            **không** đặt trong ``config.yaml``.
        profile_token: mã profile media, ``None`` để thư viện tự chọn.
        timeout: thời gian chờ tối đa của một lệnh SOAP (giây).
        opener: hàm mở phiên trả đối tượng có giao diện của
            :class:`_LibrarySession` — điểm tiêm phụ thuộc cho test.
        sleeper: hàm ngủ (giây); mặc định :func:`time.sleep`. Tiêm được để
            test không phải chờ thật.
    """

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
        # Mật khẩu chỉ giữ trong bộ nhớ; không đưa vào log, repr hay config.
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
        """URL ONVIF device service của camera.

        Luôn ghi rõ cổng: nếu để thư viện tự dựng danh sách URL, nó dùng
        ``http://{host}/onvif/device_service`` (không cổng), và camera ở cổng
        khác 80 sẽ im lặng thất bại.
        """
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
        """Đóng phiên (nếu có) và khoá vĩnh viễn đối tượng. Gọi lại không lỗi.

        Idempotent: lần gọi thứ hai không mở khoá gì, không ném lỗi. Sau khi
        đóng, mọi ``move`` báo :class:`PtzError` thay vì lặng lẽ mở phiên mới.
        """
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
        """Xoay camera theo vector ``(dx, dy)`` trong ``duration_s`` giây.

        ``continuous_move`` → ngủ đúng ``duration_s`` → ``stop()`` trong
        ``finally``. Nhờ ``stop()`` nằm trong ``finally``, một lỗi giữa chừng
        vẫn để lại camera ở trạng thái đứng yên.

        Args:
            dx: vận tốc ngang, -1..1 (dương = phải).
            dy: vận tốc dọc, -1..1 (dương = lên).
            duration_s: thời gian xoay; ``None`` dùng mặc định, luôn bị ép vào
                :data:`MIN_MOVE_DURATION_S`..:data:`MAX_MOVE_DURATION_S`.

        Returns:
            Thời gian thực sự đã xoay (sau khi ép), để route báo lại cho UI.

        Raises:
            PtzError: thiếu thư viện, không mở được phiên, camera không hỗ trợ
                continuous pan/tilt, hoặc lệnh SOAP thất bại. Thông điệp đã là
                tiếng Việt và không chứa mật khẩu.
        """
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
            # Timeout phía camera lớn hơn thời gian ta ngủ một chút, để nếu
            # tiến trình chết giữa chừng thì chính camera tự dừng (van an toàn
            # của thư viện, xem ``format_ptz_duration``).
            timeout_ms = max(1.0, (duration + 1.0) * 1000.0)

            try:
                session.continuous_move(
                    pan_tilt=(float(dx), float(dy)), timeout_ms=timeout_ms
                )
            except RuntimeError as exc:
                # Thư viện ném RuntimeError("PTZ continuous pan/tilt is not
                # supported") khi camera không quảng cáo Continuous. Lỗi mạng
                # cũng có thể là RuntimeError, nên phải phân biệt bằng thông
                # điệp — nếu không, mất mạng bị báo nhầm thành "camera không
                # hỗ trợ" (501) và người dùng đi sửa sai chỗ.
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
                    # Phiên coi như hỏng: lần sau mở mới. Van an toàn là
                    # timeout phía camera (đã đặt ở trên).
                    self._drop_session()
                    _logger.warning(
                        "Không dừng được camera sau khi xoay: %s",
                        redact_camera_source(str(exc)),
                    )

        return duration

    def move_direction(
        self, direction: str, duration_s: float | None = None
    ) -> float:
        """Xoay theo tên hướng (``left``/``right``/``up``/``down``).

        Raises:
            PtzError: hướng không nằm trong :data:`DIRECTION_VECTORS`.
        """
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
        # Không bao giờ in mật khẩu (kể cả qua repr lồng trong Config).
        return (
            f"PtzController(host={redact_camera_source(self.host)!r}, "
            f"port={self.port}, user={self.user!r})"
        )


def from_config(config: Any) -> PtzController:
    """Tạo :class:`PtzController` từ ``config.camera.onvif``.

    Args:
        config: :class:`posture_monitor.config.Config` (hoặc đối tượng có
            ``camera.onvif`` cùng hình dạng).

    Raises:
        PtzError: ONVIF đang tắt, chưa có ``host``, hoặc thiếu mật khẩu trong
            biến môi trường. Thông điệp tiếng Việt, đã che ``host``.
    """
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

    # Đọc thông tin đăng nhập tại thời điểm tạo (không lưu vào ``onvif``) để
    # nó không bao giờ nằm trong dataclass cấu hình, ``repr`` hay log. Thứ tự
    # ưu tiên: biến môi trường, rồi tài khoản nhúng trong ``camera.source``.
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
