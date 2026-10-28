"""Kiểm thử việc đọc và kiểm tra ``config.yaml`` (spec v2 §6)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.config import (  # noqa: E402
    Config,
    ConfigError,
    load_config,
    parse_camera_source,
)

VALID_YAML = """
camera:
  source: usb:0
  width: 640
  height: 480
  view: front
model:
  name: yolo11n-pose
  format: ncnn
  imgsz: 320
  target_fps: 5
  kp_conf_min: 0.5
  export_on_pc: false
tracking:
  enabled: true
  tracker: botsort.yaml
thresholds:
  head_down_ratio: 0.70
  too_close_ratio: 1.25
  shoulder_tilt_deg: 8
  head_tilt_deg: 12
  lean_x: 0.35
  look_away_yaw: 0.5
  neck_angle_drop_deg: 15
timing:
  smooth_window_s: 1.0
  bad_hold_s: 5
  good_hold_s: 2
  alert_cooldown_s: 30
  escalate_after_s: 60
  break_after_min: 45
  absent_reset_s: 120
  drowsy_hold_s: 10
alerts:
  buzzer_enabled: true
  vibration_enabled: true
hardware:
  mock: auto
  pins: {led_green: 17, led_yellow: 27, led_red: 22, buzzer: 18, vibration: 23, trig: 5, echo: 6}
sensors:
  ultrasonic_enabled: true
  min_distance_cm: 35
storage:
  db_path: data/posture.db
  retention_days: 30
web:
  host: 0.0.0.0
  port: 8000
  stream_enabled: false
