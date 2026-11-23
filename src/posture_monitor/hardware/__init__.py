"""Lớp phần cứng: LED, buzzer, mô-tơ rung, siêu âm.

Hai triển khai cùng một giao diện :class:`Hardware` (spec v2 §5.7):

- :mod:`~posture_monitor.hardware.gpio_mock` — chỉ ghi log, dùng khi
  ``--no-gpio``, khi chạy trên PC, hoặc khi không phát hiện GPIO.
- :mod:`~posture_monitor.hardware.gpio_real` — gpiozero trên chân thật.

Cả hai module được import muộn ở :func:`create_hardware` để tránh kéo
``gpiozero``/``lgpio`` vào lúc import gói.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..core.logging_setup import get_logger
from .base import Hardware, NullHardware
from .sensors import (
    FakeSensor,
    NullSensor,
    Sensor,
    UltrasonicSensor,
    create_sensor,
)

logger = get_logger(__name__)

__all__ = [
    "FakeSensor",
    "GpioMockHardware",
    "GpioRealHardware",
    "Hardware",
    "NullHardware",
    "NullSensor",
    "Sensor",
    "UltrasonicSensor",
    "create_hardware",
    "create_sensor",
]


def __getattr__(name: str):
    """Nạp muộn hai lớp triển khai khi được truy cập qua gói."""
    if name == "GpioMockHardware":
        from .gpio_mock import GpioMockHardware  # noqa: PLC0415

        return GpioMockHardware
    if name == "GpioRealHardware":
        from .gpio_real import GpioRealHardware  # noqa: PLC0415

        return GpioRealHardware
    raise AttributeError(f"module {__name__!r} không có thuộc tính {name!r}")


def _gpio_available() -> bool:
    """Có GPIO dùng được không (Linux + có chip GPIO của Pi)."""
    if not sys.platform.startswith("linux"):
        return False
    return any(
        Path(path).exists()
        for path in ("/dev/gpiochip0", "/sys/class/gpio")
    )


def create_hardware(config, no_gpio: bool = False) -> Hardware:
    """Tạo đối tượng phần cứng theo ``config.hardware.mock`` và ``--no-gpio``."""
    mode = config.hardware.mock

    if no_gpio:
        logger.info("Chế độ --no-gpio: dùng phần cứng giả lập.")
        use_mock = True
    elif mode is True:
        use_mock = True
    elif mode is False:
        use_mock = False
    else:  # "auto"
        use_mock = not _gpio_available()

    if use_mock:
        try:
            from .gpio_mock import GpioMockHardware  # noqa: PLC0415

            return GpioMockHardware(config)
        except Exception as exc:  # noqa: BLE001 - không được crash vì GPIO
            logger.warning(
                "Không khởi tạo được phần cứng giả lập (%s); dùng NullHardware.",
                exc,
            )
            return NullHardware()

    try:
        from .gpio_real import GpioRealHardware  # noqa: PLC0415

        return GpioRealHardware(config)
    except Exception as exc:  # noqa: BLE001 - thiếu GPIO/gpiozero là bình thường
        logger.warning(
            "Không khởi tạo được GPIO thật (%s); rơi về phần cứng giả lập.",
            exc,
        )
        try:
            from .gpio_mock import GpioMockHardware  # noqa: PLC0415

            return GpioMockHardware(config)
        except Exception as mock_exc:  # noqa: BLE001
            logger.warning(
                "Không khởi tạo được phần cứng giả lập (%s); dùng NullHardware.",
                mock_exc,
            )
            return NullHardware()
