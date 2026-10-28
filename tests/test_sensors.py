"""Unit test cho ``sensors.py`` (spec v2 §5.8).

Ba tầng được kiểm riêng:

- Hàm thuần :func:`aggregate_distance` và :func:`apply_distance` — không cần
  thư viện nào, chạy được trên mọi máy.
- :class:`FakeSensor` và :class:`UltrasonicSensor` ở mức **chỉ-ghi-log** khi
  không có ``gpiozero`` (đúng trạng thái PC của dự án).
- Đường dựng thiết bị thật chỉ chạy khi ``gpiozero`` có mặt
  (``pytest.importorskip``). Theo spec §5.7, ``MockPin`` không giả lập được
  khoảng cách nên không có test nào ở đây giả lập giá trị siêu âm ở tầng pin.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.classifier import (  # noqa: E402
    HEAD_DOWN,
    TOO_CLOSE,
)
from posture_monitor.config import Config, SensorsConfig  # noqa: E402
from posture_monitor.sensors import (  # noqa: E402
    MAX_VALID_CM,
    MIN_VALID_CM,
    FakeSensor,
    NullSensor,
    Sensor,
    UltrasonicSensor,
    aggregate_distance,
    apply_distance,
    create_sensor,
)


# ---------------------------------------------------------------------------
# aggregate_distance
# ---------------------------------------------------------------------------

def test_median_of_five_readings():
    assert aggregate_distance([30, 32, 31, 33, 31]) == 31


def test_median_is_robust_to_one_outlier():
    assert aggregate_distance([30, 31, 32, 33, 150]) == 32


def test_out_of_range_values_are_dropped():
    # 1,5 cm và 250 cm nằm ngoài [2, 200] nên không được tham gia trung vị.
    assert aggregate_distance([1.5, 40, 42, 250]) == 41


def test_boundary_values_are_kept():
    assert aggregate_distance([MIN_VALID_CM]) == MIN_VALID_CM
    assert aggregate_distance([MAX_VALID_CM]) == MAX_VALID_CM
    assert aggregate_distance([1.99, 200.01]) is None


def test_none_nan_and_inf_are_ignored():
    assert aggregate_distance([None, float("nan"), float("inf"), 25]) == 25


def test_no_valid_sample_returns_none_not_zero():
    """0 cm sẽ bị hiểu nhầm là ngồi sát camera; phải là ``None``."""
    assert aggregate_distance([]) is None
    assert aggregate_distance([None, None]) is None
    assert aggregate_distance([0, 500]) is None


# ---------------------------------------------------------------------------
# apply_distance — hợp nhất với nhãn camera
# ---------------------------------------------------------------------------

def test_none_distance_leaves_labels_untouched():
    labels = frozenset({HEAD_DOWN})
    assert apply_distance(labels, None, 35.0) == labels


def test_near_distance_adds_too_close():
    assert TOO_CLOSE in apply_distance(frozenset(), 20.0, 35.0)


def test_far_distance_does_not_add_too_close():
    assert TOO_CLOSE not in apply_distance(frozenset(), 60.0, 35.0)


def test_distance_exactly_at_threshold_is_not_too_close():
    assert apply_distance(frozenset(), 35.0, 35.0) == frozenset()


def test_far_distance_does_not_remove_camera_too_close():
    """Hai nguồn là phép "hoặc": camera thấy gần thì vẫn là gần."""
    labels = frozenset({TOO_CLOSE, HEAD_DOWN})
    assert apply_distance(labels, 120.0, 35.0) == labels


def test_none_distance_does_not_remove_camera_too_close():
    labels = frozenset({TOO_CLOSE})
    assert apply_distance(labels, None, 35.0) == labels


def test_other_labels_are_preserved():
    labels = frozenset({HEAD_DOWN, "LEAN", "SHOULDER_TILT"})
    merged = apply_distance(labels, 10.0, 35.0)
    assert merged == labels | {TOO_CLOSE}


def test_nan_distance_is_treated_as_no_sample():
    labels = frozenset({HEAD_DOWN})
    assert apply_distance(labels, float("nan"), 35.0) == labels


def test_returns_frozenset():
    assert isinstance(apply_distance(set(), 10.0, 35.0), frozenset)


@pytest.mark.parametrize("limit", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_min_distance_raises(limit):
    with pytest.raises(ValueError):
        apply_distance(frozenset(), 20.0, limit)


# ---------------------------------------------------------------------------
# FakeSensor / NullSensor
# ---------------------------------------------------------------------------

def test_fake_sensor_walks_through_values():
    sensor = FakeSensor([10.0, 20.0, None])
    assert sensor.read() == 10.0
    assert sensor.read() == 20.0
    assert sensor.read() is None
    sensor.close()


def test_fake_sensor_repeats_last_value_by_default():
    sensor = FakeSensor([42.0])
    sensor.read()
    assert sensor.read() == 42.0
    assert sensor.read() == 42.0


def test_fake_sensor_can_report_lost_signal():
    sensor = FakeSensor([42.0], repeat_last=False)
    assert sensor.read() == 42.0
    assert sensor.read() is None


def test_null_sensor_always_none():
    sensor = NullSensor()
    assert sensor.read() is None
    sensor.close()


def test_sensors_share_the_sensor_interface():
    assert isinstance(FakeSensor([]), Sensor)
    assert isinstance(NullSensor(), Sensor)


# ---------------------------------------------------------------------------
# UltrasonicSensor thiếu gpiozero (trạng thái PC)
# ---------------------------------------------------------------------------

def test_ultrasonic_without_gpiozero_returns_none_and_does_not_crash(
    monkeypatch,
):
    """PC không cài gpiozero: mọi thứ phải xuống cấp an toàn, không raise."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "gpiozero" or name.startswith("gpiozero."):
            raise ModuleNotFoundError("No module named 'gpiozero'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    sensor = UltrasonicSensor(Config())
    try:
        assert sensor.read() is None
        sensor.close()
    finally:
        sensor.close()


def test_ultrasonic_reads_pins_from_config():
    config = Config()
    config.hardware.pins.trig = 12
    config.hardware.pins.echo = 13
    sensor = UltrasonicSensor(config, autostart=False)
    try:
        assert sensor._trig == 12
        assert sensor._echo == 13
    finally:
        sensor.close()


def test_ultrasonic_defaults_pins_without_config():
    sensor = UltrasonicSensor(None, autostart=False)
    try:
        assert sensor._trig == 5
        assert sensor._echo == 6
    finally:
        sensor.close()


def test_ultrasonic_rejects_invalid_interval():
    with pytest.raises(ValueError):
        UltrasonicSensor(Config(), interval_s=0)


def test_ultrasonic_rejects_invalid_sample_count():
    with pytest.raises(ValueError):
        UltrasonicSensor(Config(), samples=0)


def test_ultrasonic_rejects_invalid_sample_gap():
    with pytest.raises(ValueError):
        UltrasonicSensor(Config(), sample_gap_s=-0.1)


def test_ultrasonic_spreads_reads_within_a_sample(monkeypatch):
    """Hai phép đo trong cùng một mẫu phải cách nhau ``sample_gap_s``.

    ``DistanceSensor`` của gpiozero đo ở luồng nền và ``queue_len=1`` chỉ giữ
    kết quả mới nhất; đọc dồn liền sẽ nhận đúng một trị số 5 lần, khiến trung
    vị không lọc được gì.
    """
    reads: list[float] = []
    sensor = UltrasonicSensor(Config(), samples=3, sample_gap_s=0.05,
                              autostart=False)
    monkeypatch.setattr(
        sensor, "_read_once", lambda: reads.append(time.monotonic()) or 40.0
    )
    try:
        assert sensor._collect_samples() == [40.0, 40.0, 40.0]
    finally:
        sensor.close()
    assert len(reads) == 3
    gaps = [later - earlier for earlier, later in zip(reads, reads[1:])]
    assert all(gap >= 0.04 for gap in gaps), gaps


def test_ultrasonic_background_thread_updates_last_value(monkeypatch):
    """Luồng đọc phải gọi thiết bị và lưu trung vị, kể cả khi thiếu gpiozero.

    Thiết bị được bơm thẳng vào đối tượng (không qua pin) để test đúng hành vi
    gộp mẫu — theo spec §5.7, đây là cách kiểm giá trị siêu âm duy nhất.
    """

    class StubDevice:
        def __init__(self, values):
            self._values = list(values)
            self.closed = False

        @property
        def distance(self):
            return self._values.pop(0) if self._values else 0.0

        def close(self):
            self.closed = True

    # Mét → cm: 30, 31, 32, 33 hợp lệ (trung vị 31,5); 0,005 m = 0,5 cm bị loại.
    stub = StubDevice([0.30, 0.31, 0.32, 0.005, 0.33])
    sensor = UltrasonicSensor(Config(), interval_s=0.02, samples=5,
                              sample_gap_s=0, autostart=False)
    sensor._device = stub
    stub_closed = []
    stub.close = lambda: stub_closed.append(True)

    import threading

    thread = threading.Thread(target=sensor._run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 2.0
        while sensor.read() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert sensor.read() == pytest.approx(31.5)
    finally:
        sensor.close()
        thread.join(2.0)
    assert stub_closed


# ---------------------------------------------------------------------------
# create_sensor
# ---------------------------------------------------------------------------

def test_create_sensor_disabled_returns_null_sensor_and_opens_no_pin():
    config = Config(sensors=SensorsConfig(ultrasonic_enabled=False))
    sensor = create_sensor(config)
    try:
        assert isinstance(sensor, NullSensor)
        assert sensor.read() is None
    finally:
        sensor.close()


def test_create_sensor_enabled_returns_ultrasonic_when_gpiozero_missing(
    monkeypatch,
):
    """Khi gpiozero thiếu, vẫn trả đối tượng hợp lệ đọc ``None``."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "gpiozero" or name.startswith("gpiozero."):
            raise ModuleNotFoundError("No module named 'gpiozero'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    sensor = create_sensor(Config())
    try:
        assert isinstance(sensor, UltrasonicSensor)
        assert sensor.read() is None
    finally:
        sensor.close()


def test_create_sensor_without_config_defaults_to_enabled():
    sensor = create_sensor(None)
    try:
        assert isinstance(sensor, UltrasonicSensor)
    finally:
        sensor.close()


# ---------------------------------------------------------------------------
# Chỉ chạy khi máy có gpiozero thật
# ---------------------------------------------------------------------------

def test_ultrasonic_builds_distance_sensor_with_mock_factory():
    """Dựng ``DistanceSensor`` trên MockFactory: chỉ cần khởi tạo được.

    Không kiểm giá trị (``MockPin`` không giả lập khoảng cách — spec §5.7),
    chỉ kiểm rằng thiếu echo không làm chết luồng và ``read()`` vẫn trả
    ``None`` thay vì raise.
    """
    gpiozero = pytest.importorskip("gpiozero")
    from gpiozero import Device
    from gpiozero.pins.mock import MockFactory

    original_factory = Device.pin_factory
    Device.pin_factory = MockFactory()
    try:
        sensor = UltrasonicSensor(Config(), interval_s=0.05)
        try:
            time.sleep(0.2)
            assert sensor.read() is None
        finally:
            sensor.close()
    finally:
        Device.pin_factory = original_factory
    assert gpiozero is not None
