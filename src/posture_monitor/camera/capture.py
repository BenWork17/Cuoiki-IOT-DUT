"""Nguồn ảnh (camera) và phát hiện thiết bị quay hình.

Thiết kế theo spec v2 §5.1:

- Bốn triển khai :class:`FrameSource`: ``OpenCVSource`` (USB webcam / V4L2),
  ``PiCameraSource`` (Pi Camera qua picamera2), ``RTSPSource`` (camera IP qua
  RTSP/FFmpeg) và ``FileSource`` (video file, dùng cho ``replay`` và test trên
  PC).
- Lớp cơ sở nội bộ :class:`_ReconnectableSource` hợp nhất cơ chế thử mở ban đầu
  kèm backoff tăng dần (:data:`BACKOFF_SCHEDULE`) và ngân sách tự kết nối lại
  hữu hạn (``_reconnect_budget``, ``_gave_up``, ``_closed``) cho ba nguồn thiết
  bị trực tiếp.
- Không crash khi thiếu camera: mọi lỗi mở thiết bị được ghi log và trả
  ``None`` ở tầng :func:`capture_from_config`.

Lưu ý phần cứng Pi 4: các node ``/dev/video10..31`` là thiết bị codec/ISP của
SoC (``bcm2835-codec``, ``bcm2835-isp``, ``rpi-hevc-dec``), **không phải**
camera. Chúng thường vẫn ``isOpened()`` được qua OpenCV, nên phải loại theo
tên driver đọc từ sysfs trước, rồi mới thử mở.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..core.config import parse_camera_source, redact_camera_source
from ..core.logging_setup import get_logger

logger = get_logger("posture_monitor.camera.capture")

#: Số lần thử mở (hoặc mở lại) một nguồn trước khi bỏ cuộc.
OPEN_ATTEMPTS = 3

#: Thời gian chờ giữa các lần thử, tính bằng giây (backoff tăng dần).
BACKOFF_SCHEDULE = (0.2, 0.5, 1.0)

#: Biến môi trường OpenCV dùng để truyền cờ cho backend FFmpeg. Toàn tiến
#: trình, nên :class:`RTSPSource` đặt rồi khôi phục ngay sau khi mở.
FFMPEG_OPTIONS_ENV = "OPENCV_FFMPEG_CAPTURE_OPTIONS"

#: Cờ FFmpeg tương ứng lệnh ``ffplay`` của người dùng (xem docs/SPEC_V2.md
#: §5.1). Định dạng của OpenCV là ``key;value`` ghép bằng ``|``.
RTSP_FFMPEG_OPTIONS = "|".join(
    (
        "rtsp_transport;udp",
        "fflags;nobuffer+discardcorrupt",
        "flags;low_delay",
        "framedrop;1",
        "probesize;500000",
        "analyzeduration;1000000",
        "max_delay;500000",
    )
)

#: Trần số khung xả mỗi lần đọc, chặn trường hợp đệm phình bất thường.
RTSP_MAX_DRAIN_FRAMES = 240

#: Ngưỡng thời gian một bước ``grab()`` bị coi là "đã đuổi kịp luồng trực
#: tiếp" và dừng xả, tính bằng giây.
RTSP_DRAIN_STEP_LIMIT_S = 0.03

#: Trần cho **vòng xả** (giây), kiểm giữa các lần ``grab()``.
RTSP_DRAIN_TIME_LIMIT_S = 2.0

#: Thời gian ``read()`` chờ khung **đầu tiên** khi bộ đọc nền vừa khởi động (giây).
RTSP_PREFETCH_FIRST_FRAME_S = 3.0

#: Thời gian ``read()`` chờ một khung **mới** khi bộ đọc nền đã có khung cũ (giây).
RTSP_PREFETCH_NEW_FRAME_S = 1.0

#: Khoảng nghỉ giữa hai vòng của bộ đọc nền khi camera liên tục trả lỗi (giây).
RTSP_PREFETCH_ERROR_BACKOFF_S = 0.2

#: Tên driver các node codec/ISP của SoC Raspberry Pi — tuyệt đối không phải
#: camera, phải loại khỏi danh sách thiết bị.
EXCLUDED_DRIVERS = ("bcm2835-codec", "bcm2835-isp", "rpi-hevc-dec")

#: Thư mục sysfs mô tả các node V4L2 (chỉ có trên Linux).
SYSFS_VIDEO4LINUX = Path("/sys/class/video4linux")

#: Thư mục thiết bị (chỉ có trên Linux).
DEV_DIR = Path("/dev")

#: Đường dẫn đặc trưng của Pi Camera trên Raspberry Pi OS.
VCHIQ_DEVICE = Path("/dev/vchiq")

#: Số chỉ số camera tối đa thử khi không có ``/dev/video*`` (Windows/macOS).
MAX_ENUM_INDEX = 5


class CameraError(RuntimeError):
    """Không mở được nguồn ảnh (thiếu thiết bị, sai đường dẫn, lỗi driver)."""


# --------------------------------------------------------------------------
# Giao diện chung & lớp cơ sở tự kết nối lại
# --------------------------------------------------------------------------


class FrameSource(ABC):
    """Nguồn ảnh trả về khung BGR.

    Hợp đồng:

    - :meth:`read` trả ``numpy.ndarray`` kiểu ``uint8``, hoặc ``None`` khi
      không còn khung / không kết nối lại được. Không raise trong vòng lặp
      đọc bình thường.
    - :meth:`close` giải phóng tài nguyên, gọi được nhiều lần.
    - **Đóng là trạng thái cuối**: sau :meth:`close`, :meth:`read` trả
      ``None`` và không được mở lại thiết bị/kết nối mạng nào. Với nguồn
      mạng (RTSP) mở lại ngầm là rò rỉ tài nguyên và có thể treo vòng lặp.
    """

    @abstractmethod
    def read(self) -> np.ndarray | None:
        """Đọc khung kế tiếp; ``None`` nếu không có."""

    @abstractmethod
    def close(self) -> None:
        """Giải phóng camera/file."""

    @property
    @abstractmethod
    def backend(self) -> str:
        """Tên backend: ``opencv``, ``picamera``, ``file`` hoặc ``rtsp``."""

    def __enter__(self) -> "FrameSource":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _sleep(seconds: float) -> None:
    """Ngủ ngắn; tách riêng để test có thể thay bằng hàm rỗng."""
    if seconds > 0:
        time.sleep(seconds)


def _monotonic() -> float:
    """Đồng hồ đơn điệu; tách riêng để test điều khiển được thời gian."""
    return time.monotonic()


class _ReconnectableSource(FrameSource):
    """Lớp cơ sở hợp nhất thử mở ban đầu và tự kết nối lại theo ngân sách.

    Mọi nguồn trực tiếp (:class:`OpenCVSource`, :class:`RTSPSource`,
    :class:`PiCameraSource`) đều chia sẻ cùng một máy trạng thái kết nối:

    - Thử mở tối đa ``_max_attempts`` lần kèm :data:`BACKOFF_SCHEDULE`.
    - Khi mất kết nối giữa chừng, trừ dần ``_reconnect_budget``; hết ngân sách
      thì đặt ``_gave_up = True``, log lỗi đúng một lần và dừng thử lại.
    - Đọc được khung hợp lệ thì khôi phục ``_reconnect_budget``.
    - Sau ``close()``, ``_closed = True`` chặn vĩnh viễn mọi lần mở lại.
    """

    def __init__(self, max_attempts: int = OPEN_ATTEMPTS) -> None:
        self._max_attempts = max(1, int(max_attempts))
        self._reconnect_budget = self._max_attempts
        self._gave_up = False
        self._closed = False

    @abstractmethod
    def _source_label(self) -> str:
        """Nhãn nguồn ảnh an toàn cho log (đã che mật khẩu nếu có)."""

    @abstractmethod
    def _open_once(self) -> tuple[bool, BaseException | None]:
        """Thử mở thiết bị một lần; trả ``(đã_mở, lỗi_nếu_có)``."""

    @abstractmethod
    def _release_handle(self) -> None:
        """Giải phóng handle thiết bị bên dưới mà không đổi cờ ``_closed``."""

    def _open_retry_hint(self) -> str:
        """Gợi ý khắc phục nối thêm vào cảnh báo thử lại (nếu có)."""
        return ""

    def _open(self, attempts: int | None = None) -> bool:
        """Thử mở thiết bị tối đa ``attempts`` lần kèm backoff tăng dần."""
        total = self._max_attempts if attempts is None else max(1, attempts)
        last_exc: BaseException | None = None
        for attempt in range(1, total + 1):
            opened, last_exc = self._open_once()
            if opened:
                return True
            if attempt < total:
                delay = BACKOFF_SCHEDULE[
                    min(attempt - 1, len(BACKOFF_SCHEDULE) - 1)
                ]
                detail = f": {last_exc}" if last_exc is not None else ""
                hint = self._open_retry_hint()
                logger.warning(
                    "Mở %s thất bại (lần %d/%d)%s, thử lại sau %.1f giây.%s",
                    self._source_label(),
                    attempt,
                    total,
                    detail,
                    delay,
                    f" {hint}" if hint else "",
                )
                _sleep(delay)
        if last_exc is not None:
            logger.error(
                "Mở %s thất bại sau %d lần: %s",
                self._source_label(),
                total,
                last_exc,
            )
        return False

    def _reconnect(self) -> bool:
        """Giải phóng handle cũ rồi mở lại, tối đa ``_reconnect_budget`` lần."""
        if self._closed or self._gave_up:
            return False
        if self._reconnect_budget <= 0:
            self._gave_up = True
            logger.error(
                "%s đã hết %d lần kết nối lại; dừng đọc khung.",
                self._source_label(),
                self._max_attempts,
            )
            return False

        self._reconnect_budget -= 1
        self._release_handle()
        logger.warning(
            "Mất kết nối %s, đang kết nối lại (còn %d lần)...",
            self._source_label(),
            self._reconnect_budget + 1,
        )
        opened = self._open(attempts=1)
        if opened:
            self._reconnect_budget = self._max_attempts
        return opened

    def _mark_frame_ok(self) -> None:
        """Khôi phục ngân sách kết nối lại sau khi đọc được khung hợp lệ."""
        self._reconnect_budget = self._max_attempts


# --------------------------------------------------------------------------
# OpenCVSource — USB webcam / V4L2
# --------------------------------------------------------------------------


class OpenCVSource(_ReconnectableSource):
    """Camera USB (hoặc bất kỳ thiết bị V4L2) qua ``cv2.VideoCapture``.

    Trên Linux dùng ``cv2.CAP_V4L2`` để tránh backend GStreamer tự chọn; trên
    hệ điều hành khác dùng backend mặc định.
    """

    def __init__(
        self,
        index: int,
        width: int = 640,
        height: int = 480,
        max_attempts: int = OPEN_ATTEMPTS,
    ) -> None:
        super().__init__(max_attempts=max_attempts)
        self._index = int(index)
        self._width = int(width)
        self._height = int(height)
        self._cap: cv2.VideoCapture | None = None

        if not self._open():
            raise CameraError(
                f"Không mở được camera USB chỉ số {self._index} "
                f"({self._width}x{self._height}) sau {self._max_attempts} lần thử."
            )

    # -- nội bộ ---------------------------------------------------------

    def _source_label(self) -> str:
        return f"camera USB {self._index}"

    def _open_once(self) -> tuple[bool, BaseException | None]:
        if _is_linux():
            cap = cv2.VideoCapture(self._index, cv2.CAP_V4L2)
        else:
            cap = cv2.VideoCapture(self._index)

        if cap is not None and cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            # Giữ hàng đợi ngắn để độ trễ không tăng dần (spec §3).
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._cap = cap
            logger.info(
                "Đã mở camera USB %d (backend=%s, yêu cầu %dx%d).",
                self._index,
                self.backend,
                self._width,
                self._height,
            )
            return True, None

        if cap is not None:
            cap.release()
        self._cap = None
        return False, None

    def _release_capture(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001 - release lỗi không được làm crash
                logger.debug("Bỏ qua lỗi khi release camera.", exc_info=True)
            self._cap = None

    def _release_handle(self) -> None:
        self._release_capture()

    # -- giao diện FrameSource -----------------------------------------

    def read(self) -> np.ndarray | None:
        if self._closed:
            return None
        if self._cap is None and not self._reconnect():
            return None

        assert self._cap is not None
        ok, frame = self._cap.read()
        if ok and frame is not None and frame.size > 0:
            self._mark_frame_ok()
            return frame

        # Khung hỏng/mất kết nối: thử mở lại trong ngân sách cho phép.
        if self._reconnect() and self._cap is not None:
            ok, frame = self._cap.read()
            if ok and frame is not None and frame.size > 0:
                return frame

        logger.error(
            "Camera USB %d trả khung rỗng sau khi kết nối lại; bỏ khung này.",
            self._index,
        )
        return None

    def close(self) -> None:
        """Đóng thiết bị; trạng thái cuối, gọi nhiều lần không sao."""
        self._closed = True
        self._release_capture()

    @property
    def backend(self) -> str:
        return "opencv"

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log
        return f"OpenCVSource(index={self._index})"


# --------------------------------------------------------------------------
# RTSPSource — camera IP qua RTSP/FFmpeg
# --------------------------------------------------------------------------


class RTSPSource(_ReconnectableSource):
    """Camera IP qua RTSP, đọc bằng ``cv2.VideoCapture(url, cv2.CAP_FFMPEG)``.

    Ở chế độ đồng bộ, :meth:`read` xả cạn bộ đệm bằng ``grab()`` liên tiếp cho
    tới khi đuổi kịp luồng trực tiếp (một bước ``grab()`` vượt
    :data:`RTSP_DRAIN_STEP_LIMIT_S`) rồi mới ``retrieve()`` khung cuối. Ở chế độ
    ``prefetch=True``, luồng nền đọc liên tục và giữ khung mới nhất.

    Cờ FFmpeg được đặt qua :data:`FFMPEG_OPTIONS_ENV` ngay trước lệnh mở và khôi
    phục trong ``finally`` để không rò sang các ``VideoCapture`` khác.
    """

    def __init__(
        self,
        url: str,
        max_attempts: int = OPEN_ATTEMPTS,
        drain_step_limit_s: float = RTSP_DRAIN_STEP_LIMIT_S,
        max_drain_frames: int = RTSP_MAX_DRAIN_FRAMES,
        drain_time_limit_s: float = RTSP_DRAIN_TIME_LIMIT_S,
        prefetch: bool = False,
        prefetch_wait_s: float = RTSP_PREFETCH_FIRST_FRAME_S,
    ) -> None:
        super().__init__(max_attempts=max_attempts)
        self._url = str(url)
        self._drain_step_limit_s = float(drain_step_limit_s)
        self._max_drain_frames = max(1, int(max_drain_frames))
        self._drain_time_limit_s = float(drain_time_limit_s)
        self._cap: cv2.VideoCapture | None = None
        #: Số khung đệm đã bỏ ở lần đọc gần nhất; chỉ để chẩn đoán.
        self._last_dropped = 0

        #: Bộ đọc nền. ``None`` = đọc đồng bộ như cũ.
        self._prefetch_wait_s = max(0.0, float(prefetch_wait_s))
        self._cond = threading.Condition()
        self._latest: np.ndarray | None = None
        self._latest_seq = 0
        self._consumer_seq = 0
        self._prefetch_stop = threading.Event()
        self._prefetch_thread: threading.Thread | None = None
        self._prefetch_error: str | None = None

        if not self._open():
            raise CameraError(
                f"Không mở được luồng RTSP {redact_camera_source(self._url)} "
                f"sau {self._max_attempts} lần thử."
            )

        if prefetch:
            self._start_prefetch()

    # -- nội bộ ---------------------------------------------------------

    def _source_label(self) -> str:
        return f"luồng RTSP {redact_camera_source(self._url)}"

    def _open_retry_hint(self) -> str:
        return (
            "Kiểm tra camera có bật RTSP và đúng luồng phụ (sub-stream) không."
        )

    def _open_with_ffmpeg_options(self) -> cv2.VideoCapture | None:
        """Mở URL với cờ FFmpeg, khôi phục biến môi trường ngay sau khi mở."""
        previous = os.environ.get(FFMPEG_OPTIONS_ENV)
        os.environ[FFMPEG_OPTIONS_ENV] = RTSP_FFMPEG_OPTIONS
        try:
            return cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        finally:
            if previous is None:
                os.environ.pop(FFMPEG_OPTIONS_ENV, None)
            else:
                os.environ[FFMPEG_OPTIONS_ENV] = previous

    def _open_once(self) -> tuple[bool, BaseException | None]:
        cap = self._open_with_ffmpeg_options()
        if cap is not None and cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._cap = cap
            logger.info(
                "Đã mở luồng RTSP %s (backend=%s).",
                redact_camera_source(self._url),
                self.backend,
            )
            return True, None

        if cap is not None:
            cap.release()
        self._cap = None
        return False, None

    def _release_capture(self) -> None:
        cap, self._cap = self._cap, None
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001 - release lỗi không được làm crash
                logger.debug("Bỏ qua lỗi khi release luồng RTSP.", exc_info=True)

    def _release_handle(self) -> None:
        self._release_capture()

    def _drain(self) -> tuple[bool, np.ndarray | None]:
        """Bỏ hết khung đệm rồi trả khung mới nhất."""
        cap = self._cap
        assert cap is not None
        self._last_dropped = 0

        if not cap.grab():
            return False, None

        deadline = _monotonic() + self._drain_time_limit_s
        while self._last_dropped + 1 < self._max_drain_frames:
            start = _monotonic()
            if not cap.grab():
                break
            self._last_dropped += 1
            if _monotonic() - start > self._drain_step_limit_s:
                break
            if _monotonic() > deadline:
                break

        ok, frame = cap.retrieve()
        if ok and frame is not None and frame.size > 0:
            return True, frame
        return False, None

    # -- bộ đọc nền ------------------------------------------------------

    def _start_prefetch(self) -> None:
        """Chạy vòng đọc camera ở luồng nền, giữ **một** khung mới nhất."""
        thread = threading.Thread(
            target=self._prefetch_loop,
            name="rtsp-prefetch",
            daemon=True,
        )
        self._prefetch_thread = thread
        thread.start()

        # Dùng ``time.monotonic`` thật, không dùng ``_monotonic`` mô phỏng.
        deadline = time.monotonic() + self._prefetch_wait_s
        with self._cond:
            while self._latest is None and not self._prefetch_stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.warning(
                        "Bộ đọc nền chưa có khung RTSP sau %.1f giây; vẫn "
                        "chạy tiếp và chờ khung đầu tiên.",
                        self._prefetch_wait_s,
                    )
                    break
                self._cond.wait(remaining)

    def _prefetch_loop(self) -> None:
        """Vòng đọc của luồng nền: đọc → ghi đè khung mới nhất → lặp."""
        while not self._prefetch_stop.is_set():
            try:
                if self._cap is None and not self._reconnect():
                    self._prefetch_error = "không mở lại được luồng RTSP"
                    self._prefetch_stop.wait(RTSP_PREFETCH_ERROR_BACKOFF_S)
                    continue

                assert self._cap is not None
                ok, frame = self._cap.read()
                if not ok or frame is None or frame.size == 0:
                    if self._reconnect() and self._cap is not None:
                        continue
                    self._prefetch_error = "luồng RTSP trả khung rỗng"
                    self._prefetch_stop.wait(RTSP_PREFETCH_ERROR_BACKOFF_S)
                    continue

                self._mark_frame_ok()
                self._prefetch_error = None
                with self._cond:
                    self._latest = frame
                    self._latest_seq += 1
                    self._cond.notify_all()
            except Exception as exc:  # noqa: BLE001 - luồng nền không được chết
                self._prefetch_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Bộ đọc nền RTSP lỗi: %s", self._prefetch_error)
                self._prefetch_stop.wait(RTSP_PREFETCH_ERROR_BACKOFF_S)

    def _read_prefetched(self) -> np.ndarray | None:
        """Trả khung **mới nhất chưa xử lý** từ bộ đọc nền."""
        with self._cond:
            if self._latest is None:
                return None
            target = self._consumer_seq + 1
            if self._latest_seq < target:
                self._cond.wait_for(
                    lambda: self._latest_seq >= target
                    or self._prefetch_stop.is_set(),
                    timeout=RTSP_PREFETCH_NEW_FRAME_S,
                )
            frame = self._latest
            self._consumer_seq = self._latest_seq
            return frame

    # -- giao diện FrameSource -----------------------------------------

    def read(self) -> np.ndarray | None:
        if self._closed:
            return None
        if self._prefetch_thread is not None:
            return self._read_prefetched()
        if self._cap is None and not self._reconnect():
            return None

        assert self._cap is not None
        ok, frame = self._drain()
        if ok and frame is not None and frame.size > 0:
            self._mark_frame_ok()
            return frame

        if self._reconnect() and self._cap is not None:
            ok, frame = self._drain()
            if ok and frame is not None and frame.size > 0:
                return frame

        logger.error(
            "Luồng RTSP %s trả khung rỗng sau khi kết nối lại; bỏ khung này.",
            redact_camera_source(self._url),
        )
        return None

    def close(self) -> None:
        """Đóng luồng; trạng thái cuối, gọi nhiều lần không sao."""
        self._closed = True
        self._prefetch_stop.set()
        with self._cond:
            self._cond.notify_all()
        thread = self._prefetch_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
            if thread.is_alive():
                logger.warning(
                    "Bộ đọc nền RTSP chưa dừng sau 1,0 giây; hoãn giải phóng "
                    "handle để không crash khi đang đọc."
                )
                return
        self._release_capture()

    @property
    def backend(self) -> str:
        return "rtsp"

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log
        return f"RTSPSource({redact_camera_source(self._url)!r})"


# --------------------------------------------------------------------------
# PiCameraSource — Pi Camera qua picamera2
# --------------------------------------------------------------------------


class PiCameraSource(_ReconnectableSource):
    """Pi Camera qua ``picamera2``.

    ``picamera2`` chỉ có trên Raspberry Pi OS (cài bằng apt), nên import nằm
    trong :meth:`_load_picamera2`. Phải cấu hình ``RGB888`` để nhận thứ tự byte
    ``[B, G, R]`` đúng quy ước BGR của :class:`FrameSource` (``BGR888`` của
    libcamera/picamera2 trả ``[R, G, B]`` và sẽ đảo kênh đỏ/xanh).
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        max_attempts: int = OPEN_ATTEMPTS,
    ) -> None:
        super().__init__(max_attempts=max_attempts)
        self._width = int(width)
        self._height = int(height)
        self._picam2 = None
        self._load_picamera2()

        if not self._open():
            raise CameraError(
                f"Không mở được Pi Camera ({self._width}x{self._height}) sau "
                f"{self._max_attempts} lần thử."
            )

    # -- nạp thư viện ---------------------------------------------------

    def _load_picamera2(self) -> None:
        """Import ``picamera2`` muộn; ném ``CameraError`` nếu không có."""
        try:
            from picamera2 import Picamera2  # noqa: PLC0415 - cố ý import muộn
        except ImportError as exc:
            raise CameraError(
                "Không import được picamera2. Trên Raspberry Pi OS hãy cài "
                "bằng apt: sudo apt install -y python3-picamera2, và tạo venv "
                "với --system-site-packages."
            ) from exc
        self._picamera2_cls = Picamera2

    # -- nội bộ ---------------------------------------------------------

    def _source_label(self) -> str:
        return "Pi Camera"

    def _open_once(self) -> tuple[bool, BaseException | None]:
        try:
            picam2 = self._picamera2_cls()
            config = picam2.create_video_configuration(
                main={
                    "size": (self._width, self._height),
                    # RGB888 -> byte [B, G, R] = đúng quy ước BGR của FrameSource.
                    "format": "RGB888",
                }
            )
            picam2.configure(config)
            picam2.start()
            self._picam2 = picam2
            logger.info(
                "Đã mở Pi Camera (%dx%d, backend=picamera).",
                self._width,
                self._height,
            )
            return True, None
        except Exception as exc:  # noqa: BLE001 - phần cứng có nhiều kiểu lỗi
            self._close_device()
            return False, exc

    def _close_device(self) -> None:
        picam2, self._picam2 = self._picam2, None
        if picam2 is None:
            return
        for action in ("stop", "close"):
            try:
                getattr(picam2, action)()
            except Exception:  # noqa: BLE001 - dọn dẹp, không được crash
                logger.debug("Bỏ qua lỗi khi gọi %s().", action, exc_info=True)

    def _release_handle(self) -> None:
        self._close_device()

    # -- giao diện FrameSource -----------------------------------------

    def read(self) -> np.ndarray | None:
        if self._closed:
            return None
        if self._picam2 is None and not self._reconnect():
            return None

        try:
            frame = self._picam2.capture_array("main")
            if frame is not None and frame.size > 0:
                self._mark_frame_ok()
                return frame
            logger.error("Pi Camera trả khung rỗng; bỏ khung này.")
        except Exception as exc:  # noqa: BLE001 - lỗi driver/camera
            logger.error("Đọc khung từ Pi Camera lỗi: %s", exc)
            if self._reconnect() and self._picam2 is not None:
                try:
                    frame = self._picam2.capture_array("main")
                    if frame is not None and frame.size > 0:
                        return frame
                except Exception as retry_exc:  # noqa: BLE001
                    logger.error(
                        "Đọc khung Pi Camera vẫn lỗi sau kết nối lại: %s",
                        retry_exc,
                    )
        return None

    def close(self) -> None:
        """Đóng camera; trạng thái cuối, gọi nhiều lần không sao."""
        self._closed = True
        self._close_device()

    @property
    def backend(self) -> str:
        return "picamera"

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log
        return f"PiCameraSource({self._width}x{self._height})"


