"""Test hợp đồng ``set_state(state, *, alert=...)`` của tầng phần cứng.

Mục tiêu khoá đúng một điều: ``alert=False`` **vẫn** đổi LED đúng trạng thái
nhưng **không** phát buzzer/rung. Đây là thứ khiến ``alert_cooldown_s`` thật
sự có tác dụng — trước đó cooldown chỉ chặn được trường hợp lặp lại cùng
trạng thái, còn khi trạng thái *đổi* sang BAD thì vẫn kêu.

Test bơm thiết bị ghi lại vào đối tượng thay vì dựng GPIO: trên PC không có
``gpiozero``, và ngay cả khi có thì ``MockPin`` không mô phỏng được buzzer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.config import AlertsConfig  # noqa: E402
from posture_monitor.hardware.base import NullHardware, STATES  # noqa: E402
from posture_monitor.hardware.gpio_mock import GpioMockHardware  # noqa: E402
from posture_monitor.hardware.gpio_real import GpioRealHardware  # noqa: E402


class Recorder:
    """Thiết bị ghi lại số lần bật/tắt."""

    def __init__(self) -> None:
        self.on_calls = 0
        self.off_calls = 0

    def on(self) -> None:
        self.on_calls += 1

    def off(self) -> None:
        self.off_calls += 1

    def close(self) -> None:
        pass


class FakeConfig:
    """Config tối thiểu: chỉ cần ``alerts``."""

    def __init__(self, **alerts) -> None:
        self.alerts = AlertsConfig(**alerts)


def _real_hardware():
    """``GpioRealHardware`` đã bơm thiết bị ghi lại, không đụng GPIO."""
    hardware = GpioRealHardware()
    leds = {
        "led_green": Recorder(),
        "led_yellow": Recorder(),
        "led_red": Recorder(),
    }
    buzzer = Recorder()
    vibration = Recorder()
    hardware._leds = leds
    hardware._buzzer = buzzer
    hardware._vibration = vibration
    hardware._available = True
    return hardware, leds, buzzer, vibration


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Chặn ``time.sleep(0.3)`` của nhịp buzzer để test chạy nhanh."""
    import posture_monitor.hardware.gpio_real as gpio_real
    import posture_monitor.hardware.gpio_mock as gpio_mock

    monkeypatch.setattr(gpio_real.time, "sleep", lambda *_: None)
    monkeypatch.setattr(gpio_mock.time, "sleep", lambda *_: None)


# ---------------------------------------------------------------------------
# GpioRealHardware
# ---------------------------------------------------------------------------

def test_real_bad_with_alert_sounds_and_lights_red():
    hardware, leds, buzzer, vibration = _real_hardware()
    hardware.set_state("BAD", alert=True)
    assert leds["led_red"].on_calls == 1
    assert leds["led_green"].on_calls == 0
    assert buzzer.on_calls == 2      # 2 tiếng ngắn
    assert vibration.on_calls == 1


def test_real_bad_without_alert_lights_red_but_stays_silent():
    """Ca hồi quy: đổi sang BAD trong cooldown — đèn đỏ, không tiếng."""
    hardware, leds, buzzer, vibration = _real_hardware()
    hardware.set_state("BAD", alert=False)
    assert leds["led_red"].on_calls == 1
    assert buzzer.on_calls == 0
    assert vibration.on_calls == 0


def test_real_break_without_alert_stays_silent():
    hardware, _leds, buzzer, _vibration = _real_hardware()
    hardware.set_state("BREAK", alert=False)
    assert buzzer.on_calls == 0


def test_real_break_with_alert_beeps_three_times():
    hardware, _leds, buzzer, _vibration = _real_hardware()
    hardware.set_state("BREAK", alert=True)
    assert buzzer.on_calls == 3


@pytest.mark.parametrize(
    "state,led",
    [("GOOD", "led_green"), ("WARN", "led_yellow"), ("BAD", "led_red")],
)
def test_real_each_state_lights_exactly_one_led(state, led):
    hardware, leds, _buzzer, _vibration = _real_hardware()
    hardware.set_state(state, alert=False)
    for name, device in leds.items():
        assert device.on_calls == (1 if name == led else 0), name


def test_real_absent_turns_every_led_off_and_is_silent():
    hardware, leds, buzzer, vibration = _real_hardware()
    hardware.set_state("ABSENT", alert=True)
    assert all(device.on_calls == 0 for device in leds.values())
    assert all(device.off_calls >= 1 for device in leds.values())
    assert buzzer.on_calls == 0
    assert vibration.on_calls == 0


def test_real_one_argument_call_keeps_old_behaviour():
    """Tương thích ngược: ``set_state(x)`` cũ vẫn kêu như trước."""
    hardware, _leds, buzzer, _vibration = _real_hardware()
    hardware.set_state("BAD")
    assert buzzer.on_calls == 2


def test_real_alert_flag_respects_buzzer_disabled():
    hardware, _leds, buzzer, _vibration = _real_hardware()
    hardware._config = FakeConfig(buzzer_enabled=False, vibration_enabled=False)
    hardware.set_state("BAD", alert=True)
    assert buzzer.on_calls == 0
    assert _vibration.on_calls == 0


def test_real_unknown_state_is_ignored():
    hardware, leds, buzzer, _vibration = _real_hardware()
    hardware.set_state("KHONG_TON_TAI", alert=True)
    assert buzzer.on_calls == 0
    assert all(device.on_calls == 0 for device in leds.values())


# ---------------------------------------------------------------------------
# GpioMockHardware
# ---------------------------------------------------------------------------

def _mock_hardware():
    hardware = GpioMockHardware()
    devices = {name: Recorder() for name in ("led_green", "led_yellow", "led_red")}
    devices["buzzer"] = Recorder()
    hardware._devices = devices
    hardware._mock_ready = True
    return hardware, devices


def test_mock_bad_without_alert_stays_silent():
    hardware, devices = _mock_hardware()
    hardware.set_state("BAD", alert=False)
    assert devices["led_red"].on_calls == 1
    assert devices["buzzer"].on_calls == 0


def test_mock_bad_with_alert_beeps():
    hardware, devices = _mock_hardware()
    hardware.set_state("BAD", alert=True)
    assert devices["led_red"].on_calls == 1
    assert devices["buzzer"].on_calls == 2


def test_mock_break_without_alert_stays_silent():
    hardware, devices = _mock_hardware()
    hardware.set_state("BREAK", alert=False)
    assert devices["buzzer"].on_calls == 0


def test_mock_one_argument_call_keeps_old_behaviour():
    hardware, devices = _mock_hardware()
    hardware.set_state("BAD")
    assert devices["buzzer"].on_calls == 2


# ---------------------------------------------------------------------------
# NullHardware và hợp đồng chung
# ---------------------------------------------------------------------------

def test_null_hardware_accepts_alert_flag():
    hardware = NullHardware()
    hardware.set_state("BAD", alert=False)
    hardware.set_state("BAD", alert=True)
    hardware.set_state("BAD")
    hardware.close()


def test_every_state_is_accepted_with_both_flags():
    hardware, _leds, _buzzer, _vibration = _real_hardware()
    for state in STATES:
        hardware.set_state(state, alert=True)
        hardware.set_state(state, alert=False)


def test_hardware_uses_keyword_only_alert():
    """``alert`` phải là keyword-only để không ai truyền nhầm vị trí."""
    hardware, _leds, _buzzer, _vibration = _real_hardware()
    with pytest.raises(TypeError):
        hardware.set_state("BAD", True)
