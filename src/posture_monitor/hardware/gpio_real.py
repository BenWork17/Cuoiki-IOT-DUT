"""Phần cứng thật trên Raspberry Pi — gpiozero (không dùng RPi.GPIO).

Bảng đấu dây mặc định theo spec v2 §5.7:

| Linh kiện        | Chân BCM |
| ---------------- | -------- |
| LED xanh         | 17       |
| LED vàng         | 27       |
| LED đỏ           | 22       |
| Buzzer chủ động  | 18       |
| Mô-tơ rung       | 23       |
| HC-SR04 TRIG     | 5        |
| HC-SR04 ECHO     | 6        |

Lưu ý an toàn: chân ECHO của HC-SR04 là 5V, **bắt buộc** chia áp xuống 3.3V
trước khi nối vào GPIO (xem README). Mô-tơ rung phải qua transistor NPN và
diode flyback, không nối thẳng vào GPIO.

Module này import được trên PC (không có gpiozero cũng không sao): mọi lỗi
khởi tạo được ghi log và thiết bị vắng mặt bị bỏ qua, không crash.
"""

from __future__ import annotations

import time

from ..logging_setup import get_logger
from .base import STATES, Hardware

logger = get_logger(__name__)

#: Thời gian một nhịp buzzer/rung ngắn, tính bằng giây.
PULSE_SECONDS = 0.3

#: Thời gian rung khi cảnh báo BAD (spec §5.7).
VIBRATION_BAD_SECONDS = 0.3