# --------------------------------------------------------------------------
# FileSource — video file, lặp lại khi hết
# --------------------------------------------------------------------------


class FileSource(FrameSource):
    """Video file qua ``cv2.VideoCapture(path)``.

    Khi hết video thì quay lại khung đầu, phù hợp cho ``replay`` và test trên
    PC. Nếu file không mở được, ``__init__`` ném :class:`CameraError`.
    """

    def __init__(self, path: str | Path, loop: bool = True) -> None:
        self._path = Path(path)
        self._loop = loop
        self._cap = cv2.VideoCapture(str(self._path))
        if not self._cap.isOpened():
            self._cap.release()
            self._cap = None
            raise CameraError(
                f"Không mở được video '{self._path}'. Kiểm tra đường dẫn và "
                "định dạng file (mp4/avi/mkv)."
            )
        self._frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        logger.info(
            "Đã mở video '%s' (%d khung, loop=%s).",
            self._path,
            self._frame_count,
            self._loop,
        )

    def read(self) -> np.ndarray | None:
        if self._cap is None:
            return None

        ok, frame = self._cap.read()
        if ok and frame is not None and frame.size > 0:
            return frame

        if not self._loop:
            logger.info("Đã đọc hết video '%s'.", self._path)
            return None

        try:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        except Exception:  # noqa: BLE001
            logger.debug("Không tua lại được video.", exc_info=True)
        ok, frame = self._cap.read()
        if ok and frame is not None and frame.size > 0:
            return frame

        logger.error("Không đọc được khung nào từ video '%s'.", self._path)
        return None

    def close(self) -> None:
        cap, self._cap = self._cap, None
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                logger.debug("Bỏ qua lỗi khi release video.", exc_info=True)

    @property
    def backend(self) -> str:
        return "file"

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log
        return f"FileSource({str(self._path)!r})"


