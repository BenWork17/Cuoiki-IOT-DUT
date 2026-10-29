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
    CAMERA_SOURCE_ENV,
    ONVIF_PASSWORD_ENV,
    Config,
    ConfigError,
    load_config,
    onvif_credentials,
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


def test_repo_config_yaml_enables_speaker(monkeypatch) -> None:
    """``config.yaml`` được commit phải bật loa — nếu không, bản clone mất tính năng.

    Đổi 29/10/2026: Pi đang phát tiếng được (``SPEAK_OK``, 56 gói PCMA) trong
    khi ``config.yaml`` trong git ghi ``enabled: false``, tức Pi chạy một cấu
    hình **không có trong git**: ai clone repo sẽ mất loa và không ai tái lập
    được bản demo. Bài này khoá lại sự khớp giữa file commit và tính năng đã
    kiểm chứng.
    """
    monkeypatch.delenv(CAMERA_SOURCE_ENV, raising=False)
    config = load_config(_REPO_ROOT / "config.yaml")
    assert config.camera.speaker.enabled is True
    assert config.camera.speaker.port == 554, "cổng RTSP, không phải 80 của ONVIF"


def test_repo_config_yaml_loads_without_any_env(monkeypatch, caplog) -> None:
    """Bản clone mới (không đặt biến môi trường) phải khởi động được.

    Đây là chống hồi quy môi trường cho thay đổi 29/10/2026: bật
    ``camera.speaker.enabled: true`` trong ``config.yaml`` (``source: usb:0``)
    mà vẫn ném ``ConfigError`` khi thiếu host thì app **không khởi động** trên
    máy chưa đặt ``POSTURE_CAMERA_SOURCE``. Nạp phải thành công, và phần thiếu
    được báo bằng đúng một dòng WARNING.
    """
    monkeypatch.delenv(CAMERA_SOURCE_ENV, raising=False)
    monkeypatch.delenv(ONVIF_PASSWORD_ENV, raising=False)

    with caplog.at_level("WARNING", logger="posture_monitor.config"):
        config = load_config(_REPO_ROOT / "config.yaml")

    assert config.camera.speaker.enabled is True
    assert config.camera.source == "usb:0"

    speaker_warnings = [
        record.getMessage()
        for record in caplog.records
        if record.name == "posture_monitor.config"
        and record.levelname == "WARNING"
        and "camera.speaker.enabled" in record.getMessage()
    ]
    assert len(speaker_warnings) == 1, caplog.text
    assert "không phát tiếng" in speaker_warnings[0]


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


@pytest.mark.parametrize("value", [10**400, -(10**400)])
def test_float_out_of_range_raises_config_error(tmp_path: Path, value: int) -> None:
    """Số nguyên vượt dải float phải thành ConfigError, không phải OverflowError."""
    text = f"face:\n  interval_s: {value}\n"
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "face.interval_s" in str(excinfo.value)


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
    """Tiền tố lạ vẫn bị từ chối.

    Đổi 29/10/2026: trước đây bài này dùng ``"rtsp://camera"`` làm ví dụ "loại
    không hỗ trợ", nhưng từ khi URL RTSP trần được chấp nhận (xem
    ``test_parse_bare_rtsp_url_keeps_url_intact``) thì nó là cú pháp **hợp lệ**.
    Dùng ``tcp:`` làm ví dụ thật cho loại không hỗ trợ.
    """
    with pytest.raises(ConfigError):
        parse_camera_source("tcp://camera")


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


