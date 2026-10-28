"""Phần cứng giả lập — chỉ ghi log, không đụng GPIO thật.

Theo spec v2 §5.7, dùng ``gpiozero.pins.mock.MockFactory`` có sẵn thay vì tự
viết mock pin. Việc gán ``Device.pin_factory = MockFactory()`` khiến mọi đối
tượng gpiozero (kể cả ``DistanceSensor`` dựng ở module khác) chạy trên pin giả,
nên không thể vô tình bật chân thật khi đang ở ``--no-gpio``.

``gpiozero`` là thư viện ngoài, có thể không có trên PC; import được bọc trong
hàm khởi tạo. Thiếu thư viện thì lớp vẫn hoạt động ở mức chỉ-ghi-log.
"""

from __future__ import annotations

import time

from ..logging_setup import get_logger
from .base import STATES, Hardware

logger = get_logger(__name__)

#: Thời gian một "nhịp" buzzer/rung ngắn, tính bằng giây.
PULSE_SECONDS = 0.3


class GpioMockHardware(Hardware):
    """Bản giả lập: dựng LED/buzzer trên MockFactory và ghi log trạng thái.

    Nếu ``gpiozero`` không import được, vẫn log trạng thái nhưng không dựng
    thiết bị nào — đủ để ``run --no-gpio`` chạy trên PC.
    """

    def __init__(self, config=None) -> None:
        self._config = config
        self._devices: dict[str, object] = {}
        self._mock_ready = False
        self._state = "ABSENT"
        self._install_mock_factory()
        self.set_state("GOOD")

    # -- thiết lập ------------------------------------------------------

    def _install_mock_factory(self) -> None:
        """Gán MockFactory cho gpiozero; nuốt lỗi nếu không có thư viện."""
        try:
            from gpiozero import Device  # noqa: PLC0415 - cố ý import muộn
            from gpiozero.pins.mock import MockFactory  # noqa: PLC0415

            Device.pin_factory = MockFactory()
            self._mock_ready = True
            logger.info("gpiozero dùng MockFactory (không bật chân thật).")
        except Exception as exc:  # noqa: BLE001 - PC không có gpiozero là bình thường
            logger.info(
                "Không dựng được MockFactory của gpiozero (%s); chỉ ghi log.",
                exc,
            )
            return

        self._build_devices()

    def _build_devices(self) -> None:
        """Dựng LED/buzzer giả theo bảng chân trong config."""
        pins = self._pins_config()
        try:
            from gpiozero import Buzzer, LED  # noqa: PLC0415

            self._devices["led_green"] = LED(pins["led_green"])
            self._devices["led_yellow"] = LED(pins["led_yellow"])
            self._devices["led_red"] = LED(pins["led_red"])
            self._devices["buzzer"] = Buzzer(pins["buzzer"])
        except Exception as exc:  # noqa: BLE001 - thiếu chân/backend không được crash
            logger.warning("Không dựng được thiết bị giả lập đầy đủ: %s", exc)

    def _pins_config(self) -> dict[str, int]:
        pins = getattr(getattr(self._config, "hardware", None), "pins", None)
        defaults = {
            "led_green": 17,
            "led_yellow": 27,
            "led_red": 22,
            "buzzer": 18,
        }
        if pins is None:
            return defaults
        return {
            key: int(getattr(pins, key, default))
            for key, default in defaults.items()
        }

    # -- điều khiển -----------------------------------------------------

    def _all_off(self) -> None:
        for name, device in self._devices.items():
            if name == "buzzer":
                continue
            try:
                device.off()
            except Exception:  # noqa: BLE001
                logger.debug("Bỏ qua lỗi tắt %s.", name, exc_info=True)

    def _led(self, name: str, on: bool) -> None:
        device = self._devices.get(name)
        if device is None:
            return
        try:
            device.on() if on else device.off()
        except Exception:  # noqa: BLE001
            logger.debug("Bỏ qua lỗi điều khiển %s.", name, exc_info=True)

    def _beep(self, times: int) -> None:
        buzzer = self._devices.get("buzzer")
        if buzzer is None:
            return
        for _ in range(max(0, times)):
            try:
                buzzer.on()
                time.sleep(PULSE_SECONDS)
                buzzer.off()
                time.sleep(PULSE_SECONDS)
            except Exception:  # noqa: BLE001
                logger.debug("Bỏ qua lỗi buzzer.", exc_info=True)
                return

    def set_state(self, state: str) -> None:
        """Ánh xạ trạng thái sang thiết bị và ghi log.

        ``BAD`` và ``BREAK`` có tiếng buzzer nên chạy đồng bộ ngắn; các trạng
        thái khác chỉ đổi LED, gần như tức thời.
        """
        if state not in STATES:
            logger.warning("Trạng thái phần cứng không hợp lệ: %r (bỏ qua).", state)
            return

        self._state = state
        self._all_off()

        if state == "GOOD":
            self._led("led_green", True)
            detail = "LED xanh sáng"
        elif state == "WARN":
            self._led("led_yellow", True)
            detail = "LED vàng sáng"
        elif state == "BAD":
            self._led("led_red", True)
            detail = "LED đỏ sáng, buzzer 2 tiếng ngắn"
            self._beep(2)
        elif state == "BREAK":
            detail = "buzzer 3 tiếng (nhắc nghỉ)"
            self._beep(3)
        else:  # ABSENT
            detail = "tắt hết LED"

        mode = "mock" if self._mock_ready else "log-only"
        logger.info("[%s] trạng thái=%s — %s", mode, state, detail)

    def close(self) -> None:
        self._all_off()
        for name, device in list(self._devices.items()):
            try:
                device.close()
            except Exception:  # noqa: BLE001
                logger.debug("Bỏ qua lỗi close %s.", name, exc_info=True)
        self._devices.clear()

    @property
    def state(self) -> str:
        """Trạng thái gần nhất đã đặt."""
        return self._state

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log
        return f"GpioMockHardware(state={self._state!r})"