# --------------------------------------------------------------------------
# Phát hiện thiết bị quay hình
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceInfo:
    """Một node ``/dev/videoN`` và kết luận nó có phải camera không."""

    index: int
    driver_name: str
    card_name: str
    is_capture: bool


def _read_text(path: Path) -> str:
    """Đọc nội dung sysfs; trả chuỗi rỗng nếu không đọc được."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _driver_name_for(index: int) -> str:
    """Tên driver của node ``videoN`` (ví dụ ``uvcvideo``)."""
    node_dir = SYSFS_VIDEO4LINUX / f"video{index}"
    driver_link = node_dir / "device" / "driver"
    try:
        return os.path.basename(os.readlink(driver_link))
    except OSError:
        return ""


def _is_excluded(driver_name: str, card_name: str) -> bool:
    """Node có thuộc nhóm codec/ISP của SoC không."""
    haystack = f"{driver_name} {card_name}".lower()
    return any(marker in haystack for marker in EXCLUDED_DRIVERS)


def _usb_nodes() -> list[int]:
    """Danh sách chỉ số các node ``/dev/videoN`` hiện có, sắp tăng dần."""
    if not DEV_DIR.is_dir():
        return []

    indices: list[int] = []
    pattern = re.compile(r"^video(\d+)$")
    try:
        entries = list(DEV_DIR.iterdir())
    except OSError:
        return []

    for entry in entries:
        match = pattern.match(entry.name)
        if match:
            indices.append(int(match.group(1)))
    return sorted(indices)


def _cv_log_levels():
    """Trả ``(module, current, silent, normal)`` của ``cv2.utils.logging``."""
    module = getattr(getattr(cv2, "utils", None), "logging", None)
    if module is None:
        return None, None, None, None
    silent = getattr(module, "LOG_LEVEL_SILENT", None)
    normal = getattr(module, "LOG_LEVEL_WARNING", None)
    if silent is None or normal is None:
        return None, None, None, None
    try:
        current = module.getLogLevel()
    except Exception:  # noqa: BLE001
        current = None
    return module, current, silent, normal


def _can_open_capture(index: int) -> bool:
    """Kiểm tra nhanh node có mở được như thiết bị capture không."""
    module, original_level, silent, normal = _cv_log_levels()

    cap = None
    try:
        if module is not None:
            try:
                module.setLogLevel(silent)
            except Exception:  # noqa: BLE001
                module = None
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2 if _is_linux() else 0)
        return bool(cap is not None and cap.isOpened())
    except Exception:  # noqa: BLE001 - dò thiết bị không được làm crash
        return False
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass
        if module is not None:
            try:
                module.setLogLevel(
                    original_level if original_level is not None else normal
                )
            except Exception:  # noqa: BLE001
                pass


def list_capture_devices(probe_opencv: bool = True) -> list[DeviceInfo]:
    """Liệt kê các node ``/dev/videoN`` và đánh dấu node nào là camera thật."""
    devices: list[DeviceInfo] = []
    for index in _usb_nodes():
        card_name = _read_text(SYSFS_VIDEO4LINUX / f"video{index}" / "name")
        driver_name = _driver_name_for(index)
        if _is_excluded(driver_name, card_name):
            devices.append(
                DeviceInfo(index, driver_name or card_name, card_name, False)
            )
            continue

        is_capture = _can_open_capture(index) if probe_opencv else True
        devices.append(
            DeviceInfo(index, driver_name or card_name, card_name, is_capture)
        )
    return devices


def _opencv_only_devices() -> list[DeviceInfo]:
    """Dò camera bằng cách thử mở chỉ số trên hệ điều hành không có sysfs."""
    devices: list[DeviceInfo] = []
    for index in range(MAX_ENUM_INDEX):
        if _can_open_capture(index):
            devices.append(
                DeviceInfo(
                    index=index,
                    driver_name="opencv",
                    card_name=f"camera chỉ số {index}",
                    is_capture=True,
                )
            )
    return devices


def _probe_picamera() -> dict[str, object]:
    """Kiểm tra Pi Camera; không bao giờ raise."""
    if not _is_linux():
        return {
            "available": False,
            "reason": "không phải Linux (không có /dev/vchiq)",
        }
    if not VCHIQ_DEVICE.exists():
        return {"available": False, "reason": "không có /dev/vchiq"}

    try:
        from picamera2 import Picamera2  # noqa: PLC0415 - cố ý import muộn
    except ImportError as exc:
        return {
            "available": False,
            "reason": f"không import được picamera2 ({exc})",
        }

    try:
        cameras = Picamera2.global_camera_info()
    except Exception as exc:  # noqa: BLE001 - lỗi driver không được làm crash
        return {
            "available": False,
            "reason": f"picamera2 lỗi khi liệt kê camera ({exc})",
        }

    if not cameras:
        return {
            "available": False,
            "reason": "picamera2 không thấy camera nào (kiểm tra cáp CSI và "
            "camera_auto_detect trong /boot/firmware/config.txt)",
        }
    return {"available": True, "reason": f"thấy {len(cameras)} camera CSI"}


def probe_cameras() -> dict[str, object]:
    """Dò mọi nguồn ảnh khả dụng, không raise khi thiếu phần cứng."""
    devices = list_capture_devices(probe_opencv=True)
    if not devices and not _is_linux():
        devices = _opencv_only_devices()

    usb = [
        {
            "index": device.index,
            "name": device.card_name or device.driver_name or "unknown",
            "available": device.is_capture,
        }
        for device in devices
        if not _is_excluded(device.driver_name, device.card_name)
    ]
    return {"picamera": _probe_picamera(), "usb": usb}


# --------------------------------------------------------------------------
# Tạo nguồn từ cấu hình
# --------------------------------------------------------------------------


def capture_from_config(config) -> FrameSource | None:
    """Mở nguồn ảnh theo ``config.camera.source``.

    Không raise khi thiếu thiết bị: ghi log WARNING/ERROR kèm lý do cụ thể và
    trả ``None`` để tầng trên chạy tiếp bằng chế độ không camera (spec §11.4).
    """
    camera = config.camera
    source = camera.source
    kind, value = parse_camera_source(source)

    if kind == "file":
        path = Path(str(value))
        if not path.is_file():
            logger.error(
                "Nguồn ảnh 'file:%s' không tồn tại; không mở được camera.",
                value,
            )
            return None
        try:
            return FileSource(path)
        except CameraError as exc:
            logger.error("Không mở được video '%s': %s", path, exc)
            return None

    if kind == "picamera":
        try:
            return PiCameraSource(camera.width, camera.height)
        except CameraError as exc:
            logger.warning(
                "Không mở được Pi Camera (%s). Chạy 'python scripts/"
                "camera_probe.py' để kiểm tra phần cứng.",
                exc,
            )
            return None

    if kind == "usb":
        try:
            return OpenCVSource(int(value), camera.width, camera.height)
        except CameraError as exc:
            logger.warning(
                "Không mở được camera USB %s (%s). Chạy 'python scripts/"
                "camera_probe.py' để kiểm tra phần cứng.",
                value,
                exc,
            )
            return None

    if kind == "rtsp":
        url = str(value)
        try:
            return RTSPSource(url, prefetch=True)
        except CameraError as exc:
            logger.warning(
                "Không mở được camera IP %s (%s). Kiểm tra camera đã bật "
                "RTSP, đúng địa chỉ/cổng và đúng luồng phụ (sub-stream).",
                redact_camera_source(url),
                exc,
            )
            return None

    logger.error("Loại nguồn ảnh không hỗ trợ: %s", redact_camera_source(source))
    return None