def test_speaker_enabled_without_host_warns_but_still_loads(
    tmp_path: Path, caplog
) -> None:
    """``enabled: true`` + không suy được host → **cảnh báo**, cấu hình vẫn nạp.

    Đổi 29/10/2026: trước đây ca này ném ``ConfigError``. Lý do đổi:
    ``config.yaml`` được commit đặt ``source: usb:0`` và nay bật
    ``camera.speaker.enabled: true``, nên ném lỗi ở đây làm app không khởi
    động được trên mọi máy không đặt ``POSTURE_CAMERA_SOURCE`` — hồi quy môi
    trường chứ không phải lỗi người dùng. Theo cùng hợp đồng đã áp cho
    ``face.enabled: true`` + ``match_threshold: null``: thiếu điều kiện tùy
    chọn thì cảnh báo, không chặn nạp.

    Bài này vẫn **kiểm** đúng thứ cần kiểm — không chỉ "không ném lỗi":
    cấu hình nạp được, ``enabled`` vẫn true, và có đúng một dòng WARNING nêu
    cả khóa cấu hình lẫn hệ quả "chỉ ghi sự kiện, không phát tiếng".
    """
    text = (
        "camera:\n"
        "  source: usb:0\n"
        "  speaker:\n"
        "    enabled: true\n"
        '    host: ""\n'
    )
    with caplog.at_level("WARNING", logger="posture_monitor.config"):
        config = load_config(_write(tmp_path, text))

    assert config.camera.speaker.enabled is True
    assert config.camera.speaker.host == ""

    warnings = [
        record
        for record in caplog.records
        if record.name == "posture_monitor.config"
        and record.levelname == "WARNING"
        and "camera.speaker.enabled" in record.getMessage()
    ]
    assert len(warnings) == 1, caplog.text
    message = warnings[0].getMessage()
    assert "camera.speaker.host" in message
    assert "không phát tiếng" in message
    assert "POSTURE_CAMERA_SOURCE" in message


def test_speaker_enabled_without_host_loads_when_source_is_rtsp(
    tmp_path: Path, monkeypatch
) -> None:
    """``enabled: true`` + host trống **hợp lệ** khi ``camera.source`` có host.

    Host được suy từ ``camera.source`` ở :func:`speaker_config_from_config`,
    nên chặn ngay lúc nạp sẽ khoá cứng tính năng dù đủ thông tin để suy ra.
    """
    monkeypatch.setenv(
        "POSTURE_CAMERA_SOURCE", "rtsp://admin:mat-khau-gia@192.0.2.77:554/1/2"
    )
    text = (
        "camera:\n"
        "  source: usb:0\n"
        "  speaker:\n"
        "    enabled: true\n"
        '    host: ""\n'
    )
    config = load_config(_write(tmp_path, text))

    assert config.camera.speaker.host == ""
    assert config.camera.source == "rtsp:rtsp://admin:mat-khau-gia@192.0.2.77:554/1/2"


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


# --------------------------------------------------------------------------
# schedule: giờ học quy định (mặc định tắt)
# --------------------------------------------------------------------------


def test_schedule_defaults_to_disabled(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, VALID_YAML))
    assert config.schedule.enabled is False
    assert config.schedule.windows == ()
    # Có mặc định cho cả ba loại, để bật enabled là dùng được ngay.
    assert set(config.schedule.kinds) == {
        "leave_frame",
        "phone",
        "stranger",
    }
    assert config.schedule.kinds["leave_frame"].cooldown_s > 0


def test_schedule_loads_windows_and_kinds(tmp_path: Path) -> None:
    text = (
        "schedule:\n"
        "  enabled: true\n"
        "  windows:\n"
        "    - days: [mon, tue, wed, thu, fri]\n"
        '      start: "19:00"\n'
        '      end: "21:30"\n'
        "    - days: [sat, sun]\n"
        '      start: "08:00"\n'
        '      end: "11:00"\n'
        "  kinds:\n"
        "    phone:\n"
        "      enabled: false\n"
        "      cooldown_s: 45.5\n"
        "      hold_s: 0\n"
    )
    config = load_config(_write(tmp_path, text))

    assert config.schedule.enabled is True
    assert len(config.schedule.windows) == 2
    first = config.schedule.windows[0]
    assert first.days == ("mon", "tue", "wed", "thu", "fri")
    assert (first.start.hour, first.start.minute) == (19, 0)
    assert (first.end.hour, first.end.minute) == (21, 30)
    assert first.overnight is False

    # Tắt riêng "dien thoai" không ảnh hưởng hai loại còn lại.
    assert config.schedule.kinds["phone"].enabled is False
    assert config.schedule.kinds["phone"].cooldown_s == pytest.approx(45.5)
    assert config.schedule.kinds["leave_frame"].enabled is True
    assert config.schedule.kinds["stranger"].enabled is True


