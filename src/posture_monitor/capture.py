"""Nguồn ảnh (camera) và phát hiện thiết bị quay hình.

Thiết kế theo spec v2 §5.1:

- Ba triển khai :class:`FrameSource`: ``OpenCVSource`` (USB webcam / V4L2),
  ``PiCameraSource`` (Pi Camera qua picamera2) và ``FileSource`` (video file,
  dùng cho ``replay`` và test trên PC).
- Không crash khi thiếu camera: mọi lỗi mở thiết bị được ghi log và trả
  ``None`` ở tầng :func:`capture_from_config`.
- Tự kết nối lại tối đa :data:`OPEN_ATTEMPTS` lần kèm backoff khi mất kết nối
  giữa chừng, sau đó báo lỗi rõ ràng.

Lưu ý phần cứng Pi 4: các node ``/dev/video10..31`` là thiết bị codec/ISP của
SoC (``bcm2835-codec``, ``bcm2835-isp``, ``rpi-hevc-dec``), **không phải**
camera. Chúng thường vẫn ``isOpened()`` được qua OpenCV, nên phải loại theo
tên driver đọc từ sysfs trước, rồi mới thử mở.
"""

from __future__ import annotations

import os
import re
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import parse_camera_source
from .logging_setup import get_logger

logger = get_logger(__name__)

#: Số lần thử mở (hoặc mở lại) một nguồn trước khi bỏ cuộc.
OPEN_ATTEMPTS = 3

#: Thời gian chờ giữa các lần thử, tính bằng giây (backoff tăng dần).
BACKOFF_SCHEDULE = (0.2, 0.5, 1.0)

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
# Giao diện chung
# --------------------------------------------------------------------------


