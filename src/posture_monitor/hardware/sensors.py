"""Cảm biến khoảng cách siêu âm và giao diện cảm biến chung (spec v2 §5.8).

Giao diện :class:`Sensor` cố ý tối giản (``read()`` / ``close()``) để sau này
gắn thêm cảm biến khác mà không đụng tầng trên: tầng đó chỉ cần một giá trị số
hoặc ``None`` khi chưa có mẫu.

:class:`UltrasonicSensor` bọc HC-SR04 bằng ``gpiozero.DistanceSensor``:

- Đọc trong **luồng riêng** mỗi 0,5 s; mỗi lần lấy **trung vị của 5 phép đo**
  và loại mẫu ngoài ``[2, 200] cm`` (spec §5.8).
- Năm phép đo trong một mẫu được giãn cách ``SAMPLE_GAP_S``.
- ``read()`` trả **giá trị hợp lệ gần nhất**, ``None`` nếu chưa từng có mẫu
  hợp lệ.
- Thiếu ``gpiozero`` trên PC không phải lỗi: cảm biến ghi log, không mở chân,
  ``read()`` trả ``None``.
"""

from __future__ import annotations

import math
import statistics
import threading
import time
import warnings
from abc import ABC, abstractmethod
from typing import Iterable

from ..core.labels import TOO_CLOSE
from ..core.logging_setup import get_logger

logger = get_logger(__name__)

#: Chu kỳ một lần lấy mẫu (giây), spec §5.8.
SAMPLE_INTERVAL_S = 0.5

#: Khoảng cách giữa hai phép đo trong cùng một mẫu (giây).
SAMPLE_GAP_S = 0.05

#: Số phép đo trong một mẫu; lấy trung vị (spec §5.8).
SAMPLE_COUNT = 5

#: Dải khoảng cách hợp lệ (cm). Ngoài dải này là nhiễu hoặc không có vật.
MIN_VALID_CM = 2.0
MAX_VALID_CM = 200.0

#: Tầm đo tối đa truyền cho gpiozero (mét). Khớp ``MAX_VALID_CM``.
MAX_DISTANCE_M = MAX_VALID_CM / 100.0

#: Thời gian tối đa chờ luồng đọc thoát khi :meth:`UltrasonicSensor.close`.
CLOSE_JOIN_S = 2.0

#: Số lần đọc lỗi đầu tiên được log ở mức INFO trước khi hạ xuống DEBUG.
_NO_ECHO_INFO_LIMIT = 1


class Sensor(ABC):
    """Giao diện một cảm biến đọc giá trị số."""

    @abstractmethod
    def read(self) -> float | None:
        """Giá trị hợp lệ gần nhất, hoặc ``None`` khi chưa có mẫu nào."""

    @abstractmethod
    def close(self) -> None:
        """Dừng luồng đọc và giải phóng tài nguyên."""

    def __enter__(self) -> "Sensor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class NullSensor(Sensor):
    """Cảm biến không làm gì; dùng khi tính năng bị tắt trong cấu hình."""

    def read(self) -> float | None:
        return None

    def close(self) -> None:
        pass


class FakeSensor(Sensor):
    """Cảm biến giả trả lần lượt các giá trị trong danh sách."""

    def __init__(
        self,
        values: Iterable[float | None],
        *,
        repeat_last: bool = True,
    ) -> None:
        self._values = list(values)
        self._repeat_last = bool(repeat_last)
        self._index = 0
        self._last: float | None = None
        self._closed = False

    def read(self) -> float | None:
        if self._index < len(self._values):
            self._last = self._values[self._index]
            self._index += 1
        elif not self._repeat_last:
            return None
        return self._last

    def close(self) -> None:
        self._closed = True