def test_schedule_invalid_clock_raises_at_load_time(tmp_path: Path) -> None:
    """Giờ sai định dạng phải lỗi lúc NẠP cấu hình, kèm đúng khóa."""
    text = (
        "schedule:\n"
        "  enabled: true\n"
        "  windows:\n"
        "    - days: [mon]\n"
        '      start: "7h00"\n'
        '      end: "09:00"\n'
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "schedule.windows[0].start" in str(excinfo.value)


def test_schedule_unquoted_clock_reports_yaml_trap(tmp_path: Path) -> None:
    """``start: 19:00`` (không ngoặc kép) bị YAML đọc thành số 1140."""
    text = (
        "schedule:\n"
        "  enabled: true\n"
        "  windows:\n"
        "    - days: [mon]\n"
        "      start: 19:00\n"
        "      end: 21:00\n"
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    message = str(excinfo.value)
    assert "schedule.windows[0].start" in message
    assert "19:00" in message  # gợi ý đặt trong ngoặc kép


def test_schedule_unknown_day_raises(tmp_path: Path) -> None:
    text = (
        "schedule:\n"
        "  enabled: true\n"
        "  windows:\n"
        "    - days: [monday]\n"
        '      start: "19:00"\n'
        '      end: "21:00"\n'
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "schedule.windows[0].days" in str(excinfo.value)


def test_schedule_enabled_without_windows_raises(tmp_path: Path) -> None:
    text = "schedule:\n  enabled: true\n"
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "schedule.windows" in str(excinfo.value)


def test_schedule_unknown_kind_raises(tmp_path: Path) -> None:
    text = "schedule:\n  kinds:\n    sleeping: {enabled: true}\n"
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "schedule.kinds.sleeping" in str(excinfo.value)


def test_schedule_negative_cooldown_raises(tmp_path: Path) -> None:
    text = "schedule:\n  kinds:\n    phone: {cooldown_s: -5}\n"
    with pytest.raises(ConfigError) as excinfo:
        load_config(_write(tmp_path, text))
    assert "schedule.kinds.phone.cooldown_s" in str(excinfo.value)


def test_repo_config_yaml_schedule_section_is_valid() -> None:
    """Mục ``schedule`` trong config.yaml của repo phải nạp được."""
    config = load_config(_REPO_ROOT / "config.yaml")
    assert isinstance(config.schedule.enabled, bool)
    if config.schedule.enabled:
        assert config.schedule.windows





# --------------------------------------------------------------------------
# PTZ: suy host từ camera.source, mật khẩu, và thông điệp khi thiếu cấu hình
# --------------------------------------------------------------------------

SECRET = "mat-khau-ptz-gia"
SECRET_URL = f"rtsp://admin:{SECRET}@192.0.2.77:554/1/2"


def _write_source(tmp_path: Path, source_yaml: str, extra: str = "") -> Path:
    """File cấu hình tối thiểu có đúng ``camera.source`` cần khảo sát."""
    text = f"camera:\n  source: {source_yaml}\n" + extra
    return _write(tmp_path, text)


def test_onvif_host_duoc_suy_ra_tu_camera_source_rtsp(tmp_path, monkeypatch):
    """``onvif.host`` trống + nguồn RTSP → host lấy từ URL nguồn.

    Đây là quy ước "một địa chỉ camera, một nơi khai": người dùng chỉ đặt
    ``POSTURE_CAMERA_SOURCE`` là đủ cho cả xem ảnh lẫn điều khiển PTZ.
    """
    monkeypatch.delenv(ONVIF_PASSWORD_ENV, raising=False)
    monkeypatch.setenv(CAMERA_SOURCE_ENV, SECRET_URL)

    config = load_config(_write_source(tmp_path, "usb:0"))

    assert config.camera.source == f"rtsp:{SECRET_URL}"
    assert config.camera.onvif.host == "192.0.2.77"
    assert config.camera.onvif.enabled is True, "có host + mật khẩu là tự bật"
    assert SECRET not in repr(config), "repr() lọt vào log — phải che"


def test_onvif_host_trong_camera_source_khong_phai_rtsp_thi_tat(tmp_path, monkeypatch):
    """Nguồn không mang host (usb/picamera) → không suy được, PTZ tắt."""
    monkeypatch.delenv(ONVIF_PASSWORD_ENV, raising=False)
    monkeypatch.setenv(CAMERA_SOURCE_ENV, "usb:0")

    config = load_config(_write_source(tmp_path, "usb:0"))

    assert config.camera.onvif.host == ""
    assert config.camera.onvif.enabled is False


def test_onvif_host_trong_config_thang_camera_source(tmp_path, monkeypatch):
    """``camera.onvif.host`` điền tay là đường ghi đè, không bị suy lại.

    Dùng cho trường hợp camera PTZ nằm ở host khác luồng ảnh (hiếm nhưng
    có thật với camera đặt sau đầu ghi).
    """
    monkeypatch.setenv(ONVIF_PASSWORD_ENV, SECRET)
    monkeypatch.setenv(CAMERA_SOURCE_ENV, SECRET_URL)

    path = _write(
        tmp_path,
        "camera:\n"
        "  source: usb:0\n"
        "  onvif:\n"
        "    enabled: true\n"
        "    host: 192.0.2.99\n",
    )
    config = load_config(path)

    assert config.camera.onvif.host == "192.0.2.99"
    assert config.camera.onvif.enabled is True


def test_onvif_tu_bat_khi_chi_co_source_co_mat_khau(tmp_path, monkeypatch):
    """Không khai gì ở ``camera.onvif`` + nguồn RTSP có mật khẩu → PTZ chạy.

    Đây chính là lỗi người dùng gặp: bấm nút mà không có gì xảy ra vì cấu
    hình cũ bắt phải bật tay và chép lại IP lần thứ hai.
    """
    monkeypatch.delenv(ONVIF_PASSWORD_ENV, raising=False)
    monkeypatch.setenv(CAMERA_SOURCE_ENV, SECRET_URL)

    config = load_config(_write_source(tmp_path, "usb:0"))

    assert config.camera.onvif.enabled is True
    assert config.camera.onvif.host == "192.0.2.77"


def test_onvif_tu_tat_khi_source_khong_co_mat_khau(tmp_path, monkeypatch):
    """Nguồn RTSP không kèm tài khoản + không có biến mật khẩu → tắt, không lỗi.

    Chương trình vẫn xem được ảnh; chỉ PTZ tắt và ``/api/ptz`` sẽ nói rõ vì sao.
    """
    monkeypatch.delenv(ONVIF_PASSWORD_ENV, raising=False)
    monkeypatch.setenv(CAMERA_SOURCE_ENV, "rtsp://192.0.2.77:554/1/2")

    config = load_config(_write_source(tmp_path, "usb:0"))

    assert config.camera.onvif.host == "192.0.2.77"
    assert config.camera.onvif.enabled is False


def test_onvif_enabled_true_thieu_ca_hai_nguon_mat_khau_bao_ro_cach_sua(
    tmp_path, monkeypatch
):
    """``enabled: true`` mà không có mật khẩu ở đâu → lỗi nêu cả hai đường.

    Thông điệp phải cho người dùng biết sửa bằng gì, và không được chứa mật
    khẩu nào (cả file này lẫn URL nguồn).
    """
    monkeypatch.delenv(ONVIF_PASSWORD_ENV, raising=False)
    monkeypatch.setenv(CAMERA_SOURCE_ENV, "rtsp://admin@192.0.2.77:554/1/2")

    path = _write(
        tmp_path,
        "camera:\n"
        "  source: usb:0\n"
        "  onvif:\n"
        "    enabled: true\n",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)

    message = str(excinfo.value)
    assert "POSTURE_ONVIF_PASSWORD" in message
    assert CAMERA_SOURCE_ENV in message
    assert SECRET not in message


def test_onvif_enabled_false_thang_su_tu_dong(tmp_path, monkeypatch):
    """Người dùng chủ động tắt thì tôn trọng, dù nguồn có đủ thông tin."""
    monkeypatch.setenv(ONVIF_PASSWORD_ENV, SECRET)
    monkeypatch.setenv(CAMERA_SOURCE_ENV, SECRET_URL)

    path = _write(
        tmp_path,
        "camera:\n  source: usb:0\n  onvif:\n    enabled: false\n",
    )
    config = load_config(path)

    assert config.camera.onvif.enabled is False
    assert config.camera.onvif.host == "192.0.2.77", "host vẫn suy ra được"


def test_onvif_cau_hinh_cu_enabled_true_va_host_van_chay(tmp_path, monkeypatch):
    """Cấu hình kiểu cũ (``enabled: true`` + ``host`` + biến mật khẩu) không vỡ."""
    monkeypatch.setenv(ONVIF_PASSWORD_ENV, SECRET)

    path = _write(
        tmp_path,
        "camera:\n"
        "  source: usb:0\n"
        "  onvif:\n"
        "    enabled: true\n"
        "    host: 192.0.2.10\n"
        "    port: 8080\n"
        "    user: admin\n",
    )
    config = load_config(path)

    assert config.camera.onvif.enabled is True
    assert config.camera.onvif.host == "192.0.2.10"
    assert config.camera.onvif.port == 8080


def test_onvif_enabled_sai_kieu_bao_loi(tmp_path):
    path = _write(
        tmp_path,
        "camera:\n  source: usb:0\n  onvif:\n    enabled: 5\n",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert "camera.onvif.enabled" in str(excinfo.value)


def test_onvif_host_dang_url_rtsp_bi_che_trong_thong_diep(tmp_path, monkeypatch):
    """Dán URL RTSP có mật khẩu vào ``camera.onvif.host`` → mật khẩu bị che."""
    monkeypatch.delenv(ONVIF_PASSWORD_ENV, raising=False)

    path = _write(
        tmp_path,
        "camera:\n"
        "  source: usb:0\n"
        "  onvif:\n"
        "    enabled: true\n"
        f'    host: "{SECRET_URL}"\n',
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)

    message = str(excinfo.value)
    assert SECRET not in message


def test_onvif_tu_bat_khi_chi_co_env_password(tmp_path, monkeypatch):
    """``auto`` + ``POSTURE_ONVIF_PASSWORD`` + URL **không** có tài khoản → bật.

    Đây là đường triển khai mà tài liệu khuyên dùng: mật khẩu để trong biến
    môi trường chứ không nhét vào URL. ``enabled`` = ``auto`` chỉ được quyết
    định dựa trên *có mật khẩu từ bất kỳ nguồn nào*, không phải chỉ URL.

    Test này khoá đúng tổ hợp đó. Hai test lân cận
    (``test_onvif_tu_bat_khi_chi_co_source_co_mat_khau`` và
    ``test_onvif_tu_tat_khi_source_khong_co_mat_khau``) đều giả định "nguồn
    mật khẩu duy nhất là URL", nên một bản "đơn giản hoá" hàm
    ``_resolve_onvif`` thành ``_source_credentials(source)[1]`` vẫn làm chúng
    xanh trong khi đường khuyến nghị trong README §7.2 chết.
    """
    monkeypatch.setenv(ONVIF_PASSWORD_ENV, SECRET)
    monkeypatch.setenv(CAMERA_SOURCE_ENV, "rtsp://192.0.2.77:554/1/2")

    config = load_config(_write_source(tmp_path, "usb:0"))

    assert config.camera.source == "rtsp:rtsp://192.0.2.77:554/1/2"
    assert config.camera.onvif.host == "192.0.2.77", "host vẫn suy từ source"
    assert config.camera.onvif.enabled is True, (
        "có mật khẩu từ biến môi trường là đủ để auto bật"
    )
    assert SECRET not in repr(config)


def test_env_password_thang_tai_khoan_nhung_trong_source(tmp_path, monkeypatch):
    """Cả hai nguồn đều có mật khẩu **khác nhau** → biến môi trường thắng.

    Tài liệu hứa "``POSTURE_ONVIF_PASSWORD`` luôn thắng" (README §4,
    ``docs/WEB_DASHBOARD.md`` §7.2). Nếu ai đó đảo thứ tự ưu tiên trong
    :func:`onvif_credentials` thì người dùng đổi mật khẩu bằng biến môi trường
    sẽ thấy camera từ chối đăng nhập mà không hiểu vì sao.
    """
    env_secret = "mat-khau-tu-env"
    source_secret = "mat-khau-trong-url"
    monkeypatch.setenv(ONVIF_PASSWORD_ENV, env_secret)
    monkeypatch.setenv(
        CAMERA_SOURCE_ENV, f"rtsp://nguoi-dung-url:{source_secret}@192.0.2.77:554/1/2"
    )

    config = load_config(_write_source(tmp_path, "usb:0"))
    user, password = onvif_credentials(
        config.camera.onvif, config.camera.source
    )

    assert password == env_secret, "biến môi trường phải thắng URL"
    assert password != source_secret
    # Tài khoản đi kèm mật khẩu env là ``camera.onvif.user`` (mặc định
    # ``admin``), không phải tên đăng nhập nhúng trong URL — cặp
    # (user, password) phải đến từ **cùng một** nguồn.
    assert user == config.camera.onvif.user
    assert user != "nguoi-dung-url"
    assert source_secret not in repr(config)