class FrameSource(ABC):
    """Nguồn ảnh trả về khung BGR.

    Hợp đồng:

    - :meth:`read` trả ``numpy.ndarray`` kiểu ``uint8``, hoặc ``None`` khi
      không còn khung / không kết nối lại được. Không raise trong vòng lặp
      đọc bình thường.
    - :meth:`close` giải phóng tài nguyên, gọi được nhiều lần.
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
        """Tên backend: ``opencv``, ``picamera`` hoặc ``file``."""

    # Cho phép dùng trong ``with`` để bảo đảm giải phóng tài nguyên.
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


# --------------------------------------------------------------------------
# OpenCVSource — USB webcam / V4L2
# --------------------------------------------------------------------------


class OpenCVSource(FrameSource):
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
        self._index = int(index)
        self._width = int(width)
        self._height = int(height)
        self._max_attempts = max(1, int(max_attempts))
        self._cap: cv2.VideoCapture | None = None
        #: Số lần mở lại còn lại sau khi mất kết nối giữa chừng. Đặt lại khi
        #: đọc được khung, để lần mất kết nối sau lại có đủ ngân sách.
        self._reconnect_budget = self._max_attempts
        self._gave_up = False

        if not self._open():
            raise CameraError(
                f"Không mở được camera USB chỉ số {self._index} "
                f"({self._width}x{self._height}) sau {self._max_attempts} lần thử."
            )

    # -- nội bộ ---------------------------------------------------------

    def _open(self, attempts: int | None = None) -> bool:
        """Thử mở thiết bị; trả ``True`` nếu thành công.

        Args:
            attempts: số lần thử trong lần gọi này; mặc định dùng
                ``self._max_attempts``. Khi gọi từ :meth:`_reconnect`, truyền
                ``1`` để mỗi đơn vị ngân sách tương ứng đúng một lần mở.
        """
        total = self._max_attempts if attempts is None else max(1, attempts)
        cap: cv2.VideoCapture | None = None
        for attempt in range(1, total + 1):
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
                return True

            if cap is not None:
                cap.release()
            if attempt < total:
                delay = BACKOFF_SCHEDULE[
                    min(attempt - 1, len(BACKOFF_SCHEDULE) - 1)
                ]
                logger.warning(
                    "Mở camera USB %d thất bại (lần %d/%d), thử lại sau %.1f giây.",
                    self._index,
                    attempt,
                    total,
                    delay,
                )
                _sleep(delay)
        self._cap = None
        return False

    def _reconnect(self) -> bool:
        """Giải phóng handle cũ rồi mở lại, tối đa ``_reconnect_budget`` lần.

        Ngân sách bị trừ mỗi lần gọi; hết ngân sách thì báo lỗi rõ một lần và
        từ đó ``read()`` trả ``None`` ngay, không thử vô hạn (spec §5.1).
        """
        if self._gave_up:
            return False
        if self._reconnect_budget <= 0:
            self._gave_up = True
            logger.error(
                "Camera USB %d đã hết %d lần kết nối lại; dừng đọc khung.",
                self._index,
                self._max_attempts,
            )
            return False

        self._reconnect_budget -= 1
        self._release_capture()
        logger.warning(
            "Mất kết nối camera USB %d, đang kết nối lại (còn %d lần)...",
            self._index,
            self._reconnect_budget + 1,
        )
        opened = self._open(attempts=1)
        if opened:
            # Mở được thì cấp lại ngân sách cho lần mất kết nối sau.
            self._reconnect_budget = self._max_attempts
        return opened

    def _release_capture(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001 - release lỗi không được làm crash
                logger.debug("Bỏ qua lỗi khi release camera.", exc_info=True)
            self._cap = None

    # -- giao diện FrameSource -----------------------------------------

    def read(self) -> np.ndarray | None:
        if self._cap is None and not self._reconnect():
            return None

        assert self._cap is not None
        ok, frame = self._cap.read()
        if ok and frame is not None and frame.size > 0:
            self._reconnect_budget = self._max_attempts
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
        self._release_capture()

    @property
    def backend(self) -> str:
        return "opencv"

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log
        return f"OpenCVSource(index={self._index})"


# --------------------------------------------------------------------------
# PiCameraSource — Pi Camera qua picamera2
# --------------------------------------------------------------------------


class PiCameraSource(FrameSource):
    """Pi Camera qua ``picamera2``.

    ``picamera2`` chỉ có trên Raspberry Pi OS (cài bằng apt), nên import nằm
    trong ``__init__`` và được bọc ``try/except``.

    **Bẫy đặt tên format:** tên format của picamera2 (lấy từ libcamera) ngược
    với thứ tự byte thật trong bộ nhớ. Theo picamera2 manual RP-008156-DS-7
    (Appendix A, "Pixel and image formats" — bản manual này mô tả đúng
    picamera2 0.3.37 đang dùng trên máy đích):

    - ``BGR888`` → byte là ``[R, G, B]``
    - ``RGB888`` → byte là ``[B, G, R]``

    Vì :meth:`FrameSource.read` quy ước trả khung **BGR** (giống OpenCV và
    :class:`OpenCVSource`/:class:`FileSource`), phải chọn ``RGB888`` — chọn
    ``BGR888`` sẽ làm khung bị đảo kênh đỏ/xanh **một cách âm thầm**.

    Mức bằng chứng (ghi rõ để người đọc sau không hiểu nhầm):

    1. Đo trên Pi ngày 28/10/2026 — round-trip simplejpeg: encode mảng có pixel
       đỏ với ``colorspace="RGB"`` rồi ``cv2.imdecode(..., IMREAD_COLOR)`` cho
       ra BGR ``[0, 0, 250]``; với ``colorspace="BGR"`` cho ``[255, 0, 23]``.
       Tức nhãn colorspace chính là thứ tự byte trong bộ nhớ.
    2. Đọc từ source đã cài — ``FORMAT_TABLE`` trong ``picamera2/request.py``
       ánh xạ ``"BGR888"`` → ``"RGB"`` khi đưa cho simplejpeg.
    3. Đọc từ tài liệu chính thức — Appendix A của manual nói trên.

    Lưu ý: pipeline **không có** chỗ nào gọi ``cv2.cvtColor``, nên không có
    đường chuyển màu dự phòng; tên format sai là sai màu luôn.

    **Chưa** xác nhận bằng camera thật (Pi chưa gắn camera nào).
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        max_attempts: int = OPEN_ATTEMPTS,
    ) -> None:
        self._width = int(width)
        self._height = int(height)
        self._max_attempts = max(1, int(max_attempts))
        self._picam2 = None
        #: Ngân sách mở lại sau khi mất kết nối giữa chừng (xem OpenCVSource).
        self._reconnect_budget = self._max_attempts
        self._gave_up = False
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

    def _open(self, attempts: int | None = None) -> bool:
        """Mở Pi Camera; ``attempts`` mặc định là ``self._max_attempts``."""
        total = self._max_attempts if attempts is None else max(1, attempts)
        for attempt in range(1, total + 1):
            try:
                picam2 = self._picamera2_cls()
                config = picam2.create_video_configuration(
                    main={
                        "size": (self._width, self._height),
                        # RGB888 -> byte [B, G, R] = đúng quy ước BGR của
                        # FrameSource. KHÔNG đổi sang BGR888: tên đó cho
                        # [R, G, B] và sẽ đảo kênh đỏ/xanh (xem docstring lớp).
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
                return True
            except Exception as exc:  # noqa: BLE001 - phần cứng có nhiều kiểu lỗi
                self._close_device()
                if attempt < total:
                    delay = BACKOFF_SCHEDULE[
                        min(attempt - 1, len(BACKOFF_SCHEDULE) - 1)
                    ]
                    logger.warning(
                        "Mở Pi Camera thất bại (lần %d/%d): %s; thử lại sau "
                        "%.1f giây.",
                        attempt,
                        total,
                        exc,
                        delay,
                    )
                    _sleep(delay)
                else:
                    logger.error(
                        "Mở Pi Camera thất bại sau %d lần: %s", total, exc
                    )
        return False

    def _close_device(self) -> None:
        picam2, self._picam2 = self._picam2, None
        if picam2 is None:
            return
        for action in ("stop", "close"):
            try:
                getattr(picam2, action)()
            except Exception:  # noqa: BLE001 - dọn dẹp, không được crash
                logger.debug("Bỏ qua lỗi khi gọi %s().", action, exc_info=True)

    def _reconnect(self) -> bool:
        """Mở lại sau khi mất kết nối, trong ngân sách có hạn (spec §5.1)."""
        if self._gave_up:
            return False
        if self._reconnect_budget <= 0:
            self._gave_up = True
            logger.error(
                "Pi Camera đã hết %d lần kết nối lại; dừng đọc khung.",
                self._max_attempts,
            )
            return False

        self._reconnect_budget -= 1
        self._close_device()
        logger.warning(
            "Mất kết nối Pi Camera, đang kết nối lại (còn %d lần)...",
            self._reconnect_budget + 1,
        )
        opened = self._open(attempts=1)
        if opened:
            self._reconnect_budget = self._max_attempts
        return opened

    # -- giao diện FrameSource -----------------------------------------

    def read(self) -> np.ndarray | None:
        if self._picam2 is None and not self._reconnect():
            return None

        try:
            frame = self._picam2.capture_array("main")
            if frame is not None and frame.size > 0:
                self._reconnect_budget = self._max_attempts
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

        # Hết video: tua về đầu và đọc lại một lần.
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
    """Tên driver của node ``videoN`` (ví dụ ``uvcvideo``).

    Sysfs đặt liên kết ``<node>/device/driver``; nếu không có (một số node
    ảo) thì trả chuỗi rỗng.
    """
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
    """Trả ``(module, current, silent, normal)`` của ``cv2.utils.logging``.

    Trả ``(None, None, None, None)`` nếu bản OpenCV không có API này (các bản
    cũ hoặc bản build tối giản).
    """
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
    """Kiểm tra nhanh node có mở được như thiết bị capture không.

    Đây chỉ là kiểm tra phụ: node codec/ISP cũng mở được, nên kết luận chính
    vẫn dựa trên tên driver (xem :func:`_is_excluded`).

    Log lỗi của OpenCV được tạm tắt trong lúc dò, vì dò các chỉ số không tồn
    tại sinh ra hàng loạt dòng ``Camera index out of range`` gây nhiễu; mức
    log cũ được khôi phục sau đó.
    """
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
                module.setLogLevel(original_level if original_level is not None else normal)
            except Exception:  # noqa: BLE001
                pass


def list_capture_devices(probe_opencv: bool = True) -> list[DeviceInfo]:
    """Liệt kê các node ``/dev/videoN`` và đánh dấu node nào là camera thật.

    Args:
        probe_opencv: nếu ``True``, thử mở từng node không bị loại bằng tên
            driver để kiểm tra thêm. Trên Pi, việc này làm bước dò chậm hơn vì
            mỗi node phải được mở và đóng.

    Returns:
        Danh sách :class:`DeviceInfo` sắp theo chỉ số. Trên hệ điều hành không
        phải Linux, trả danh sách rỗng (không có ``/dev/video*``).
    """
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
    """Dò camera bằng cách thử mở chỉ số trên hệ điều hành không có sysfs.

    Dùng cho Windows/macOS, nơi không có ``/dev/video*`` và không đọc được tên
    driver. Chỉ số mở được coi là camera (không có node codec của SoC để loại).
    """
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
    """Dò mọi nguồn ảnh khả dụng, không raise khi thiếu phần cứng.

    Returns:
        ``{"picamera": {"available": bool, "reason": str},
        "usb": [{"index": int, "name": str, "available": bool}, ...]}``.
        Danh sách ``usb`` rỗng nghĩa là không có node capture nào.
    """
    devices = list_capture_devices(probe_opencv=True)
    if not devices and not _is_linux():
        # Windows/macOS không có sysfs: dò bằng cách thử mở chỉ số.
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

    # parse_camera_source đã chặn loại lạ; đây chỉ là lưới an toàn.
    logger.error("Loại nguồn ảnh không hỗ trợ: %r", source)
    return None