"""


def _write(tmp_path: Path, text: str, name: str = "config.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Trường hợp hợp lệ
# --------------------------------------------------------------------------


def test_load_valid_config(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, VALID_YAML))

    assert isinstance(config, Config)
    assert config.camera.source == "usb:0"
    assert config.camera.width == 640
    assert config.camera.height == 480
    assert config.camera.view == "front"

    assert config.model.name == "yolo11n-pose"
    assert config.model.format == "ncnn"
    assert config.model.imgsz == 320
    assert config.model.export_on_pc is False

    assert config.tracking.enabled is True
    assert config.tracking.tracker == "botsort.yaml"

    assert config.thresholds.head_down_ratio == pytest.approx(0.70)
    assert config.thresholds.neck_angle_drop_deg == pytest.approx(15.0)

    assert config.timing.bad_hold_s == pytest.approx(5.0)
    assert config.timing.drowsy_hold_s == pytest.approx(10.0)

    assert config.hardware.mock == "auto"
    assert config.hardware.pins.led_green == 17
    assert config.hardware.pins.echo == 6

    assert config.sensors.min_distance_cm == pytest.approx(35.0)
    assert config.storage.db_path == "data/posture.db"
    assert config.web.port == 8000
    assert config.web.stream_enabled is False


def test_repo_config_yaml_is_valid() -> None:
    """config.yaml trong repo phải nạp được (bảo vệ khỏi sửa hỏng)."""
    config = load_config(_REPO_ROOT / "config.yaml")
    assert config.camera.view in ("front", "side")
    assert config.model.export_on_pc is False
    assert hasattr(config, "tracking")


def test_missing_keys_use_defaults(tmp_path: Path) -> None:
    """File chỉ có một mục: các mục còn lại lấy mặc định, không lỗi."""
    config = load_config(_write(tmp_path, "camera:\n  source: picamera\n"))
    defaults = Config()

    assert config.camera.source == "picamera"
    assert config.camera.width == defaults.camera.width
    assert config.model.imgsz == defaults.model.imgsz
    assert config.timing.bad_hold_s == defaults.timing.bad_hold_s
    assert config.hardware.pins.buzzer == defaults.hardware.pins.buzzer


def test_empty_file_uses_all_defaults(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, ""))
    defaults = Config()
    assert config.camera.source == defaults.camera.source
    assert config.model.target_fps == defaults.model.target_fps


# --------------------------------------------------------------------------
# Trường hợp lỗi
# --------------------------------------------------------------------------


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "khong_co.yaml"
    with pytest.raises(FileNotFoundError) as excinfo:
        load_config(missing)
    # Thông báo phải nêu đường dẫn để người dùng sửa được.
    assert "khong_co.yaml" in str(excinfo.value)


def test_wrong_type_for_int_raises_config_error(tmp_path: Path) -> None:
    text = "camera:\n  width: \"640\"\n"
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "camera.width" in str(excinfo.value)


def test_wrong_type_for_float_raises_config_error(tmp_path: Path) -> None:
    text = "thresholds:\n  head_down_ratio: chuoi\n"
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "thresholds.head_down_ratio" in str(excinfo.value)


def test_wrong_type_for_bool_raises_config_error(tmp_path: Path) -> None:
    text = "web:\n  stream_enabled: \"yes\"\n"
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "web.stream_enabled" in str(excinfo.value)


def test_invalid_view_raises_config_error(tmp_path: Path) -> None:
    text = "camera:\n  view: behind\n"
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "camera.view" in str(excinfo.value)


def test_invalid_model_format_raises_config_error(tmp_path: Path) -> None:
    text = "model:\n  format: tensorrt\n"
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, text))


def test_non_mapping_section_raises_config_error(tmp_path: Path) -> None:
    text = "camera: 640\n"
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "camera" in str(excinfo.value)


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "- camera\n- model\n"))


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, "camera: [unclosed\n"))
    assert "YAML" in str(excinfo.value)


def test_invalid_camera_source_raises_config_error(tmp_path: Path) -> None:
    text = "camera:\n  source: usb:abc\n"
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, text))


def test_negative_port_raises_config_error(tmp_path: Path) -> None:
    text = "web:\n  port: 0\n"
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, text))


# --------------------------------------------------------------------------
# Cú pháp camera.source
# --------------------------------------------------------------------------


def test_parse_camera_source_usb() -> None:
    assert parse_camera_source("usb:0") == ("usb", 0)
    assert parse_camera_source("usb:2") == ("usb", 2)


def test_parse_camera_source_picamera() -> None:
    assert parse_camera_source("picamera") == ("picamera", None)


def test_parse_camera_source_file_with_windows_path() -> None:
    kind, value = parse_camera_source(r"file:C:\video\a.mp4")
    assert kind == "file"
    assert value == r"C:\video\a.mp4"


def test_parse_camera_source_rejects_unknown_kind() -> None:
    with pytest.raises(ConfigError):
        parse_camera_source("rtsp://camera")


# --------------------------------------------------------------------------
# camera.onvif (PTZ, cổng HTTP) và camera.speaker (loa, cổng RTSP)
# --------------------------------------------------------------------------
def test_speaker_section_defaults_to_off_with_rtsp_port(tmp_path: Path) -> None:
    """Mặc định: tắt, cổng 554 — **khác** ``camera.onvif.port`` = 80."""
    config = load_config(_write(tmp_path, VALID_YAML))

    speaker = config.camera.speaker
    assert speaker.enabled is False
    assert speaker.host == ""
    assert speaker.port == 554
    assert speaker.stream_path == "/1/2"
    assert config.camera.onvif.port == 80


def test_speaker_and_onvif_ports_do_not_share_one_key(tmp_path: Path) -> None:
    """Đặt ``onvif.port: 80`` không được làm ``speaker.port`` thành 80.

    Đây chính là lỗi mà việc tách schema sửa: trước đây cả hai đọc chung
    ``camera.onvif.port``, nên loa nhận cổng HTTP và không mở được backchannel.
    """
    text = (
        "camera:\n"
        "  source: usb:0\n"
        "  onvif:\n"
        "    port: 80\n"
        "  speaker:\n"
        "    port: 554\n"
    )
    config = load_config(_write(tmp_path, text))

    assert config.camera.onvif.port == 80
    assert config.camera.speaker.port == 554


def test_speaker_enabled_without_host_raises_config_error(tmp_path: Path) -> None:
    text = (
        "camera:\n"
        "  source: usb:0\n"
        "  speaker:\n"
        "    enabled: true\n"
        '    host: ""\n'
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "camera.speaker.host" in str(excinfo.value)


def test_speaker_port_out_of_range_raises_config_error(tmp_path: Path) -> None:
    text = "camera:\n  source: usb:0\n  speaker:\n    port: 70000\n"
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "camera.speaker.port" in str(excinfo.value)


def test_speaker_host_with_rtsp_url_is_rejected_and_redacted(
    tmp_path: Path,
) -> None:
    """Dán cả URL RTSP vào ``host`` → lỗi, và mật khẩu trong URL phải bị che."""
    text = (
        "camera:\n"
        "  source: usb:0\n"
        "  speaker:\n"
        "    enabled: true\n"
        '    host: "rtsp://admin:mat-khau-gia@192.0.2.55:554/1/2"\n'
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))

    message = str(excinfo.value)
    assert "camera.speaker.host" in message
    assert "mat-khau-gia" not in message