def aggregate_distance(
    samples: Iterable[float | None],
) -> float | None:
    """Trung vị các mẫu hợp lệ trong ``[MIN_VALID_CM, MAX_VALID_CM]``."""
    valid: list[float] = []
    for sample in samples:
        if sample is None:
            continue
        try:
            value = float(sample)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        if MIN_VALID_CM <= value <= MAX_VALID_CM:
            valid.append(value)
    return statistics.median(valid) if valid else None


def apply_distance(
    labels: frozenset[str],
    distance_cm: float | None,
    min_distance_cm: float,
) -> frozenset[str]:
    """Hợp nhãn ``TOO_CLOSE`` từ nguồn siêu âm vào nhãn của camera (§5.8)."""
    limit = float(min_distance_cm)
    if not math.isfinite(limit) or limit <= 0.0:
        raise ValueError(
            f"min_distance_cm phải là số hữu hạn dương, nhận được "
            f"{min_distance_cm!r}."
        )

    merged = frozenset(labels)
    if distance_cm is None:
        return merged
    try:
        value = float(distance_cm)
    except (TypeError, ValueError):
        return merged
    if not math.isfinite(value):
        return merged
    if value < limit:
        return merged | {TOO_CLOSE}
    return merged


class UltrasonicSensor(Sensor):
    """HC-SR04 trên chân TRIG/ECHO lấy từ ``config.hardware.pins``."""

    def __init__(
        self,
        config=None,
        *,
        interval_s: float = SAMPLE_INTERVAL_S,
        samples: int = SAMPLE_COUNT,
        sample_gap_s: float = SAMPLE_GAP_S,
        autostart: bool = True,
    ) -> None:
        if not math.isfinite(float(interval_s)) or interval_s <= 0:
            raise ValueError(
                f"interval_s phải là số hữu hạn dương, nhận được {interval_s!r}."
            )
        if int(samples) < 1:
            raise ValueError(f"samples phải >= 1, nhận được {samples!r}.")
        if not math.isfinite(float(sample_gap_s)) or sample_gap_s < 0:
            raise ValueError(
                "sample_gap_s phải là số hữu hạn không âm, nhận được "
                f"{sample_gap_s!r}."
            )

        self._config = config
        self._interval_s = float(interval_s)
        self._samples = int(samples)
        self._sample_gap_s = float(sample_gap_s)
        self._trig, self._echo = self._pins_from_config(config)

        self._device = None
        self._lock = threading.Lock()
        self._last: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failures = 0

        if autostart:
            self._device = self._create_device()
            if self._device is not None:
                self._thread = threading.Thread(
                    target=self._run,
                    name="ultrasonic-sensor",
                    daemon=True,
                )
                self._thread.start()

    # ------------------------------------------------------------------
    # Khởi tạo
    # ------------------------------------------------------------------
    @staticmethod
    def _pins_from_config(config) -> tuple[int, int]:
        """Đọc TRIG/ECHO từ ``config.hardware.pins``, lỗi thì về mặc định."""
        pins = getattr(getattr(config, "hardware", None), "pins", None)
        defaults = (5, 6)
        if pins is None:
            return defaults
        values = []
        for name, default in (("trig", defaults[0]), ("echo", defaults[1])):
            raw = getattr(pins, name, default)
            try:
                values.append(int(raw))
            except (TypeError, ValueError):
                logger.warning(
                    "Chân '%s' không hợp lệ (%r); dùng mặc định %d.",
                    name,
                    raw,
                    default,
                )
                values.append(default)
        return values[0], values[1]

    def _create_device(self):
        """Dựng ``DistanceSensor``; thiếu gpiozero/chân bận thì trả ``None``."""
        try:
            from gpiozero import DistanceSensor  # noqa: PLC0415 - import muộn
        except Exception as exc:  # noqa: BLE001 - PC không có gpiozero
            logger.warning(
                "Không import được gpiozero (%s); cảm biến siêu âm không hoạt "
                "động. Trên PC đây là bình thường.",
                exc,
            )
            return None

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                device = DistanceSensor(
                    echo=self._echo,
                    trigger=self._trig,
                    max_distance=MAX_DISTANCE_M,
                    queue_len=1,
                )
            for warning in caught:
                logger.info(
                    "gpiozero cảnh báo khi tạo cảm biến siêu âm: %s",
                    warning.message,
                )
        except Exception as exc:  # noqa: BLE001 - chân bận/backend hỏng
            logger.warning(
                "Không khởi tạo được HC-SR04 trên TRIG=GPIO%d, ECHO=GPIO%d: %s",
                self._trig,
                self._echo,
                exc,
            )
            return None

        logger.info(
            "Cảm biến siêu âm sẵn sàng: TRIG=GPIO%d, ECHO=GPIO%d, "
            "chu kỳ %.2f s, %d mẫu/lần.",
            self._trig,
            self._echo,
            self._interval_s,
            self._samples,
        )
        return device

    # ------------------------------------------------------------------
    # Giao diện Sensor
    # ------------------------------------------------------------------
    def read(self) -> float | None:
        """Khoảng cách hợp lệ gần nhất (cm), hoặc ``None``."""
        with self._lock:
            return self._last

    def close(self) -> None:
        """Dừng luồng rồi đóng thiết bị; gọi nhiều lần không sao."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(CLOSE_JOIN_S)
            self._thread = None
        device = self._device
        self._device = None
        if device is not None:
            try:
                device.close()
            except Exception:  # noqa: BLE001
                logger.debug("Bỏ qua lỗi close cảm biến siêu âm.", exc_info=True)

    # ------------------------------------------------------------------
    # Luồng đọc
    # ------------------------------------------------------------------
    def _run(self) -> None:
        """Lấy mẫu đều đặn; không bao giờ để lỗi cảm biến thoát khỏi luồng."""
        next_tick = time.monotonic()
        while not self._stop.is_set():
            try:
                samples = self._collect_samples()
                median = aggregate_distance(samples)
                if median is not None:
                    with self._lock:
                        self._last = median
            except Exception:  # noqa: BLE001 - thread không được chết
                logger.warning(
                    "Lỗi không mong đợi khi đọc cảm biến siêu âm; bỏ qua nhịp.",
                    exc_info=True,
                )

            next_tick += self._interval_s
            delay = next_tick - time.monotonic()
            if delay <= 0.0:
                next_tick = time.monotonic()
                delay = 0.0
            self._stop.wait(delay)

    def _collect_samples(self) -> list[float | None]:
        """Lấy ``samples`` phép đo, giãn cách để mỗi lần là một lần đo mới."""
        samples: list[float | None] = []
        for index in range(self._samples):
            if index:
                if self._stop.wait(self._sample_gap_s):
                    break
            samples.append(self._read_once())
        return samples

    def _read_once(self) -> float | None:
        """Một phép đo thô, quy đổi mét → cm; lỗi trả ``None``."""
        device = self._device
        if device is None:
            return None
        try:
            value = float(device.distance) * 100.0
            self._failures = 0
            return value
        except Exception as exc:  # noqa: BLE001 - no echo là bình thường
            self._failures += 1
            if self._failures <= _NO_ECHO_INFO_LIMIT:
                logger.info(
                    "Siêu âm không đọc được (%s). Trên Pi chưa gắn HC-SR04 "
                    "đây là bình thường; sẽ thử lại mỗi %.1f s.",
                    exc,
                    self._interval_s,
                )
            else:
                logger.debug("Siêu âm vẫn không đọc được: %s", exc)
            return None


def create_sensor(config=None) -> Sensor:
    """Tạo cảm biến theo ``config.sensors`` (spec §5.8)."""
    sensors_cfg = getattr(config, "sensors", None)
    enabled = bool(getattr(sensors_cfg, "ultrasonic_enabled", True))
    if not enabled:
        logger.info(
            "Siêu âm đang tắt (sensors.ultrasonic_enabled=false); bỏ qua "
            "HC-SR04."
        )
        return NullSensor()
    return UltrasonicSensor(config)