class GpioRealHardware(Hardware):
    """Điều khiển LED/buzzer/rung thật bằng gpiozero.

    Mỗi thiết bị được khởi tạo độc lập: linh kiện nào vắng hoặc lỗi thì bỏ
    qua, ghi log, các linh kiện còn lại vẫn chạy.
    """

    def __init__(self, config=None) -> None:
        self._config = config
        self._leds: dict[str, object] = {}
        self._buzzer = None
        self._vibration = None
        self._state = "ABSENT"
        self._available = False
        self._init_devices()
        self.set_state("ABSENT")

    # -- khởi tạo -------------------------------------------------------

    def _pin(self, name: str, default: int) -> int:
        pins = getattr(getattr(self._config, "hardware", None), "pins", None)
        value = getattr(pins, name, default) if pins is not None else default
        try:
            return int(value)
        except (TypeError, ValueError):
            logger.warning(
                "Chân '%s' không hợp lệ (%r); dùng mặc định %d.",
                name,
                value,
                default,
            )
            return default

    def _init_devices(self) -> None:
        """Dựng các đối tượng gpiozero; thiếu thư viện thì chỉ ghi log."""
        try:
            from gpiozero import Buzzer, LED  # noqa: PLC0415 - cố ý import muộn
        except Exception as exc:  # noqa: BLE001 - PC không có gpiozero
            logger.warning(
                "Không import được gpiozero (%s); phần cứng thật không hoạt "
                "động. Chạy với --no-gpio trên máy không phải Pi.",
                exc,
            )
            return

        for key, pin in (
            ("led_green", self._pin("led_green", 17)),
            ("led_yellow", self._pin("led_yellow", 27)),
            ("led_red", self._pin("led_red", 22)),
        ):
            try:
                self._leds[key] = LED(pin)
            except Exception as exc:  # noqa: BLE001 - chân bận/hỏng
                logger.warning("Không khởi tạo được %s trên GPIO%d: %s", key, pin, exc)

        try:
            self._buzzer = Buzzer(self._pin("buzzer", 18))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Không khởi tạo được buzzer trên GPIO%d: %s",
                self._pin("buzzer", 18),
                exc,
            )

        try:
            self._vibration = Buzzer(self._pin("vibration", 23))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Không khởi tạo được mô-tơ rung trên GPIO%d: %s",
                self._pin("vibration", 23),
                exc,
            )

        self._available = bool(self._leds or self._buzzer or self._vibration)
        if self._available:
            logger.info(
                "Đã khởi tạo phần cứng thật: %d LED, buzzer=%s, rung=%s.",
                len(self._leds),
                self._buzzer is not None,
                self._vibration is not None,
            )

    # -- tiện ích -------------------------------------------------------

    def _alerts_config(self):
        return getattr(self._config, "alerts", None)

    def _all_leds_off(self) -> None:
        for name, led in self._leds.items():
            try:
                led.off()
            except Exception:  # noqa: BLE001
                logger.debug("Bỏ qua lỗi tắt %s.", name, exc_info=True)

    def _led_on(self, name: str) -> None:
        led = self._leds.get(name)
        if led is None:
            return
        try:
            led.on()
        except Exception:  # noqa: BLE001
            logger.debug("Bỏ qua lỗi bật %s.", name, exc_info=True)

    def _beep(self, times: int) -> None:
        if self._buzzer is None:
            return
        for _ in range(max(0, times)):
            try:
                self._buzzer.on()
                time.sleep(PULSE_SECONDS)
                self._buzzer.off()
                time.sleep(PULSE_SECONDS)
            except Exception:  # noqa: BLE001
                logger.debug("Bỏ qua lỗi buzzer.", exc_info=True)
                return

    def _vibrate(self, seconds: float) -> None:
        if self._vibration is None:
            return
        try:
            self._vibration.on()
            time.sleep(seconds)
            self._vibration.off()
        except Exception:  # noqa: BLE001
            logger.debug("Bỏ qua lỗi mô-tơ rung.", exc_info=True)

    # -- giao diện Hardware --------------------------------------------

    def set_state(self, state: str, *, alert: bool = True) -> None:
        """Ánh xạ trạng thái sang LED/buzzer/rung theo spec §5.7.

        ``alert=False`` vẫn đổi LED đúng trạng thái nhưng **không** kêu và
        **không** rung — đó là trường hợp sự kiện bị ``alert_cooldown_s``
        chặn: người dùng đã được nhắc gần đây thì đèn vẫn phải phản ánh tư
        thế, chỉ tiếng là phải im.
        """
        if state not in STATES:
            logger.warning("Trạng thái phần cứng không hợp lệ: %r (bỏ qua).", state)
            return

        if not self._available:
            logger.debug("Không có thiết bị thật; bỏ qua trạng thái %s.", state)
            return

        self._state = state
        self._all_leds_off()
        alerts = self._alerts_config()
        buzzer_enabled = bool(getattr(alerts, "buzzer_enabled", True))
        vibration_enabled = bool(getattr(alerts, "vibration_enabled", True))
        sound = bool(alert)

        if state == "GOOD":
            self._led_on("led_green")
        elif state == "WARN":
            self._led_on("led_yellow")
        elif state == "BAD":
            self._led_on("led_red")
            if sound and buzzer_enabled:
                self._beep(2)
            if sound and vibration_enabled:
                self._vibrate(VIBRATION_BAD_SECONDS)
        elif state == "BREAK":
            # Nhắc nghỉ không bao giờ bị cooldown chặn, nhưng vẫn tôn trọng
            # cờ cho nhất quán với hợp đồng.
            if sound and buzzer_enabled:
                self._beep(3)
        # ABSENT: tắt hết, không làm gì thêm.

        logger.info(
            "Phần cứng thật -> %s%s", state, "" if sound else " (im lặng — cooldown)"
        )

    def close(self) -> None:
        self._all_leds_off()
        for name, device in (
            *self._leds.items(),
            ("buzzer", self._buzzer),
            ("vibration", self._vibration),
        ):
            if device is None:
                continue
            try:
                device.close()
            except Exception:  # noqa: BLE001
                logger.debug("Bỏ qua lỗi close %s.", name, exc_info=True)
        self._leds.clear()
        self._buzzer = None
        self._vibration = None
        self._available = False

    @property
    def state(self) -> str:
        return self._state

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log
        return f"GpioRealHardware(state={self._state!r}, available={self._available})"
