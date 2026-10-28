"""Unit test cho ``scripts/hw_selftest.py``.

Bài tự kiểm tra là công cụ người dùng chạy tay, nên test chỉ khoá những gì
kiểm được trên PC: bảng kết quả, mã thoát, việc chạy hết các mục dù có lỗi,
và việc tôn trọng ``--no-gpio``. Không có test nào xác nhận đèn sáng hay
buzzer kêu — điều đó chỉ mắt/ tai người mới biết.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_SCRIPT = _REPO_ROOT / "scripts" / "hw_selftest.py"


def _load_script():
    """Nạp script như một module để test hàm bên trong."""
    spec = importlib.util.spec_from_file_location("hw_selftest_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hw = _load_script()


class FakeDevice:
    """Thiết bị gpiozero giả: ghi lại bật/tắt và lỗi khởi tạo."""

    def __init__(self, pin, *, fail_on_init=False, fail_on_on=False):
        self.pin = pin
        self.on_calls = 0
        self.off_calls = 0
        self.closed = False
        self._fail_on_init = fail_on_init
        self._fail_on_on = fail_on_on
        if fail_on_init:
            raise RuntimeError("GPIO busy")

    def on(self):
        if self._fail_on_on:
            raise RuntimeError("mất chân khi bật")
        self.on_calls += 1

    def off(self):
        self.off_calls += 1

    def close(self):
        self.closed = True


class FakeGpiozero:
    """Đứng thay module ``gpiozero``, có ``LED``/``Buzzer``/``DistanceSensor``."""

    def __init__(self, *, fail_pins=(), fail_on_on=False):
        self.devices: list[FakeDevice] = []
        self.fail_pins = set(fail_pins)
        self.fail_on_on = fail_on_on

    def _make(self, pin):
        device = FakeDevice(
            pin,
            fail_on_init=pin in self.fail_pins,
            fail_on_on=self.fail_on_on,
        )
        self.devices.append(device)
        return device

    def LED(self, pin):
        return self._make(pin)

    def Buzzer(self, pin):
        return self._make(pin)


class FakeDistanceSensor(FakeDevice):
    """``DistanceSensor`` giả: ``distance`` tính bằng mét, có thể ném lỗi."""

    def __init__(self, pin, *, distances, fail_after=None):
        super().__init__(pin)
        self._distances = list(distances)
        self._fail_after = fail_after
        self._reads = 0

    @property
    def distance(self):
        if self._fail_after is not None and self._reads >= self._fail_after:
            raise RuntimeError("no echo received")
        self._reads += 1
        if not self._distances:
            raise RuntimeError("no echo received")
        return self._distances.pop(0)


class FakeGpiozeroWithDistance(FakeGpiozero):
    def __init__(self, *, distances, **kwargs):
        super().__init__(**kwargs)
        self._distances = distances

    def DistanceSensor(self, echo, trigger, max_distance=None, queue_len=None):
        device = FakeDistanceSensor(
            (trigger, echo), distances=self._distances
        )
        self.devices.append(device)
        return device


# ---------------------------------------------------------------------------
# Từng linh kiện
# ---------------------------------------------------------------------------

def test_check_led_turns_on_then_off():
    gpio = FakeGpiozero()
    slept: list[float] = []
    result = hw.check_led(
        "LED xanh", 17, seconds=0.5, sleep=slept.append, out=lambda *_: None,
        gpiozero=gpio,
    )
    assert result.ok
    assert gpio.devices[0].on_calls == 1
    assert gpio.devices[0].off_calls == 1
    assert slept == [0.5]
    assert result.name == "LED xanh (GPIO17)"


def test_check_led_no_gpio_does_not_touch_pins():
    gpio = FakeGpiozero()
    result = hw.check_led(
        "LED xanh", 17, sleep=lambda *_: None, out=lambda *_: None,
        no_gpio=True, gpiozero=gpio,
    )
    assert result.status == hw.ABSENT
    assert gpio.devices == []


def test_check_led_reports_unavailable_pin():
    gpio = FakeGpiozero(fail_pins={17})
    result = hw.check_led(
        "LED xanh", 17, sleep=lambda *_: None, out=lambda *_: None,
        gpiozero=gpio,
    )
    assert result.status == hw.ABSENT
    assert "GPIO busy" in result.detail


def test_check_led_reports_error_while_on():
    gpio = FakeGpiozero(fail_on_on=True)
    result = hw.check_led(
        "LED đỏ", 22, sleep=lambda *_: None, out=lambda *_: None,
        gpiozero=gpio,
    )
    assert result.status == hw.ERROR


def test_check_led_without_gpiozero_is_absent():
    result = hw.check_led(
        "LED xanh", 17, sleep=lambda *_: None, out=lambda *_: None,
        gpiozero=None,
    )
    assert result.status == hw.ABSENT


def test_check_buzzer_pulses_expected_number_of_times():
    gpio = FakeGpiozero()
    result = hw.check_buzzer(
        18, times=3, sleep=lambda *_: None, out=lambda *_: None,
        gpiozero=gpio,
    )
    assert result.ok
    assert gpio.devices[0].on_calls == 3
    assert gpio.devices[0].off_calls == 3


def test_check_vibration_runs_motor():
    gpio = FakeGpiozero()
    result = hw.check_vibration(
        23, sleep=lambda *_: None, out=lambda *_: None, gpiozero=gpio,
    )
    assert result.ok
    assert gpio.devices[0].on_calls == 1


# ---------------------------------------------------------------------------
# Siêu âm
# ---------------------------------------------------------------------------

def test_ultrasonic_prints_every_reading_and_median():
    gpio = FakeGpiozeroWithDistance(distances=[0.30, 0.31, 0.32, 0.33, 0.34])
    lines: list[str] = []
    result = hw.check_ultrasonic(
        5, 6, reads=5, sleep=lambda *_: None, out=lines.append, gpiozero=gpio,
    )
    assert result.ok
    assert "31.0 cm" in result.detail or "32.0 cm" in result.detail
    printed = "\n".join(lines)
    assert "lần  1" in printed
    assert "lần  5" in printed
    assert "cm" in printed


def test_ultrasonic_reports_no_echo_per_reading():
    gpio = FakeGpiozeroWithDistance(distances=[])
    lines: list[str] = []
    result = hw.check_ultrasonic(
        5, 6, reads=3, sleep=lambda *_: None, out=lines.append, gpiozero=gpio,
    )
    assert result.status == hw.ERROR
    assert "no echo" in "\n".join(lines)
    assert "3/3" in result.detail


def test_ultrasonic_marks_out_of_range_reading_as_dropped():
    gpio = FakeGpiozeroWithDistance(distances=[3.0])  # 300 cm
    lines: list[str] = []
    result = hw.check_ultrasonic(
        5, 6, reads=1, sleep=lambda *_: None, out=lines.append, gpiozero=gpio,
    )
    assert result.status == hw.ERROR
    assert "ngoài dải hợp lệ" in "\n".join(lines)


def test_ultrasonic_succeeds_with_one_valid_reading_among_failures():
    gpio = FakeGpiozeroWithDistance(distances=[0.40])
    result = hw.check_ultrasonic(
        5, 6, reads=3, sleep=lambda *_: None, out=lambda *_: None,
        gpiozero=gpio,
    )
    assert result.ok
    assert "1/3" in result.detail


def test_ultrasonic_no_gpio_opens_nothing():
    gpio = FakeGpiozeroWithDistance(distances=[0.3])
    result = hw.check_ultrasonic(
        5, 6, sleep=lambda *_: None, out=lambda *_: None,
        no_gpio=True, gpiozero=gpio,
    )
    assert result.status == hw.ABSENT
    assert gpio.devices == []


# ---------------------------------------------------------------------------
# Toàn bộ bài chạy
# ---------------------------------------------------------------------------

def _run_all(monkeypatch, gpio, **kwargs):
    monkeypatch.setattr(hw, "_import_gpiozero", lambda: (gpio, None))
    lines: list[str] = []
    code = hw.run(
        config_path=None, sleep=lambda *_: None, out=lines.append, **kwargs
    )
    return code, "\n".join(lines)


def test_run_returns_zero_when_all_devices_ok(monkeypatch):
    gpio = FakeGpiozeroWithDistance(distances=[0.4] * 10)
    code, output = _run_all(monkeypatch, gpio)
    assert code == 0
    assert "TỰ KIỂM TRA PHẦN CỨNG" in output
    assert "KẾT LUẬN: tất cả linh kiện" in output
    for name in ("LED xanh", "LED vàng", "LED đỏ", "Buzzer", "Mô-tơ rung"):
        assert name in output


def test_run_continues_after_missing_device_and_returns_nonzero(monkeypatch):
    """LED xanh không dựng được, nhưng các mục sau vẫn phải chạy hết."""
    gpio = FakeGpiozeroWithDistance(distances=[0.4] * 10, fail_pins={17})
    code, output = _run_all(monkeypatch, gpio)
    assert code == 1
    assert "vắng" in output
    # Buzzer/rung/siêu âm vẫn được thử: ít nhất 3 thiết bị khác đã dựng.
    assert len(gpio.devices) >= 4
    assert "HC-SR04" in output


def test_run_without_gpiozero_runs_to_the_end_and_returns_nonzero(monkeypatch):
    """PC không có gpiozero: không traceback, vẫn in đủ bảng."""
    monkeypatch.setattr(
        hw, "_import_gpiozero", lambda: (None, "không import được gpiozero (test)")
    )
    lines: list[str] = []
    code = hw.run(config_path=None, sleep=lambda *_: None, out=lines.append)
    output = "\n".join(lines)
    assert code == 1
    assert "không import được gpiozero" in output
    for name in ("LED xanh", "LED vàng", "LED đỏ", "Buzzer", "Mô-tơ rung",
                 "HC-SR04"):
        assert name in output


def test_run_no_gpio_mode_never_imports_gpio(monkeypatch):
    def boom():
        raise AssertionError("--no-gpio không được import gpiozero")

    monkeypatch.setattr(hw, "_import_gpiozero", boom)
    lines: list[str] = []
    code = hw.run(
        no_gpio=True, config_path=None, sleep=lambda *_: None,
        out=lines.append,
    )
    output = "\n".join(lines)
    assert code == 1
    assert "--no-gpio" in output
    assert output.count("vắng") >= 6


def test_run_with_bad_config_still_runs(monkeypatch):
    gpio = FakeGpiozeroWithDistance(distances=[0.4] * 10)
    monkeypatch.setattr(hw, "_import_gpiozero", lambda: (gpio, None))
    lines: list[str] = []
    code = hw.run(
        config_path="khong_ton_tai.yaml", sleep=lambda *_: None,
        out=lines.append,
    )
    assert code == 0
    assert "không nạp được cấu hình" in "\n".join(lines)


def test_run_print_result_table_has_each_device_row(monkeypatch):
    gpio = FakeGpiozeroWithDistance(distances=[0.4] * 10)
    _, output = _run_all(monkeypatch, gpio)
    assert "Linh kiện" in output
    assert output.count("ok") >= 6


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_main_no_gpio_returns_nonzero_on_pc(capsys):
    code = hw.main(["--no-gpio", "--config", "khong_ton_tai.yaml"])
    captured = capsys.readouterr()
    assert code == 1
    assert "TỰ KIỂM TRA PHẦN CỨNG" in captured.out


def test_main_returns_zero_when_all_ok(monkeypatch, capsys):
    gpio = FakeGpiozeroWithDistance(distances=[0.4] * 10)
    monkeypatch.setattr(hw, "_import_gpiozero", lambda: (gpio, None))
    # ``main`` gọi ``run`` không truyền ``sleep``, nên chặn thẳng ``time.sleep``
    # mà script dùng; đổi hằng số thời lượng là vô ích vì chúng đã bind vào
    # giá trị mặc định của tham số lúc định nghĩa hàm.
    monkeypatch.setattr(hw.time, "sleep", lambda *_: None)
    code = hw.main(["--config", "khong_ton_tai.yaml"])
    assert code == 0


def test_main_rejects_unknown_argument():
    with pytest.raises(SystemExit) as excinfo:
        hw.main(["--khong-co-co-nay"])
    assert excinfo.value.code != 0


# ---------------------------------------------------------------------------
# Chỉ chạy khi máy có gpiozero thật
# ---------------------------------------------------------------------------

def test_real_gpiozero_led_on_mock_factory():
    gpiozero = pytest.importorskip("gpiozero")
    from gpiozero import Device
    from gpiozero.pins.mock import MockFactory

    original_factory = Device.pin_factory
    Device.pin_factory = MockFactory()
    try:
        gpio = gpiozero
        result = hw.check_led(
            "LED xanh", 17, seconds=0.01, out=lambda *_: None, gpiozero=gpio,
        )
        assert result.ok
    finally:
        Device.pin_factory = original_factory
