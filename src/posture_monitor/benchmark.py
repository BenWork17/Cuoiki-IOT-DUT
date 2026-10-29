"""Đo hiệu năng trên **chính máy đang chạy** (spec v2 §8, §10 mốc M5, §11.6).

Spec §11.6 cấm lấy số FPS/độ trễ/nhiệt/RAM từ tài liệu hay ngoại suy từ máy
khác: mọi chỉ số hiệu năng phải do module này sinh ra trên máy đích. Vì vậy
module **không** chứa số liệu mẫu, không có giá trị mặc định "trông đẹp", và
mọi thứ không đo được đều ghi ``null`` kèm lý do cụ thể.

Chuỗi khâu được đo đúng theo yêu cầu M5::

    capture → pose.detect → features.extract → classifier.classify → state.update

Không gồm làm mượt (``Smoother``) và vẽ overlay — báo cáo ghi rõ điểm này để
không ai đọc số ra rồi tưởng đó là toàn bộ ứng dụng.

Hồ sơ đo (``--profile``)
------------------------
Spec §14 bước G yêu cầu đo **ba cấu hình** khác nhau. ``--profile`` chọn đúng
cấu hình đó:

===============  ===================================================
``pose``         chỉ model tư thế (mặc định, hành vi cũ giữ nguyên)
``pose_phone``   thêm model detect COCO cho điện thoại, cách khung
``pose_phone_face``  thêm cả đường ống khuôn mặt, cách ``face.interval_s``
===============  ===================================================

**Không bao giờ âm thầm rơi về một hồ sơ khác.** Hồ sơ cần module hoặc khối
cấu hình mà bản này chưa có sẽ bị từ chối bằng thông điệp tiếng Việt và mã
thoát khác 0. Một bài đo in "6 FPS" trong khi thực chất chỉ chạy pose là đúng
loại lỗi mà cơ chế này tồn tại để chặn.

Báo cáo luôn ghi ``"profile"`` và ``"models"`` (mỗi model một mục, kèm vai trò
và nhịp chạy) để người đọc không thể hiểu nhầm bài đo gồm những model nào.
Các khóa mới chỉ được **thêm**, không đổi tên khóa cũ.

Bốn nhóm số liệu:

1. **Thời gian**: từng khâu và toàn khung, đơn vị ms, báo ``min``/``median``/
   ``p95``/``max``. FPS suy ra từ **median thời gian toàn khung**, nên nó là
   *FPS pipeline đầy đủ*, không phải FPS suy luận thuần. Nếu lấy được
   ``preprocess/inference/postprocess`` do ultralytics tự đo thì báo riêng;
   không lấy được thì ghi ``null``, không ước lượng.
2. **Nhiệt độ CPU** và **throttle**: lấy mẫu mỗi :data:`SAMPLE_INTERVAL_S`
   giây bằng ``vcgencmd``. Thiếu ``vcgencmd`` (PC) → ``null`` + lý do.
3. **RAM**: RSS đầu/cuối/đỉnh qua ``psutil``; thiếu ``psutil`` → ``null``.
4. **Nguồn dữ liệu**: ``camera``, ``video``, ``image`` hay ``synthetic``. Ảnh
   tĩnh lặp lại là nguồn hợp lệ (Pi của dự án chưa có camera) nhưng báo cáo
   phải nói rõ **không phải FPS camera thật**.

Ngưỡng so sánh lấy nguyên từ bảng §8 (FPS ≥ 5, nhiệt < 80 °C, RAM < 1 GB,
không bit throttle). Đây là tiêu chí nghiệm thu của bài đo, không phải ngưỡng
nghiệp vụ của tư thế — ngưỡng nghiệp vụ nằm trong ``config.yaml``.

Cấu trúc dict trả về (ổn định để CLI/tầng khác đọc; ``null`` = không đo được)::

    {
      "report_version": int,
      "profile": str, "models": [{"name", "role", "cadence", ...}],
      "generated_at": str, "duration_s": float,
      "host": {"platform", "machine", "python", "cpu", "cpu_count",
               "is_raspberry_pi"},
      "source": {"spec", "kind", "backend", "is_static", "note"},
      "model": {"name", "format", "backend", "imgsz"},
      "baseline": {"loaded", "path", "note"},
      "frames": {"measured", "with_person", "errors"},
      "timing_ms": {"pipeline_total": Stat, "capture": Stat,
                    "pose_detect": Stat, "features": Stat,
                    "classify": Stat, "state_update": Stat,
                    "pose_preprocess": Stat, "pose_inference": Stat,
                    "pose_postprocess": Stat},
      "fps": {"pipeline_median": float|null, "note": str,
              "valid": bool, "throttle_checked": bool},
      "temperature_c": {"min", "median", "max", "samples", "available",
                        "reason"},
      "memory_mb": {"start", "end", "peak", "available", "reason"},
      "throttle": {"final", "any_set", "invalidates_fps", "flags",
                   "samples", "available", "reason"},
      "criteria": [{"key", "label", "target", "measured", "pass", "note"}],
      "notices": [str], "warnings": [str]
    }

``Stat`` là ``{"count", "min", "median", "p95", "max", "mean"}`` hoặc ``None``.

Chạy trực tiếp::

    python -m posture_monitor.benchmark --seconds 60 \\
        --config config.yaml [--profile pose|pose_phone|pose_phone_face] \\
        [--source file:anh.jpg] [--json out.json] [--no-gpio]

Mã thoát: 0 khi đo xong (kể cả không đạt chỉ tiêu), khác 0 khi không đo được
(không mở được nguồn, thiếu model). Mọi lỗi môi trường đều được bắt và báo
bằng thông điệp tiếng Việt, không để traceback làm sập bài đo (spec §11.4).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np

from .calibration import CalibrationError, Baseline
from .calibration import load as load_calibration
from .capture import CameraError, FrameSource, capture_from_config
from .classifier import classify
from .config import (
    Config,
    ConfigError,
    load_config,
    parse_camera_source,
    redact_camera_source,
)
from .features import ALL_NAMES, extract
from .logging_setup import get_logger, setup_logging
from .pose import PoseError, PoseEstimator
from .state import StateMachine

try:  # psutil nằm trong requirements.txt nhưng Pi có thể thiếu vì cài tay.
    import psutil
except Exception:  # noqa: BLE001 - thiếu psutil không được làm sập bài đo
    psutil = None  # type: ignore[assignment]

logger = get_logger(__name__)

#: Phiên bản cấu trúc báo cáo; tăng khi đổi schema để tầng đọc biết.
REPORT_VERSION = 1

# ---------------------------------------------------------------------------
# Hằng số kỹ thuật của bài đo (không phải ngưỡng nghiệp vụ)
# ---------------------------------------------------------------------------

#: Nhịp lấy mẫu nhiệt/throttle, tính bằng giây. Spec §8 yêu cầu lấy mẫu mỗi
#: 5 giây trong suốt bài đo; đây là hằng số kỹ thuật, không đọc từ config.
SAMPLE_INTERVAL_S = 5.0

#: Số khung chạy "khởi động" bị loại khỏi thống kê. Lần suy luận đầu tiên của
#: ultralytics nạp bộ nhớ đệm và chậm hơn hẳn (trên PC đo được ~1,1 s so với
#: ~60 ms), để nguyên sẽ làm hỏng ``max`` và ``p95``.
WARMUP_FRAMES = 5

#: Cứ ngần này khung lấy mẫu RAM một lần. Lấy mỗi khung thì chính phép đo làm
#: chậm vòng lặp; ``psutil`` không rẻ trên Pi.
MEMORY_EVERY_FRAMES = 10

#: Số lỗi khung tối đa còn chấp nhận trước khi dừng bài đo (báo cáo một phần).
MAX_FRAME_ERRORS = 10

#: Số byte trong 1 MiB. Báo cáo dùng MiB cho khớp cách ``free -m`` của Pi.
BYTES_PER_MIB = 1024 * 1024

#: Tiêu chí nghiệm thu §8. Đây là ngưỡng của **bài đo**, lấy nguyên văn spec.
MIN_FPS = 5.0
MAX_TEMP_C = 80.0
MAX_RAM_MB = 1024.0

#: Bit throttle khiến số FPS đo được không hợp lệ (spec §8): ``0x4`` = đang bị
#: bóp hiệu năng, ``0x40000`` = đã từng bị bóp trong phiên.
THROTTLE_ACTIVE = 0x4
THROTTLE_ACTIVE_OCCURRED = 0x40000

#: Ý nghĩa từng bit của ``vcgencmd get_throttled`` (spec §8).
THROTTLE_BITS = (
    (0x1, "under-voltage (đang thiếu áp)"),
    (0x2, "freq capped (đang bị hạ xung)"),
    (0x4, "đang throttle (đang bị bóp hiệu năng)"),
    (0x10000, "đã từng xảy ra under-voltage"),
    (0x20000, "đã từng xảy ra freq capped"),
    (0x40000, "đã từng xảy ra throttle"),
)

#: Phần mở rộng được coi là ảnh tĩnh (nguồn lặp một khung).
IMAGE_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
)

#: Loại nguồn trong báo cáo, kèm câu mô tả trung thực cho từng loại.
SOURCE_KINDS = {
    "camera": "camera trực tiếp (USB hoặc Pi Camera)",
    "video": "video ghi sẵn, phát lặp lại",
    "image": "ảnh tĩnh lặp lại — KHÔNG phải FPS camera thật",
    "synthetic": "khung tổng hợp dùng cho kiểm thử — không phải camera",
}

_TEMP_RE = re.compile(r"temp=(-?\d+(?:\.\d+)?)")
_THROTTLE_RE = re.compile(r"throttled=(0x[0-9a-fA-F]+)")


# ---------------------------------------------------------------------------
# Hồ sơ đo (--profile): cấu hình nào chạy model nào
# ---------------------------------------------------------------------------

#: Hồ sơ mặc định — **giữ nguyên hành vi cũ tuyệt đối**: chỉ pose.
DEFAULT_PROFILE = "pose"

#: Mô tả từng hồ sơ, dùng cho ``--help``, thông điệp lỗi và báo cáo.
PROFILES: dict[str, str] = {
    "pose": "chỉ model tư thế (hành vi gốc của benchmark)",
    "pose_phone": "pose + model detect COCO cho điện thoại (cách khung)",
    "pose_phone_face": "pose + detect điện thoại + đường ống khuôn mặt",
}

#: Hồ sơ cần module ``phone_detector`` (nằm trên nhánh ``r3-phone``).
_PHONE_PROFILES = frozenset({"pose_phone", "pose_phone_face"})

#: Hồ sơ cần thêm đường ống khuôn mặt.
_FACE_PROFILES = frozenset({"pose_phone_face"})


def normalise_profile(profile: Any) -> str:
    """Kiểm tra tên hồ sơ; trả tên chuẩn hoá.

    ``None`` được hiểu là :data:`DEFAULT_PROFILE` (tiện cho tầng gọi cũ).

    Raises:
        BenchmarkError: tên hồ sơ không nằm trong :data:`PROFILES`. Sai tên
            phải **dừng**, không được lặng lẽ coi như ``pose`` — đo nhầm cấu
            hình rồi in số là đúng loại lỗi module này tồn tại để chặn.
    """
    if profile is None:
        return DEFAULT_PROFILE
    name = str(profile).strip()
    if name not in PROFILES:
        raise BenchmarkError(
            f"Hồ sơ đo --profile không hợp lệ: {name!r}. Chọn một trong "
            + ", ".join(f"'{key}' ({value})" for key, value in PROFILES.items())
            + "."
        )
    return name


class _ExtraModel:
    """Một model phụ chạy cạnh pose, kèm metadata cho báo cáo.

    ``step`` nhận ``(frame, pose, now)`` và trả ``None``; ngoại lệ bên trong
    được ghi cảnh báo và đếm, không được làm sập bài đo (spec §11.4).
    """

    def __init__(
        self,
        name: str,
        role: str,
        cadence: str,
        step: Callable[[Any, Any, float], None],
        meta: dict[str, Any],
    ) -> None:
        self.name = name
        self.role = role
        self.cadence = cadence
        self._step = step
        self.meta = meta
        #: Số khung lỗi riêng của model phụ (không cộng vào ``frames.errors``).
        self.errors = 0
        #: Thời gian từng lần chạy model phụ, ms — để báo cáo có bằng chứng.
        self.durations_ms: list[float] = []

    def step(self, frame: Any, pose: Any, now: float) -> None:
        start = time.perf_counter()
        try:
            self._step(frame, pose, now)
        except Exception as exc:  # noqa: BLE001 - model phụ không được sập
            self.errors += 1
            logger.warning(
                "Model phụ '%s' lỗi ở khung này: %s", self.name, exc
            )
            return
        self.durations_ms.append((time.perf_counter() - start) * 1000.0)

    def describe(self) -> dict[str, Any]:
        """Mục trong ``report["models"]`` — không chứa trọng số/mật khẩu."""
        entry: dict[str, Any] = {
            "name": self.name,
            "role": self.role,
            "cadence": self.cadence,
            "errors": self.errors,
            "timing_ms": _stats(self.durations_ms),
        }
        entry.update(self.meta)
        return entry


#: Thông điệp khi hồ sơ cần ``phone_detector`` mà bản này chưa có module.
PHONE_MISSING_MESSAGE = (
    "Hồ sơ đo cần model detect điện thoại, nhưng bản này KHÔNG có module "
    "'posture_monitor.phone_detector' (module nằm trên nhánh 'r3-phone'). "
    "Không đo thay bằng cấu hình khác: một bài đo in FPS của riêng pose mà "
    "dán nhãn 'pose_phone' là số liệu sai. Hãy merge nhánh 'r3-phone' (và khối "
    "cấu hình 'phone') rồi chạy lại; muốn đo ngay bây giờ thì dùng "
    "--profile pose và ghi rõ chỉ có pose."
)

#: Thông điệp khi hồ sơ cần đường ống khuôn mặt mà cấu hình chưa có.
FACE_MISSING_MESSAGE = (
    "Hồ sơ đo cần đường ống khuôn mặt, nhưng cấu hình này KHÔNG có khối "
    "'face' (hoặc khối đó đang tắt, hoặc thiếu tệp 'yunet.onnx'/'sface.onnx'). "
    "Không đo thay bằng cấu hình khác vì báo cáo sẽ mang nhãn sai. Hãy thêm "
    "khối 'face' theo spec §6 và đặt sẵn hai tệp ONNX, rồi chạy lại; muốn đo "
    "ngay bây giờ thì dùng --profile pose_phone hoặc --profile pose."
)


def _build_phone_extra(config: Config) -> _ExtraModel:
    """Dựng model phụ detect điện thoại từ ``config.phone``.

    Raises:
        BenchmarkError: thiếu module :mod:`posture_monitor.phone_detector`
            (nhánh ``r3-phone`` chưa merge) hoặc thiếu/tắt khối ``phone``.
            Từ chối rõ ràng thay vì đo nhầm cấu hình.
    """
    try:  # noqa: PLC0415 - import muộn: module chỉ cần khi chọn hồ sơ này
        from .phone_detector import PhoneSignal
    except ImportError as exc:
        raise BenchmarkError(PHONE_MISSING_MESSAGE) from exc

    phone_cfg = getattr(config, "phone", None)
    if phone_cfg is None:
        raise BenchmarkError(
            PHONE_MISSING_MESSAGE
            + " (Cấu hình đang nạp không có khối 'phone'.)"
        )
    if not bool(getattr(phone_cfg, "enabled", False)):
        raise BenchmarkError(
            "Hồ sơ đo cần model detect điện thoại nhưng 'phone.enabled' đang "
            "false, nên model đó sẽ không chạy. Không đo nhầm cấu hình: bật "
            "'phone.enabled: true' hoặc dùng --profile pose."
        )

    signal = PhoneSignal(config)
    every = int(getattr(phone_cfg, "detect_every_n_frames", 1) or 1)
    detect_model = str(getattr(phone_cfg, "detect_model", "yolo11n"))

    def step(frame: Any, pose: Any, now: float) -> None:
        if pose is None:
            # Không có keypoint thì PhoneSignal vẫn trả None; bỏ qua cho rẻ.
            return
        signal.observe(frame, _keypoints_array(pose), now)

    return _ExtraModel(
        name=detect_model,
        role="phone_detect",
        cadence=f"mỗi {every} khung",
        step=step,
        meta={
            "imgsz": int(getattr(phone_cfg, "imgsz", 320)),
            "format": config.model.format,
            "detect_every_n_frames": every,
        },
    )


def _build_face_extra(config: Config) -> _ExtraModel:
    """Dựng model phụ đường ống khuôn mặt từ ``config.face``.

    Raises:
        BenchmarkError: thiếu khối ``face``, khối đang tắt, hoặc thiếu tệp
            ``yunet.onnx``/``sface.onnx`` trên đĩa.
    """
    face_cfg = getattr(config, "face", None)
    if face_cfg is None or not bool(getattr(face_cfg, "enabled", False)):
        raise BenchmarkError(FACE_MISSING_MESSAGE)

    from .faces import FaceRecognizer  # noqa: PLC0415

    yunet = Path(str(getattr(face_cfg, "detector", "")))
    sface = Path(str(getattr(face_cfg, "recognizer", "")))
    missing = [str(path) for path in (yunet, sface) if not path.is_file()]
    if missing:
        raise BenchmarkError(
            FACE_MISSING_MESSAGE
            + " (Thiếu tệp: " + ", ".join(missing) + ".)"
        )

    detect_width = int(getattr(face_cfg, "detect_width", 320) or 320)
    recognizer = FaceRecognizer(
        yunet,
        sface,
        input_size=(detect_width, detect_width),
    )
    interval_s = float(getattr(face_cfg, "interval_s", 2.0) or 2.0)
    state: dict[str, Any] = {"next_at": 0.0}

    def step(frame: Any, pose: Any, now: float) -> None:
        # Chạy theo nhịp ``face.interval_s`` như vòng lặp thật; đo chi phí một
        # lượt là mục đích, nên chỉ cần kích hoạt đúng nhịp. Lỗi model (thiếu
        # OpenCV, ONNX hỏng) do ``_ExtraModel.step`` bắt và đếm — không được
        # làm sập khung pose.
        if now < state["next_at"]:
            return
        state["next_at"] = now + interval_s
        recognizer.embed_largest(frame)

    return _ExtraModel(
        name="yunet+sface",
        role="face",
        cadence=f"mỗi {interval_s:g} s",
        step=step,
        meta={
            "detect_width": detect_width,
            "format": "onnx",
            "interval_s": interval_s,
        },
    )


def _keypoints_array(pose: Any) -> Any:
    """Ghép ``xy``/``conf`` của :class:`PoseResult` thành ``(17, 3)``."""
    xy = getattr(pose, "xy", None)
    conf = getattr(pose, "conf", None)
    if xy is None or conf is None:
        return None
    return np.concatenate(
        [np.asarray(xy, dtype=float), np.asarray(conf, dtype=float)[:, None]],
        axis=1,
    )


def _build_extras(config: Config, profile: str) -> list[_ExtraModel]:
    """Dựng danh sách model phụ theo hồ sơ; từ chối nếu không dựng được.

    Khi nhiều model phụ cùng thiếu, báo **tất cả** lý do trong một lần chứ
    không chỉ cái đầu tiên: người sửa cần biết đủ việc phải làm (merge
    ``r3-phone``, thêm khối ``face``, tải hai tệp ONNX).
    """
    builders: list[tuple[bool, Callable[[Config], _ExtraModel]]] = [
        (profile in _PHONE_PROFILES, _build_phone_extra),
        (profile in _FACE_PROFILES, _build_face_extra),
    ]
    extras: list[_ExtraModel] = []
    problems: list[str] = []
    for needed, builder in builders:
        if not needed:
            continue
        try:
            extras.append(builder(config))
        except BenchmarkError as exc:
            problems.append(str(exc))
    if problems:
        raise BenchmarkError(
            problems[0]
            if len(problems) == 1
            else "Hồ sơ này chưa chạy được vì thiếu nhiều phần:\n- "
            + "\n- ".join(problems)
        )
    return extras



class BenchmarkError(RuntimeError):
    """Không thể đo (không mở được nguồn, thiếu model, sai tham số môi trường)."""


# ---------------------------------------------------------------------------
# Nguồn ảnh bổ sung: ảnh tĩnh và danh sách khung tổng hợp
# ---------------------------------------------------------------------------


class StaticImageSource(FrameSource):
    """Ảnh tĩnh lặp lại vô hạn.

    Dùng khi máy chưa có camera (Pi của dự án ở thời điểm M5): đo được chi phí
    suy luận + đặc trưng + phân loại trên khung thật, nhưng **không** đo được
    chi phí đọc cảm biến. Báo cáo ghi ``kind="image"`` để không ai đọc nhầm
    thành FPS camera.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._frame = cv2.imread(str(self._path))
        if self._frame is None:
            raise CameraError(
                f"Không đọc được ảnh tĩnh '{self._path}'. Kiểm tra đường dẫn "
                "và định dạng file."
            )
        logger.info(
            "Đã mở ảnh tĩnh '%s' (%dx%d); dùng lặp lại cho bài đo.",
            self._path,
            self._frame.shape[1],
            self._frame.shape[0],
        )

    def read(self) -> np.ndarray | None:
        return self._frame

    def close(self) -> None:
        self._frame = None  # type: ignore[assignment]

    @property
    def backend(self) -> str:
        return "image"

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log
        return f"StaticImageSource({str(self._path)!r})"


class FrameListSource(FrameSource):
    """Lặp vô hạn một danh sách khung ``numpy`` (dùng cho test trên PC).

    Nhờ nguồn này, ``run_benchmark`` kiểm thử được toàn bộ vòng đo mà không
    cần model thật, camera hay file video.
    """

    def __init__(self, frames: Sequence[np.ndarray]) -> None:
        if not frames:
            raise CameraError("Danh sách khung tổng hợp rỗng.")
        for index, frame in enumerate(frames):
            if not isinstance(frame, np.ndarray) or frame.size == 0:
                raise CameraError(
                    f"Khung tổng hợp thứ {index} không phải ảnh numpy hợp lệ."
                )
        self._frames = list(frames)
        self._index = 0

    def read(self) -> np.ndarray | None:
        if not self._frames:
            return None
        frame = self._frames[self._index % len(self._frames)]
        self._index += 1
        return frame

    def close(self) -> None:
        self._frames = []
        self._index = 0

    @property
    def backend(self) -> str:
        return "synthetic"


# ---------------------------------------------------------------------------
# Đọc lệnh hệ thống (vcgencmd) — thiếu lệnh là chuyện bình thường trên PC
# ---------------------------------------------------------------------------


class _Command:
    """Bọc một lệnh ngoài, nhớ luôn trạng thái "máy này không có lệnh".

    ``vcgencmd`` chỉ có trên Raspberry Pi OS. Trên PC, ``subprocess`` ném
    ``FileNotFoundError`` mỗi lần gọi; nhớ lại để không sinh lỗi lặp lại và
    để báo cáo nêu đúng lý do thay vì bịa số.
    """

    def __init__(self, *argv: str) -> None:
        self._argv = argv
        self._missing: str | None = None

    def run(self, timeout: float = 2.0) -> tuple[str | None, str | None]:
        """Chạy lệnh; trả ``(stdout, None)`` hoặc ``(None, lý do)``."""
        if self._missing is not None:
            return None, self._missing
        try:
            completed = subprocess.run(
                self._argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            self._missing = (
                f"Không có lệnh '{self._argv[0]}' trên máy này "
                "(chỉ Raspberry Pi OS mới có)."
            )
            return None, self._missing
        except (OSError, subprocess.SubprocessError) as exc:
            return None, f"Không chạy được '{' '.join(self._argv)}': {exc}"

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            return None, (
                f"'{' '.join(self._argv)}' thoát với mã {completed.returncode}"
                + (f": {detail}" if detail else "")
            )
        return completed.stdout.strip(), None


def _parse_temp(text: str | None) -> float | None:
    """Tách nhiệt độ từ ``temp=55.0'C``; ``None`` nếu không khớp."""
    if not text:
        return None
    match = _TEMP_RE.search(text)
    if match is None:
        return None
    value = float(match.group(1))
    return value if math.isfinite(value) else None


def _parse_throttled(text: str | None) -> int | None:
    """Tách số nguyên từ ``throttled=0x0``; ``None`` nếu không khớp."""
    if not text:
        return None
    match = _THROTTLE_RE.search(text)
    if match is None:
        return None
    try:
        return int(match.group(1), 16)
    except ValueError:  # pragma: no cover - regex đã chặn ký tự lạ
        return None


def _describe_throttle(value: int) -> dict[str, Any]:
    """Giải mã bitmask throttle thành cờ đọc được (bảng bitmask spec §8)."""
    flags = [
        {"bit": f"0x{bit:x}", "meaning": meaning}
        for bit, meaning in THROTTLE_BITS
        if value & bit
    ]
    return {
        "raw": f"0x{value:x}",
        "flags": flags,
        "any_set": value != 0,
        "invalidates_fps": bool(
            value & (THROTTLE_ACTIVE | THROTTLE_ACTIVE_OCCURRED)
        ),
    }


# ---------------------------------------------------------------------------
# Tiện ích thống kê / môi trường
# ---------------------------------------------------------------------------


def _stats(values: Sequence[float]) -> dict[str, float] | None:
    """Tính ``min/median/p95/max/mean``; ``None`` khi không có mẫu hợp lệ."""
    data = [
        float(value)
        for value in values
        if value is not None and math.isfinite(float(value))
    ]
    if not data:
        return None
    array = np.asarray(data, dtype=float)
    return {
        "count": int(array.size),
        "min": float(array.min()),
        "median": float(np.median(array)),
        "p95": float(np.percentile(array, 95)),
        "max": float(array.max()),
        "mean": float(array.mean()),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_text(path: Path) -> str:
    """Đọc file văn bản; trả chuỗi rỗng nếu không đọc được."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _cpu_model() -> str:
    """Tên CPU: ưu tiên ``/proc/cpuinfo`` (Linux), rồi ``platform.processor``."""
    cpuinfo = _read_text(Path("/proc/cpuinfo"))
    for line in cpuinfo.splitlines():
        if line.lower().startswith(("model name", "hardware", "model")):
            _, _, value = line.partition(":")
            value = value.strip()
            if value:
                return value
    return platform.processor() or "không rõ"


def _host_info() -> dict[str, Any]:
    """Thông tin máy đang chạy — bắt buộc để người đọc biết số đo từ đâu."""
    model = _read_text(Path("/proc/device-tree/model")).strip("\x00").strip()
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu": model or _cpu_model(),
        "cpu_count": _cpu_count(),
        "is_raspberry_pi": "raspberry pi" in model.lower(),
    }


def _cpu_count() -> int | None:
    try:
        return os.cpu_count()
    except Exception:  # noqa: BLE001 - chỉ là thông tin phụ
        return None


def _rss_mib() -> float | None:
    """RSS của tiến trình hiện tại, đơn vị MiB; ``None`` nếu thiếu psutil."""
    if psutil is None:
        return None
    try:
        return psutil.Process().memory_info().rss / BYTES_PER_MIB
    except Exception:  # noqa: BLE001 - quyền đọc / tiến trình đã thoát
        return None


# ---------------------------------------------------------------------------
# Mở nguồn ảnh
# ---------------------------------------------------------------------------


def _resolve_source(
    config: Config, source_override: Any
) -> tuple[FrameSource, dict[str, Any], bool]:
    """Mở nguồn ảnh và trả ``(nguồn, mô tả, có_phải_tự_đóng)``.

    ``source_override`` nhận:

    - ``None`` → dùng ``config.camera.source``;
    - chuỗi cú pháp ``usb:N`` / ``picamera`` / ``file:duong_dan`` (ảnh tĩnh
      được nhận diện theo phần mở rộng);
    - một :class:`FrameSource` đã mở sẵn;
    - danh sách khung ``numpy`` (hoặc một khung đơn) cho kiểm thử.

    Raises:
        BenchmarkError: khi không mở được nguồn, kèm lý do cụ thể.
    """
    # Trường hợp test: danh sách khung tổng hợp.
    if isinstance(source_override, np.ndarray):
        source = FrameListSource([source_override])
        return source, _source_meta(
            "synthetic", source, "một khung tổng hợp lặp lại"
        ), True
    if isinstance(source_override, (list, tuple)):
        try:
            source = FrameListSource(source_override)
        except CameraError as exc:
            raise BenchmarkError(str(exc)) from exc
        return source, _source_meta(
            "synthetic", source, f"{len(source_override)} khung tổng hợp lặp lại"
        ), True

    # Nguồn đã mở sẵn (test hoặc tầng khác truyền vào): không đóng hộ.
    if isinstance(source_override, FrameSource):
        return source_override, _source_meta(
            "camera", source_override, "nguồn do bên gọi truyền vào"
        ), False

    spec = config.camera.source if source_override is None else source_override
    if not isinstance(spec, str) or not spec.strip():
        # ``repr`` giữ nguyên định dạng cũ cho ``None``/chuỗi rỗng, rồi mới che:
        # đối tượng lạ vẫn có thể mang mật khẩu trong ``repr`` của nó.
        raise BenchmarkError(
            f"Nguồn ảnh không hợp lệ: {redact_camera_source(repr(spec))}. "
            "Dùng 'usb:N', 'picamera' hoặc 'file:duong_dan'."
        )
    spec = spec.strip()
    #: Bản đã che user/mật khẩu, dùng cho **mọi** thông điệp lỗi bên dưới.
    #: URL RTSP chứa mật khẩu thật; in ``spec`` trần ra màn hình là rò rỉ.
    safe_spec = redact_camera_source(spec)

    try:
        kind, value = parse_camera_source(spec)
    except ConfigError as exc:
        raise BenchmarkError(str(exc)) from exc

    if kind == "file":
        path = Path(str(value))
        if not path.is_file():
            raise BenchmarkError(
                f"Nguồn ảnh '{safe_spec}' không tồn tại: {path.resolve()}. "
                "Trên Pi chưa có camera, hãy trỏ tới ảnh tĩnh hoặc video có "
                "sẵn, ví dụ --source file:anh_mau.jpg."
            )
        if path.suffix.lower() in IMAGE_SUFFIXES:
            try:
                source = StaticImageSource(path)
            except CameraError as exc:
                raise BenchmarkError(str(exc)) from exc
            return source, _source_meta(
                "image", source, f"ảnh tĩnh '{path.name}' lặp lại"
            ), True

    # usb / picamera / video file: dùng lại đường mở đã kiểm thử của capture.
    patched = replace(config, camera=replace(config.camera, source=spec))
    try:
        source = capture_from_config(patched)
    except CameraError as exc:  # pragma: no cover - capture_from_config nuốt lỗi
        raise BenchmarkError(
            f"Không mở được nguồn '{safe_spec}': {exc}"
        ) from exc
    if source is None:
        raise BenchmarkError(
            f"Không mở được nguồn ảnh '{safe_spec}'. Xem log phía trên để biết "
            "lý do (thiếu thiết bị, sai đường dẫn, driver lỗi). Chạy "
            "'python scripts/camera_probe.py' để kiểm tra phần cứng."
        )
    report_kind = "video" if kind == "file" else "camera"
    return source, _source_meta(report_kind, source, spec), True


def _source_meta(
    kind: str, source: FrameSource, detail: str
) -> dict[str, Any]:
    """Mô tả nguồn ảnh theo cách không thể đọc nhầm thành camera thật.

    ``detail`` được che user/mật khẩu **trước khi** vào dict: báo cáo này vừa
    in ra màn hình (:func:`format_report`) vừa ghi thẳng ra file qua ``--json``,
    nên che ở đây là chỗ duy nhất bịt cả hai đường.
    """
    is_static = kind == "image"
    return {
        "spec": redact_camera_source(detail),
        "kind": kind,
        "backend": _safe_backend(source),
        "is_static": is_static,
        "note": SOURCE_KINDS.get(kind, kind),
    }


def _safe_backend(source: FrameSource) -> str:
    try:
        return str(source.backend)
    except Exception:  # noqa: BLE001 - backend chỉ là thông tin phụ
        return "không rõ"


# ---------------------------------------------------------------------------
# Thu thời gian từng khâu do ultralytics tự đo
# ---------------------------------------------------------------------------


class _StageTap:
    """Gom ``preprocess/inference/postprocess`` (ms) từ ``Results.speed``.

    ``PoseEstimator.detect`` không trả đối tượng ``Results`` thô, nên phải
    bám vào callback ``on_predict_batch_end`` của model. Đây là **thuộc tính
    riêng** của ``PoseEstimator``/ultralytics: nếu bản ultralytics đang dùng
    không có ``add_callback`` hoặc callback không được gọi, các khâu này để
    ``null`` — bài đo vẫn chạy, tuyệt đối không ước lượng thay.

    Chỉ giữ mẫu **gần nhất** và số lần đã nhận, không giữ cả danh sách: bài đo
    có thể chạy hàng giờ (tiêu chí ổn định §8) và giữ mọi mẫu sẽ tự làm tăng
    RAM của chính phép đo.
    """

    def __init__(self) -> None:
        self.latest: dict[str, float] | None = None
        self.count = 0

    def on_batch_end(self, predictor) -> None:  # pragma: no cover - do UL gọi
        results = getattr(predictor, "results", None) or []
        for result in results:
            speed = getattr(result, "speed", None)
            if isinstance(speed, dict):
                self.latest = dict(speed)
                self.count += 1

    def attach(self, estimator) -> bool:
        """Gắn callback vào model; trả ``True`` nếu gắn được."""
        model = getattr(estimator, "_model", None)
        if model is None or not hasattr(model, "add_callback"):
            logger.warning(
                "Không gắn được callback vào model pose; bỏ qua thời gian "
                "preprocess/inference/postprocess (không ước lượng thay)."
            )
            return False
        try:
            model.add_callback("on_predict_batch_end", self.on_batch_end)
            return True
        except Exception as exc:  # noqa: BLE001 - chỉ là số liệu phụ
            logger.warning(
                "Không gắn được callback thời gian từng khâu: %s", exc
            )
            return False


# ---------------------------------------------------------------------------
# Hàm công khai
# ---------------------------------------------------------------------------


def _neutral_baseline(config: Config) -> tuple[Baseline, dict[str, Any]]:
    """Nạp ``calibration.json`` nếu có; không có thì dùng baseline rỗng.

    Bài đo **không** tự hiệu chỉnh từ khung đang đo: baseline bịa ra từ
    chính dữ liệu đo sẽ làm nhãn phân loại vô nghĩa. Baseline rỗng khiến mọi
    phép so sánh cần baseline bị bỏ qua (đúng tinh thần "thiếu thì không đánh
    giá" của M2) — thời gian phân loại vẫn được đo trên đúng đường code.
    """
    path = "calibration.json"
    try:
        baseline = load_calibration(path)
    except FileNotFoundError:
        return (
            _empty_baseline(config),
            {
                "loaded": False,
                "path": path,
                "note": (
                    "Chưa có calibration.json: baseline rỗng, các nhãn phụ "
                    "thuộc baseline không được đánh giá. Thời gian phân loại "
                    "vẫn đo trên đường code thật."
                ),
            },
        )
    except CalibrationError as exc:
        logger.warning("Không đọc được '%s': %s", path, exc)
        return (
            _empty_baseline(config),
            {
                "loaded": False,
                "path": path,
                "note": f"calibration.json hỏng ({exc}); dùng baseline rỗng.",
            },
        )
    return baseline, {
        "loaded": True,
        "path": path,
        "note": "Đã nạp baseline hiệu chỉnh có sẵn.",
    }


def _empty_baseline(config: Config) -> Baseline:
    return Baseline(
        values={name: None for name in ALL_NAMES},
        view=config.camera.view,
        width=int(config.camera.width),
        height=int(config.camera.height),
        created_at="",
        frames=0,
    )


def run_benchmark(
    config: Config,
    seconds: float,
    source_override: Any = None,
    profile: str = DEFAULT_PROFILE,
) -> dict[str, Any]:
    """Đo hiệu năng pipeline trên máy đang chạy (spec §8, §11.6).

    Args:
        config: :class:`~posture_monitor.config.Config` đã nạp.
        seconds: thời lượng đo (giây, > 0), không tính khung khởi động.
        source_override: nguồn ảnh thay cho ``config.camera.source``; nhận
            chuỗi ``usb:N`` / ``picamera`` / ``file:...``, một
            :class:`~posture_monitor.capture.FrameSource`, hoặc danh sách
            khung ``numpy`` (kiểm thử trên PC).
        profile: hồ sơ đo, một trong :data:`PROFILES`. Mặc định
            :data:`DEFAULT_PROFILE` (``pose``) giữ nguyên hành vi cũ.

    Returns:
        Dict báo cáo theo schema mô tả ở docstring module. Mọi giá trị không
        đo được là ``None`` kèm lý do. Luôn có ``"profile"`` và ``"models"``.

    Raises:
        BenchmarkError: không mở được nguồn, không nạp được model, hồ sơ cần
            module/cấu hình chưa có, hoặc không xử lý được khung nào.
        ValueError: ``seconds`` không dương hoặc không hữu hạn.
    """
    seconds = float(seconds)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(
            f"seconds phải là số hữu hạn dương, nhận được {seconds!r}."
        )

    # Kiểm hồ sơ + dựng model phụ **trước** khi mở nguồn: hồ sơ không chạy
    # được thì phải từ chối ngay, không chạy nửa vời rồi in số nhầm nhãn.
    profile = normalise_profile(profile)
    extras = _build_extras(config, profile)

    notices: list[str] = []
    warnings: list[str] = []

    source, source_meta, owned = _resolve_source(config, source_override)
    if source_meta["is_static"]:
        notices.append(
            "NGUỒN ẢNH TĨNH: số FPS dưới đây KHÔNG phải FPS camera thật; nó "
            "bỏ qua thời gian đọc cảm biến và chỉ là cận trên của pipeline."
        )
    if source_meta["kind"] == "synthetic":
        notices.append(
            "NGUỒN TỔNG HỢP: bài đo dùng khung giả cho kiểm thử, không dùng "
            "được làm số liệu nghiệm thu."
        )

    estimator = None
    try:
        # Nạp model trước khi đo: thời gian nạp không phải thời gian suy luận.
        try:
            estimator = PoseEstimator(config)
        except PoseError as exc:
            raise BenchmarkError(str(exc)) from exc

        baseline, baseline_meta = _neutral_baseline(config)
        if not baseline_meta["loaded"]:
            notices.append(baseline_meta["note"])
        # ``features.extract`` đọc thẳng ``baseline.shoulder_width`` (thuộc tính
        # ném lỗi khi thiếu), nên khi chưa hiệu chỉnh phải truyền ``None``:
        # đúng ngữ nghĩa "chưa có baseline thì không tính closeness/lean_x".
        # ``classify`` chỉ dùng ``baseline.get()`` nên vẫn nhận baseline rỗng.
        feature_baseline = baseline if baseline_meta["loaded"] else None

        stage_tap = _StageTap()
        stage_ok = stage_tap.attach(estimator)

        machine = StateMachine(config.timing)
        temp_cmd = _Command("vcgencmd", "measure_temp")
        throttle_cmd = _Command("vcgencmd", "get_throttled")

        view = config.camera.view
        kp_conf_min = float(config.model.kp_conf_min)

        capture_ms: list[float] = []
        detect_ms: list[float] = []
        features_ms: list[float] = []
        classify_ms: list[float] = []
        state_ms: list[float] = []
        total_ms: list[float] = []
        pre_ms: list[float] = []
        infer_ms: list[float] = []
        post_ms: list[float] = []

        samples: list[dict[str, Any]] = []
        measured = 0
        with_person = 0
        errors = 0
        memory_samples: list[float] = []

        def take_sample(elapsed: float) -> None:
            """Lấy một mẫu nhiệt + throttle, ghi cả lý do khi không có."""
            temp_text, temp_reason = temp_cmd.run()
            throttle_text, throttle_reason = throttle_cmd.run()
            temperature = _parse_temp(temp_text)
            throttled = _parse_throttled(throttle_text)
            sample: dict[str, Any] = {
                "t_s": round(elapsed, 3),
                "temp_c": temperature,
                "temp_reason": temp_reason if temperature is None else None,
                "throttled": None if throttled is None else f"0x{throttled:x}",
                "throttle_reason": (
                    throttle_reason if throttled is None else None
                ),
                "invalidates_fps": (
                    _describe_throttle(throttled)["invalidates_fps"]
                    if throttled is not None
                    else False
                ),
            }
            samples.append(sample)
            logger.info(
                "Mẫu môi trường t=%.0fs: nhiệt=%s, throttled=%s",
                elapsed,
                "không đọc được" if temperature is None else f"{temperature:.1f}°C",
                "không đọc được" if throttled is None else f"0x{throttled:x}",
            )

        # --- Khởi động: loại khỏi thống kê, tránh lần chạy đầu làm hỏng p95.
        for _ in range(WARMUP_FRAMES):
            frame = source.read()
            if frame is None:
                break
            try:
                estimator.detect(frame)
            except Exception as exc:  # noqa: BLE001 - model lỗi phải báo rõ
                logger.warning("Khung khởi động lỗi: %s", exc)
                break

        start = time.monotonic()
        take_sample(0.0)
        last_sample_elapsed = 0.0
        start_rss = _rss_mib()
        if start_rss is not None:
            memory_samples.append(start_rss)
        if psutil is None:
            warnings.append(
                "Thiếu psutil: không đo được RAM. Cài 'pip install psutil' "
                "(đã có trong requirements.txt)."
            )
            notices.append("RAM: null vì thiếu psutil.")

        first = True
        while first or (time.monotonic() - start < seconds):
            first = False

            t0 = time.perf_counter()
            try:
                frame = source.read()
            except Exception as exc:  # noqa: BLE001 - nguồn lỗi không được sập
                errors += 1
                logger.warning("Đọc khung lỗi (%d): %s", errors, exc)
                frame = None
            if frame is None:
                # Nguồn chết hẳn: chưa xử lý được khung nào thì không có gì để
                # báo cáo; đã có khung thì dừng và báo phần đã đo.
                if measured == 0:
                    raise BenchmarkError(
                        "Không đọc được khung nào từ nguồn ảnh; không có gì "
                        "để đo."
                    )
                warnings.append(
                    "Nguồn ảnh hết khung giữa bài đo; báo cáo chỉ gồm "
                    f"{measured} khung đã xử lý."
                )
                break
            t1 = time.perf_counter()

            pose = None
            frame_failed = False
            stage_before = stage_tap.count
            try:
                pose = estimator.detect(frame)
            except Exception as exc:  # noqa: BLE001 - lỗi model không được sập
                errors += 1
                frame_failed = True
                logger.warning("Suy luận lỗi (%d): %s", errors, exc)
                if measured == 0 and errors >= 3:
                    raise BenchmarkError(
                        f"Suy luận pose lỗi liên tục, không đo được: {exc}"
                    ) from exc
                if errors > MAX_FRAME_ERRORS:
                    warnings.append(
                        f"Vượt {MAX_FRAME_ERRORS} lỗi khung; dừng bài đo sớm."
                    )
                    break
            t2 = time.perf_counter()

            # Model phụ (điện thoại/khuôn mặt): chỉ chạy khi khung có pose và
            # hồ sơ yêu cầu. Lỗi ở đây đếm riêng, không làm hỏng khung pose.
            if extras and pose is not None and not frame_failed:
                extra_now = time.monotonic() - start
                for extra in extras:
                    extra.step(frame, pose, extra_now)

            if pose is None:
                features = extract(
                    None,
                    None,
                    view=view,
                    kp_conf_min=kp_conf_min,
                    baseline=feature_baseline,
                )
            else:
                with_person += 1
                features = extract(
                    pose.xy,
                    pose.conf,
                    view=view,
                    kp_conf_min=kp_conf_min,
                    baseline=feature_baseline,
                )
            t3 = time.perf_counter()

            classification = classify(features, baseline, config.thresholds)
            t4 = time.perf_counter()

            now = time.monotonic() - start
            try:
                machine.update(now, classification.labels, classification.score)
            except ValueError as exc:  # pragma: no cover - đồng hồ đơn điệu
                logger.warning("Máy trạng thái từ chối mốc thời gian: %s", exc)
            t5 = time.perf_counter()

            # Chỉ ghi vào thống kê khi khung chạy trọn vẹn (không có ngoại lệ
            # ở khâu suy luận), để một khung lỗi không kéo median xuống.
            # Khung không thấy người vẫn là mẫu hợp lệ: nó vẫn đi hết chuỗi.
            if not frame_failed:
                capture_ms.append((t1 - t0) * 1000.0)
                detect_ms.append((t2 - t1) * 1000.0)
                features_ms.append((t3 - t2) * 1000.0)
                classify_ms.append((t4 - t3) * 1000.0)
                state_ms.append((t5 - t4) * 1000.0)
                total_ms.append((t5 - t0) * 1000.0)
                measured += 1

                if (
                    stage_ok
                    and stage_tap.count > stage_before
                    and stage_tap.latest is not None
                ):
                    speed = stage_tap.latest
                    for key, bucket in (
                        ("preprocess", pre_ms),
                        ("inference", infer_ms),
                        ("postprocess", post_ms),
                    ):
                        value = speed.get(key)
                        if isinstance(value, (int, float)) and math.isfinite(
                            float(value)
                        ):
                            bucket.append(float(value))

            if measured > 0 and measured % MEMORY_EVERY_FRAMES == 0:
                rss = _rss_mib()
                if rss is not None:
                    memory_samples.append(rss)

            elapsed = time.monotonic() - start
            if elapsed - last_sample_elapsed >= SAMPLE_INTERVAL_S:
                take_sample(elapsed)
                last_sample_elapsed = elapsed

        # Mẫu cuối: ghi lại nhiệt/throttle tại thời điểm kết thúc bài đo.
        take_sample(time.monotonic() - start)
        end_rss = _rss_mib()
        if end_rss is not None:
            memory_samples.append(end_rss)

        if measured == 0:
            raise BenchmarkError(
                "Không có khung nào chạy trọn vẹn; không có số liệu để báo "
                "cáo. Xem log để biết lỗi cụ thể."
            )

        report = _build_report(
            config=config,
            seconds=seconds,
            source_meta=source_meta,
            estimator=estimator,
            profile=profile,
            extras=extras,
            baseline_meta=baseline_meta,
            measured=measured,
            with_person=with_person,
            errors=errors,
            capture_ms=capture_ms,
            detect_ms=detect_ms,
            features_ms=features_ms,
            classify_ms=classify_ms,
            state_ms=state_ms,
            total_ms=total_ms,
            pre_ms=pre_ms,
            infer_ms=infer_ms,
            post_ms=post_ms,
            samples=samples,
            memory_samples=memory_samples,
            notices=notices,
            warnings=warnings,
        )
        return report
    finally:
        if owned:
            source.close()


def _build_report(
    *,
    config: Config,
    seconds: float,
    source_meta: dict[str, Any],
    estimator,
    profile: str = DEFAULT_PROFILE,
    extras: Sequence[_ExtraModel] = (),
    baseline_meta: dict[str, Any],
    measured: int,
    with_person: int,
    errors: int,
    capture_ms: list[float],
    detect_ms: list[float],
    features_ms: list[float],
    classify_ms: list[float],
    state_ms: list[float],
    total_ms: list[float],
    pre_ms: list[float],
    infer_ms: list[float],
    post_ms: list[float],
    samples: list[dict[str, Any]],
    memory_samples: list[float],
    notices: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Ghép báo cáo từ số liệu thô; tách riêng để dễ đọc và dễ kiểm thử."""
    total_stats = _stats(total_ms)
    median_total = None if total_stats is None else total_stats["median"]
    fps_median = (
        1000.0 / median_total
        if median_total is not None and median_total > 0
        else None
    )

    # ---- Nhiệt độ ------------------------------------------------------
    temps = [
        float(sample["temp_c"])
        for sample in samples
        if sample.get("temp_c") is not None
    ]
    temp_stats = _stats(temps)
    temp_reason = None
    if not temps:
        temp_reason = next(
            (
                sample["temp_reason"]
                for sample in samples
                if sample.get("temp_reason")
            ),
            None,
        ) or "Không lấy được mẫu nhiệt độ nào."
        notices.append(f"Nhiệt độ CPU: null — {temp_reason}")
    temperature = {
        "min": None if temp_stats is None else temp_stats["min"],
        "median": None if temp_stats is None else temp_stats["median"],
        "max": None if temp_stats is None else temp_stats["max"],
        "samples": len(temps),
        "available": bool(temps),
        "reason": temp_reason,
    }

    # ---- Throttle ------------------------------------------------------
    described = [
        _describe_throttle(int(sample["throttled"], 16))
        for sample in samples
        if sample.get("throttled") is not None
    ]
    throttle_flag_map: dict[int, str] = {}
    for value in described:
        for flag in value["flags"]:
            throttle_flag_map[int(flag["bit"], 16)] = flag["meaning"]
    final_throttle = None
    for sample in reversed(samples):
        if sample.get("throttled") is not None:
            final_throttle = sample["throttled"]
            break
    invalidates = any(value["invalidates_fps"] for value in described)
    any_set = any(value["any_set"] for value in described)
    throttle_reason = None
    if not described:
        throttle_reason = next(
            (
                sample["throttle_reason"]
                for sample in samples
                if sample.get("throttle_reason")
            ),
            None,
        ) or "Không lấy được mẫu throttle nào."
        notices.append(f"Throttle: null — {throttle_reason}")
    if invalidates:
        warnings.append(
            "THROTTLE: có mẫu bật bit 0x4/0x40000 — số FPS đo được KHÔNG HỢP "
            "LỆ theo spec §8. Sửa tản nhiệt/nguồn rồi đo lại."
        )
    elif any_set:
        warnings.append(
            "THROTTLE: có bit khác 0 đã bật (xem danh sách cờ) — đối chiếu "
            "bảng bitmask §8 trước khi dùng số."
        )
    throttle = {
        "final": final_throttle,
        "any_set": any_set,
        "invalidates_fps": invalidates,
        "flags": [
            {"bit": f"0x{bit:05x}", "meaning": meaning}
            for bit, meaning in sorted(throttle_flag_map.items())
        ],
        "samples": [
            {
                "t_s": sample["t_s"],
                "temp_c": sample["temp_c"],
                "throttled": sample["throttled"],
                "invalidates_fps": sample["invalidates_fps"],
            }
            for sample in samples
        ],
        "available": bool(described),
        "reason": throttle_reason,
    }

    # ---- RAM -----------------------------------------------------------
    ram_start = memory_samples[0] if memory_samples else None
    ram_end = memory_samples[-1] if memory_samples else None
    ram_peak = max(memory_samples) if memory_samples else None
    ram_reason = None
    if ram_peak is None:
        ram_reason = (
            "Thiếu psutil nên không đọc được RSS."
            if psutil is None
            else "Không đọc được RSS của tiến trình."
        )
    memory = {
        "start": _round(ram_start),
        "end": _round(ram_end),
        "peak": _round(ram_peak),
        "available": ram_peak is not None,
        "reason": ram_reason,
    }
    if ram_peak is not None and ram_peak >= MAX_RAM_MB:
        warnings.append(
            f"RAM đỉnh {ram_peak:.0f} MiB vượt mức {MAX_RAM_MB:.0f} MiB của "
            "spec §8."
        )

    # ---- Chỉ tiêu §8 ---------------------------------------------------
    # Chỉ kiểm được throttle khi có ``vcgencmd``. Không kiểm được thì **không**
    # được coi là bằng chứng FPS hợp lệ: phép đo FPS vẫn chạy, nhưng điều kiện
    # "không bit throttle" của §8 chưa được chứng minh trên máy này.
    throttle_checked = bool(described)
    fps_valid = throttle_checked and not invalidates
    fps_note = "FPS pipeline đầy đủ, KHÔNG phải FPS suy luận thuần."
    if invalidates:
        fps_note += " KHÔNG HỢP LỆ: throttle đã bật bit 0x4/0x40000."
    elif not throttle_checked:
        fps_note += (
            " Chưa kiểm được throttle (thiếu vcgencmd) nên chưa thể coi là "
            "bằng chứng đạt §8."
        )
    if source_meta.get("is_static"):
        fps_note += " Nguồn ảnh tĩnh nên đây chỉ là cận trên."

    if fps_median is None:
        fps_pass: bool | None = None
    elif invalidates:
        fps_pass = False
    elif not throttle_checked:
        # Đo được FPS nhưng chưa loại trừ được throttle → không đủ căn cứ kết
        # luận, không được mặc định là đạt.
        fps_pass = None
    else:
        fps_pass = bool(fps_median >= MIN_FPS)

    criteria = [
        {
            "key": "fps",
            "label": "FPS pipeline (median toàn khung)",
            "target": f">= {MIN_FPS:g} FPS",
            "measured": _round(fps_median, 3),
            "pass": fps_pass,
            "note": fps_note,
        },
        {
            "key": "temperature",
            "label": "Nhiệt độ CPU (max)",
            "target": f"< {MAX_TEMP_C:g} °C",
            "measured": None if temp_stats is None else _round(temp_stats["max"]),
            "pass": (
                None
                if temp_stats is None
                else bool(temp_stats["max"] < MAX_TEMP_C)
            ),
            "note": temp_reason or "",
        },
        {
            "key": "memory",
            "label": "RAM tiến trình (đỉnh)",
            "target": f"< {MAX_RAM_MB:g} MiB",
            "measured": None if ram_peak is None else _round(ram_peak),
            "pass": None if ram_peak is None else bool(ram_peak < MAX_RAM_MB),
            "note": ram_reason or "",
        },
        {
            "key": "throttle",
            "label": "Không bit throttle nào bật",
            "target": "0x0",
            "measured": final_throttle,
            "pass": None if not described else bool(not any_set),
            "note": throttle_reason or "",
        },
    ]

    stage_specs = (
        ("pipeline_total", total_ms, "Toàn khung (capture→state)"),
        ("capture", capture_ms, "Đọc khung từ nguồn"),
        ("pose_detect", detect_ms, "pose.detect (toàn bộ)"),
        ("pose_preprocess", pre_ms, "├ ultralytics preprocess"),
        ("pose_inference", infer_ms, "├ ultralytics inference"),
        ("pose_postprocess", post_ms, "└ ultralytics postprocess"),
        ("features", features_ms, "features.extract"),
        ("classify", classify_ms, "classifier.classify"),
        ("state_update", state_ms, "state.update"),
    )
    timing = {key: _stats(values) for key, values, _ in stage_specs}

    # ---- Danh sách model thực sự đã chạy trong bài đo -------------------
    # Đây là hàng rào chống nhãn sai: người đọc báo cáo thấy đúng những model
    # đã chạy, không phải những model mà hồ sơ *lẽ ra* phải chạy.
    models: list[dict[str, Any]] = [
        {
            "name": config.model.name,
            "role": "pose",
            "cadence": "mỗi khung",
            "format": config.model.format,
            "imgsz": int(config.model.imgsz),
            "backend": getattr(estimator, "backend", "không rõ"),
            "errors": errors,
            "timing_ms": timing.get("pose_detect"),
        }
    ]
    models.extend(extra.describe() for extra in extras)
    if profile != DEFAULT_PROFILE:
        notices.append(
            f"Hồ sơ đo '{profile}': {PROFILES.get(profile, profile)}. Chỉ "
            "được dùng số FPS của bài đo này cho đúng hồ sơ đó; đừng suy sang "
            "cấu hình khác (spec §8)."
        )

    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "generated_at": _now_iso(),
        "duration_s": round(seconds, 3),
        "profile": profile,
        "models": models,
        "host": _host_info(),
        "source": dict(source_meta),
        "model": {
            "name": config.model.name,
            "format": config.model.format,
            "backend": getattr(estimator, "backend", "không rõ"),
            "imgsz": int(config.model.imgsz),
        },
        "baseline": dict(baseline_meta),
        "frames": {
            "measured": measured,
            "with_person": with_person,
            "errors": errors,
        },
        "timing_ms": timing,
        "fps": {
            "pipeline_median": _round(fps_median, 3),
            "valid": fps_valid,
            "throttle_checked": throttle_checked,
            "note": (
                "FPS = 1000 / median(toàn khung). Đây là FPS pipeline đầy đủ "
                "(capture→detect→extract→classify→state), không phải FPS suy "
                "luận thuần; chưa gồm làm mượt, vẽ overlay, web. Bài đo chạy "
                "hết tốc lực, KHÔNG áp target_fps; lúc chạy thật ứng dụng tự "
                "giữ nhịp target_fps nên FPS thực tế thấp hơn hoặc bằng số này."
            ),
        },
        "temperature_c": temperature,
        "memory_mb": memory,
        "throttle": throttle,
        "criteria": criteria,
        "notices": notices,
        "warnings": warnings,
    }
    return report


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


# ---------------------------------------------------------------------------
# In báo cáo cho người đọc
# ---------------------------------------------------------------------------


def _fmt(value: Any, digits: int = 2, unit: str = "") -> str:
    """Định dạng số cho bảng; ``null`` hiển thị là "không đo được"."""
    if value is None:
        return "không đo được"
    if isinstance(value, bool):
        return "có" if value else "không"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}{unit}"
    return str(value)


def _pass_text(value: bool | None) -> str:
    if value is None:
        return "KHÔNG KẾT LUẬN"
    return "ĐẠT" if value else "KHÔNG ĐẠT"


def format_report(report: dict[str, Any]) -> str:
    """Dựng bảng tiếng Việt dễ đọc từ dict báo cáo."""
    lines: list[str] = []
    host = report["host"]
    source = report["source"]
    model = report["model"]
    frames = report["frames"]
    timing = report["timing_ms"]
    fps = report["fps"]
    temperature = report["temperature_c"]
    memory = report["memory_mb"]
    throttle = report["throttle"]

    lines.append("=" * 78)
    lines.append("  BÁO CÁO BENCHMARK — HỆ THỐNG GIÁM SÁT TƯ THẾ (M5)")
    lines.append("=" * 78)
    lines.append(f"  Thời điểm    : {report['generated_at']}")
    lines.append(f"  Máy          : {host['cpu']} | {host['machine']}")
    lines.append(f"  Hệ điều hành : {host['platform']}")
    lines.append(f"  Python       : {host['python']}")
    lines.append(
        "  Raspberry Pi : " + ("có" if host["is_raspberry_pi"] else "không")
    )
    lines.append(
        f"  Model        : {model['name']} ({model['backend']}, "
        f"imgsz={model['imgsz']})"
    )
    lines.append(
        f"  Hồ sơ đo     : {report.get('profile', DEFAULT_PROFILE)}"
    )
    for entry in report.get("models", []):
        if entry.get("role") == "pose":
            continue
        lines.append(
            f"    + model phụ : {entry.get('name')} — {entry.get('role')} "
            f"({entry.get('cadence')}, lỗi={entry.get('errors', 0)})"
        )
    lines.append(
        f"  Nguồn ảnh    : {source['kind']} — {source['note']} "
        f"({source['spec']}) [backend={source['backend']}]"
    )
    lines.append(
        "  Baseline     : "
        + (
            "đã nạp calibration.json"
            if report["baseline"]["loaded"]
            else "rỗng (chưa hiệu chỉnh)"
        )
    )
    lines.append(
        f"  Thời lượng   : {report['duration_s']:.1f} s, "
        f"{frames['measured']} khung ({frames['with_person']} có người)"
    )
    lines.append("-" * 78)
    lines.append(
        "  THỜI GIAN TỪNG KHÂU (ms)          N       Min    Median      P95      Max"
    )
    labels = {
        "pipeline_total": "TỔNG toàn khung",
        "capture": "  capture (đọc khung)",
        "pose_detect": "  pose.detect",
        "pose_preprocess": "    ├ preprocess (UL)",
        "pose_inference": "    ├ inference (UL)",
        "pose_postprocess": "    └ postprocess (UL)",
        "features": "  features.extract",
        "classify": "  classifier.classify",
        "state_update": "  state.update",
    }
    for key, label in labels.items():
        stats = timing.get(key)
        if stats is None:
            lines.append(f"  {label:<32} {'-':>5}  {'không đo được':>30}")
            continue
        # Khâu dưới 1 ms (features/classify/state) mà in 2 chữ số thập phân
        # thì ra toàn 0.00; lấy thêm chữ số để bảng không trông như "bằng 0".
        digits = 2 if stats["median"] >= 1.0 else 3
        lines.append(
            f"  {label:<32} {stats['count']:>5} "
            f"{stats['min']:>8.{digits}f} {stats['median']:>9.{digits}f} "
            f"{stats['p95']:>8.{digits}f} {stats['max']:>8.{digits}f}"
        )
    lines.append("-" * 78)
    # Nhãn cảnh báo cạnh con số FPS: phân biệt rõ "FPS sai vì throttle" với
    # "chưa kiểm được throttle" — hai chuyện khác nhau, không được lẫn.
    if throttle["invalidates_fps"]:
        fps_flag = "   <-- KHÔNG HỢP LỆ: throttle đã bật bit 0x4/0x40000"
    elif not throttle["available"]:
        fps_flag = (
            "   <-- CHƯA XÁC NHẬN: máy không có vcgencmd nên chưa kiểm được "
            "throttle"
        )
    else:
        fps_flag = ""
    lines.append(
        f"  FPS pipeline (từ median toàn khung): {_fmt(fps['pipeline_median'], 2)}"
        + fps_flag
    )
    lines.append(f"  {fps['note']}")
    lines.append("-" * 78)
    lines.append(
        "  NHIỆT ĐỘ CPU (°C)  : "
        + (
            "không đo được"
            if not temperature["available"]
            else (
                f"min={_fmt(temperature['min'])} "
                f"median={_fmt(temperature['median'])} "
                f"max={_fmt(temperature['max'])} "
                f"({temperature['samples']} mẫu)"
            )
        )
    )
    if not temperature["available"]:
        lines.append(f"    lý do: {temperature['reason']}")
    lines.append(
        "  RAM (MiB)          : "
        + (
            "không đo được"
            if not memory["available"]
            else (
                f"đầu={_fmt(memory['start'], 1)} "
                f"cuối={_fmt(memory['end'], 1)} "
                f"đỉnh={_fmt(memory['peak'], 1)}"
            )
        )
    )
    if not memory["available"]:
        lines.append(f"    lý do: {memory['reason']}")
    if not throttle["available"]:
        lines.append("  THROTTLE           : không đo được")
        lines.append(f"    lý do: {throttle['reason']}")
    else:
        lines.append(
            "  THROTTLE           : "
            f"cuối={throttle['final']} | "
            f"bit bật={'có' if throttle['any_set'] else 'không'}"
        )
        for flag in throttle["flags"]:
            lines.append(f"    {flag['bit']}: {flag['meaning']}")
    lines.append("-" * 78)
    lines.append("  TIÊU CHÍ NGHIỆM THU (spec §8)")
    for criterion in report["criteria"]:
        measured = criterion["measured"]
        shown = "không đo được" if measured is None else _fmt(measured)
        lines.append(
            f"  - {criterion['label']}: đo được: {shown}; "
            f"mục tiêu {criterion['target']} => {_pass_text(criterion['pass'])}"
        )
        if criterion["note"]:
            lines.append(f"      {criterion['note']}")
    if report["notices"]:
        lines.append("-" * 78)
        lines.append("  GHI CHÚ")
        for notice in report["notices"]:
            lines.append(f"  * {notice}")
    if report["warnings"]:
        lines.append("-" * 78)
        lines.append("  CẢNH BÁO")
        for warning in report["warnings"]:
            lines.append(f"  ! {warning}")
    lines.append("=" * 78)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Điểm vào dòng lệnh
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Parser riêng cho ``python -m posture_monitor.benchmark``."""
    parser = argparse.ArgumentParser(
        prog="python -m posture_monitor.benchmark",
        description=(
            "Đo FPS/độ trễ/nhiệt/RAM/throttle trên chính máy đang chạy "
            "(spec §8, §11.6)."
        ),
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=60.0,
        help="Thời lượng đo, giây (mặc định: 60).",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Đường dẫn file cấu hình (mặc định: config.yaml).",
    )
    parser.add_argument(
        "--source",
        default=None,
        metavar="NGUON",
        help=(
            "Ghi đè nguồn ảnh: usb:0 | picamera | file:anh.jpg | "
            "file:video.mp4. Trên Pi chưa có camera, dùng ảnh tĩnh."
        ),
    )
    parser.add_argument(
        "--json",
        default=None,
        metavar="DUONG_DAN",
        help="Ghi báo cáo JSON ra file (ngoài bảng in trên màn hình).",
    )
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        metavar="HO_SO",
        help=(
            "Hồ sơ đo: "
            + "; ".join(f"{key} = {value}" for key, value in PROFILES.items())
            + f". Mặc định: {DEFAULT_PROFILE}. Tên sai hoặc hồ sơ cần module "
            "chưa có sẽ bị từ chối với thông điệp tiếng Việt và mã thoát khác "
            "0, KHÔNG lặng lẽ đo thiếu model."
        ),
    )
    parser.add_argument(
        "--no-gpio",
        action="store_true",
        help="Tương thích CLI chung; benchmark không dùng GPIO.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Mức log: DEBUG, INFO, WARNING, ERROR (mặc định: INFO).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Chạy bài đo từ dòng lệnh; trả mã thoát của tiến trình."""
    parser = build_parser()
    args = parser.parse_args(argv)
    logger_root = setup_logging(args.log_level)

    if args.no_gpio:
        logger_root.info(
            "Benchmark không dùng GPIO; cờ --no-gpio chỉ để tương thích CLI."
        )
    if args.seconds <= 0:
        logger_root.error("--seconds phải lớn hơn 0.")
        return 2

    try:
        try:
            config = load_config(args.config)
        except FileNotFoundError as exc:
            logger_root.error("%s", exc)
            return 2
        except ConfigError as exc:
            logger_root.error("Cấu hình không hợp lệ: %s", exc)
            return 2

        report = run_benchmark(
            config,
            args.seconds,
            source_override=args.source,
            profile=args.profile,
        )
    except BenchmarkError as exc:
        logger_root.error("Không đo được: %s", exc)
        return 2
    except KeyboardInterrupt:
        print("\nĐã dừng theo yêu cầu.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - bài đo không được để traceback
        logger_root.error("Lỗi không mong muốn khi đo: %s", exc)
        logger_root.debug("Chi tiết:", exc_info=True)
        return 1

    print(format_report(report))

    if args.json:
        target = Path(args.json)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            logger_root.error("Không ghi được báo cáo JSON '%s': %s", target, exc)
            return 2
        print(f"Đã ghi báo cáo JSON: {target.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
