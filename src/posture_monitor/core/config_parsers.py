"""Các hàm ép kiểu an toàn và phân tích từng mục của ``config.yaml``."""

from __future__ import annotations

import logging
import math
import os
from typing import Any

from ..domain.schedule import ScheduleConfig, ScheduleError, parse_schedule_mapping
from .config_models import (
    MODEL_FORMATS,
    VIEWS,
    AlertsConfig,
    CameraConfig,
    CameraSpeakerConfig,
    ConfigError,
    FaceConfig,
    HardwareConfig,
    ModelConfig,
    OnvifConfig,
    PhoneConfig,
    PinsConfig,
    PresenceConfig,
    SensorsConfig,
    SessionConfig,
    SpeakerAlertConfig,
    StorageConfig,
    ThresholdsConfig,
    TimingConfig,
    TrackingConfig,
    WebConfig,
)
from .credentials import (
    CAMERA_SOURCE_ENV,
    ONVIF_PASSWORD_ENV,
    _normalize_env_source,
    camera_source_host,
    onvif_credentials,
    parse_camera_source,
    redact_camera_source,
)
from .labels import (
    MAX_SPEECH_SPEED,
    MAX_VOLUME,
    MIN_SPEECH_SPEED,
    MIN_VOLUME,
    VOICE_LABELS,
    VOICES,
    normalise_voice,
)

_LOGGER = logging.getLogger("posture_monitor.core.config")

_MIN_SESSION_MINUTES = 1
_MAX_SESSION_MINUTES = 720


def _where(section: str, key: str) -> str:
    return f"{section}.{key}" if section else key


def _as_dict(value: Any, section: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(
            f"Mục '{section}' phải là một ánh xạ (dict), nhận được "
            f"{type(value).__name__}."
        )
    return value


def _get_int(data: dict[str, Any], key: str, default: int, section: str) -> int:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"'{_where(section, key)}' phải là số nguyên, nhận được "
            f"{type(value).__name__}: {value!r}."
        )
    return value


def _get_float(data: dict[str, Any], key: str, default: float, section: str) -> float:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"'{_where(section, key)}' phải là số, nhận được "
            f"{type(value).__name__}: {value!r}."
        )
    try:
        return float(value)
    except OverflowError:
        raise ConfigError(
            f"'{_where(section, key)}' phải là số biểu diễn được dạng float, "
            f"nhận được {type(value).__name__}: {value!r}."
        ) from None


def _get_optional_float(data: dict[str, Any], key: str, section: str) -> float | None:
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"'{_where(section, key)}' phải là số hoặc null (chưa đo), nhận "
            f"được {type(value).__name__}: {value!r}."
        )
    return float(value)


def _get_bool(data: dict[str, Any], key: str, default: bool, section: str) -> bool:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ConfigError(
            f"'{_where(section, key)}' phải là true/false, nhận được "
            f"{type(value).__name__}: {value!r}."
        )
    return value


def _get_optional_bool(data: dict[str, Any], key: str, section: str) -> bool | None:
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() == "auto":
        return None
    raise ConfigError(
        f"'{_where(section, key)}' phải là true, false hoặc auto/để trống, "
        f"nhận được {value!r}."
    )


def _get_str(data: dict[str, Any], key: str, default: str, section: str) -> str:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, str):
        raise ConfigError(
            f"'{_where(section, key)}' phải là chuỗi, nhận được "
            f"{type(value).__name__}: {value!r}."
        )
    return value


def _get_choice(
    data: dict[str, Any],
    key: str,
    default: str,
    allowed: tuple[str, ...],
    section: str,
) -> str:
    value = _get_str(data, key, default, section)
    if value not in allowed:
        raise ConfigError(
            f"'{_where(section, key)}' phải là một trong {allowed}, "
            f"nhận được {value!r}."
        )
    return value


def _parse_onvif(raw: Any) -> OnvifConfig:
    data = _as_dict(raw, "camera.onvif")
    cfg = OnvifConfig(
        enabled=_get_optional_bool(data, "enabled", "camera.onvif"),
        host=_get_str(data, "host", OnvifConfig.host, "camera.onvif"),
        port=_get_int(data, "port", OnvifConfig.port, "camera.onvif"),
        user=_get_str(data, "user", OnvifConfig.user, "camera.onvif"),
    )
    if not 0 < cfg.port < 65536:
        raise ConfigError("'camera.onvif.port' phải nằm trong khoảng 1..65535.")
    return cfg


def _check_onvif_ready(onvif: OnvifConfig, source: str, *, from_env: bool) -> None:
    safe_host = redact_camera_source(onvif.host)
    if not onvif.host.strip():
        hint = (
            f"Đặt biến môi trường {CAMERA_SOURCE_ENV} thành URL RTSP của "
            "camera, hoặc điền 'camera.onvif.host'."
            if not from_env
            else "Điền 'camera.onvif.host' trong config.yaml."
        )
        raise ConfigError(
            "'camera.onvif.enabled' là true nhưng không xác định được "
            "'camera.onvif.host'. " + hint
        )
    if not onvif_credentials(onvif, source)[1]:
        raise ConfigError(
            "'camera.onvif.enabled' là true nhưng chưa có mật khẩu ONVIF "
            f"cho camera {safe_host!r}. Đặt biến môi trường "
            f"{ONVIF_PASSWORD_ENV}, hoặc đặt {CAMERA_SOURCE_ENV} thành URL "
            "RTSP có kèm tài khoản (mật khẩu không được ghi vào config.yaml)."
        )


def _resolve_onvif(onvif: OnvifConfig, source: str, *, from_env: bool) -> OnvifConfig:
    if not onvif.host.strip():
        onvif.host = camera_source_host(source)

    explicit = onvif.enabled is not None
    if not explicit:
        onvif.enabled = bool(onvif.host.strip())

    if onvif.enabled and explicit:
        _check_onvif_ready(onvif, source, from_env=from_env)
    elif onvif.enabled and not onvif_credentials(onvif, source)[1]:
        onvif.enabled = False
    return onvif


def _parse_speaker(raw: Any) -> CameraSpeakerConfig:
    data = _as_dict(raw, "camera.speaker")
    cfg = CameraSpeakerConfig(
        enabled=_get_bool(
            data, "enabled", CameraSpeakerConfig.enabled, "camera.speaker"
        ),
        host=_get_str(data, "host", CameraSpeakerConfig.host, "camera.speaker"),
        port=_get_int(data, "port", CameraSpeakerConfig.port, "camera.speaker"),
        user=_get_str(data, "user", CameraSpeakerConfig.user, "camera.speaker"),
        stream_path=_get_str(
            data, "stream_path", CameraSpeakerConfig.stream_path, "camera.speaker"
        ),
    )
    if not 0 < cfg.port < 65536:
        raise ConfigError("'camera.speaker.port' phải nằm trong khoảng 1..65535.")
    if "://" in cfg.host:
        safe_host = redact_camera_source(cfg.host)
        raise ConfigError(
            f"'camera.speaker.host' = {safe_host!r} phải là tên máy hoặc IP, "
            "không kèm 'rtsp://' hay thông tin đăng nhập. Đặt phần đường dẫn "
            "vào 'camera.speaker.stream_path'."
        )
    return cfg


def _parse_camera(raw: Any) -> CameraConfig:
    data = _as_dict(raw, "camera")
    cfg = CameraConfig(
        source=_get_str(data, "source", CameraConfig.source, "camera"),
        width=_get_int(data, "width", CameraConfig.width, "camera"),
        height=_get_int(data, "height", CameraConfig.height, "camera"),
        view=_get_choice(data, "view", CameraConfig.view, VIEWS, "camera"),
        onvif=_parse_onvif(data.get("onvif")),
        speaker=_parse_speaker(data.get("speaker")),
    )
    override = os.environ.get(CAMERA_SOURCE_ENV, "").strip()
    if override:
        cfg.source = _normalize_env_source(override)

    parse_camera_source(cfg.source)
    cfg.onvif = _resolve_onvif(cfg.onvif, cfg.source, from_env=bool(override))

    if cfg.speaker.enabled and not cfg.speaker.host.strip():
        if not camera_source_host(cfg.source):
            _LOGGER.warning(
                "'camera.speaker.enabled' là true nhưng không xác định được "
                "'camera.speaker.host': mục đó đang trống và 'camera.source' "
                "(%s) không phải URL RTSP có host. Loa sẽ CHỈ ghi sự kiện, "
                "không phát tiếng. Muốn có tiếng, đặt biến môi trường %s thành "
                "'rtsp:rtsp://...' hoặc điền 'camera.speaker.host' (ví dụ "
                "192.168.1.50).",
                redact_camera_source(cfg.source),
                CAMERA_SOURCE_ENV,
            )
    if cfg.width <= 0 or cfg.height <= 0:
        raise ConfigError(
            f"'camera.width' và 'camera.height' phải là số dương, nhận được "
            f"{cfg.width}x{cfg.height}."
        )
    return cfg


def _parse_model(raw: Any) -> ModelConfig:
    data = _as_dict(raw, "model")
    cfg = ModelConfig(
        name=_get_str(data, "name", ModelConfig.name, "model"),
        format=_get_choice(data, "format", ModelConfig.format, MODEL_FORMATS, "model"),
        imgsz=_get_int(data, "imgsz", ModelConfig.imgsz, "model"),
        target_fps=_get_int(data, "target_fps", ModelConfig.target_fps, "model"),
        kp_conf_min=_get_float(data, "kp_conf_min", ModelConfig.kp_conf_min, "model"),
        export_on_pc=_get_bool(data, "export_on_pc", ModelConfig.export_on_pc, "model"),
    )
    if cfg.imgsz <= 0:
        raise ConfigError("'model.imgsz' phải là số dương.")
    if cfg.target_fps <= 0:
        raise ConfigError("'model.target_fps' phải là số dương.")
    if not 0.0 <= cfg.kp_conf_min <= 1.0:
        raise ConfigError("'model.kp_conf_min' phải nằm trong [0, 1].")
    return cfg


def _parse_tracking(raw: Any) -> TrackingConfig:
    data = _as_dict(raw, "tracking")
    return TrackingConfig(
        enabled=_get_bool(data, "enabled", TrackingConfig.enabled, "tracking"),
        tracker=_get_str(data, "tracker", TrackingConfig.tracker, "tracking"),
    )


def _parse_phone(raw: Any) -> PhoneConfig:
    data = _as_dict(raw, "phone")
    base = PhoneConfig()
    cfg = PhoneConfig(
        enabled=_get_bool(data, "enabled", base.enabled, "phone"),
        detect_model=_get_str(data, "detect_model", base.detect_model, "phone"),
        detect_weights=_get_str(data, "detect_weights", base.detect_weights, "phone"),
        detect_every_n_frames=_get_int(
            data, "detect_every_n_frames", base.detect_every_n_frames, "phone"
        ),
        imgsz=_get_int(data, "imgsz", base.imgsz, "phone"),
        conf_threshold=_get_float(data, "conf_threshold", base.conf_threshold, "phone"),
        wrist_conf_min=_get_float(data, "wrist_conf_min", base.wrist_conf_min, "phone"),
        box_ttl_s=_get_float(data, "box_ttl_s", base.box_ttl_s, "phone"),
        hold_s=_get_float(data, "hold_s", base.hold_s, "phone"),
        touching_slack_px=_get_float(
            data, "touching_slack_px", base.touching_slack_px, "phone"
        ),
        shoulder_ratio=_get_float(data, "shoulder_ratio", base.shoulder_ratio, "phone"),
        head_filter=_get_bool(data, "head_filter", base.head_filter, "phone"),
        phone_like_filter=_get_bool(
            data, "phone_like_filter", base.phone_like_filter, "phone"
        ),
        min_size_ratio=_get_float(data, "min_size_ratio", base.min_size_ratio, "phone"),
        max_above_shoulder_px=_get_float(
            data, "max_above_shoulder_px", base.max_above_shoulder_px, "phone"
        ),
        oversize_ratio=_get_float(data, "oversize_ratio", base.oversize_ratio, "phone"),
        miss_tolerance_frames=_get_int(
            data, "miss_tolerance_frames", base.miss_tolerance_frames, "phone"
        ),
    )
    if not cfg.detect_model.strip():
        raise ConfigError("'phone.detect_model' phải là chuỗi không rỗng.")
    if cfg.detect_every_n_frames < 1:
        raise ConfigError("'phone.detect_every_n_frames' phải >= 1.")
    if cfg.imgsz <= 0:
        raise ConfigError("'phone.imgsz' phải là số dương.")
    if not 0.0 <= cfg.conf_threshold <= 1.0:
        raise ConfigError("'phone.conf_threshold' phải nằm trong [0, 1].")
    if not 0.0 < cfg.wrist_conf_min <= 1.0:
        raise ConfigError("'phone.wrist_conf_min' phải nằm trong (0, 1].")
    for field_name in (
        "box_ttl_s",
        "hold_s",
        "touching_slack_px",
        "shoulder_ratio",
        "min_size_ratio",
        "max_above_shoulder_px",
        "oversize_ratio",
        "miss_tolerance_frames",
    ):
        if getattr(cfg, field_name) < 0:
            raise ConfigError(f"'phone.{field_name}' không được âm.")
    return cfg


def _parse_thresholds(raw: Any) -> ThresholdsConfig:
    data = _as_dict(raw, "thresholds")
    base = ThresholdsConfig()
    return ThresholdsConfig(
        head_down_ratio=_get_float(
            data, "head_down_ratio", base.head_down_ratio, "thresholds"
        ),
        too_close_ratio=_get_float(
            data, "too_close_ratio", base.too_close_ratio, "thresholds"
        ),
        shoulder_tilt_deg=_get_float(
            data, "shoulder_tilt_deg", base.shoulder_tilt_deg, "thresholds"
        ),
        head_tilt_deg=_get_float(
            data, "head_tilt_deg", base.head_tilt_deg, "thresholds"
        ),
        lean_x=_get_float(data, "lean_x", base.lean_x, "thresholds"),
        look_away_yaw=_get_float(
            data, "look_away_yaw", base.look_away_yaw, "thresholds"
        ),
        neck_angle_drop_deg=_get_float(
            data, "neck_angle_drop_deg", base.neck_angle_drop_deg, "thresholds"
        ),
    )


def _parse_timing(raw: Any) -> TimingConfig:
    data = _as_dict(raw, "timing")
    base = TimingConfig()
    return TimingConfig(
        smooth_window_s=_get_float(
            data, "smooth_window_s", base.smooth_window_s, "timing"
        ),
        bad_hold_s=_get_float(data, "bad_hold_s", base.bad_hold_s, "timing"),
        good_hold_s=_get_float(data, "good_hold_s", base.good_hold_s, "timing"),
        alert_cooldown_s=_get_float(
            data, "alert_cooldown_s", base.alert_cooldown_s, "timing"
        ),
        escalate_after_s=_get_float(
            data, "escalate_after_s", base.escalate_after_s, "timing"
        ),
        break_after_min=_get_float(
            data, "break_after_min", base.break_after_min, "timing"
        ),
        absent_reset_s=_get_float(
            data, "absent_reset_s", base.absent_reset_s, "timing"
        ),
        drowsy_hold_s=_get_float(data, "drowsy_hold_s", base.drowsy_hold_s, "timing"),
    )


def _parse_alerts(raw: Any) -> AlertsConfig:
    data = _as_dict(raw, "alerts")
    return AlertsConfig(
        buzzer_enabled=_get_bool(
            data, "buzzer_enabled", AlertsConfig.buzzer_enabled, "alerts"
        ),
        vibration_enabled=_get_bool(
            data, "vibration_enabled", AlertsConfig.vibration_enabled, "alerts"
        ),
        gpio_alert_enabled=_get_bool(
            data, "gpio_alert_enabled", AlertsConfig.gpio_alert_enabled, "alerts"
        ),
    )


def _parse_schedule(raw: Any) -> ScheduleConfig:
    data = _as_dict(raw, "schedule")
    try:
        return parse_schedule_mapping(data, prefix="schedule", reject_unknown_keys=False)
    except ScheduleError as exc:
        raise ConfigError(str(exc)) from exc


def _parse_pins(raw: Any) -> PinsConfig:
    data = _as_dict(raw, "hardware.pins")
    base = PinsConfig()
    return PinsConfig(
        led_green=_get_int(data, "led_green", base.led_green, "hardware.pins"),
        led_yellow=_get_int(data, "led_yellow", base.led_yellow, "hardware.pins"),
        led_red=_get_int(data, "led_red", base.led_red, "hardware.pins"),
        buzzer=_get_int(data, "buzzer", base.buzzer, "hardware.pins"),
        vibration=_get_int(data, "vibration", base.vibration, "hardware.pins"),
        trig=_get_int(data, "trig", base.trig, "hardware.pins"),
        echo=_get_int(data, "echo", base.echo, "hardware.pins"),
    )


def _parse_hardware(raw: Any) -> HardwareConfig:
    data = _as_dict(raw, "hardware")
    mock: str | bool = "auto"
    if "mock" in data and data["mock"] is not None:
        value = data["mock"]
        if isinstance(value, bool):
            mock = value
        elif isinstance(value, str) and value in ("auto", "true", "false"):
            mock = True if value == "true" else False if value == "false" else "auto"
        else:
            raise ConfigError(
                f"'hardware.mock' phải là auto, true hoặc false, nhận được {value!r}."
            )
    return HardwareConfig(mock=mock, pins=_parse_pins(data.get("pins")))


def _parse_sensors(raw: Any) -> SensorsConfig:
    data = _as_dict(raw, "sensors")
    cfg = SensorsConfig(
        ultrasonic_enabled=_get_bool(
            data, "ultrasonic_enabled", SensorsConfig.ultrasonic_enabled, "sensors"
        ),
        min_distance_cm=_get_float(
            data, "min_distance_cm", SensorsConfig.min_distance_cm, "sensors"
        ),
    )
    if cfg.min_distance_cm <= 0:
        raise ConfigError("'sensors.min_distance_cm' phải là số dương.")
    return cfg


def _parse_presence(raw: Any) -> PresenceConfig:
    data = _as_dict(raw, "presence")
    cfg = PresenceConfig(
        absent_grace_s=_get_float(
            data, "absent_grace_s", PresenceConfig.absent_grace_s, "presence"
        ),
    )
    if cfg.absent_grace_s < 0:
        raise ConfigError("'presence.absent_grace_s' không được âm.")
    return cfg


def _parse_storage(raw: Any) -> StorageConfig:
    data = _as_dict(raw, "storage")
    cfg = StorageConfig(
        db_path=_get_str(data, "db_path", StorageConfig.db_path, "storage"),
        retention_days=_get_int(
            data, "retention_days", StorageConfig.retention_days, "storage"
        ),
    )
    if cfg.retention_days < 0:
        raise ConfigError("'storage.retention_days' không được âm.")
    return cfg


def _parse_face(raw: Any) -> FaceConfig:
    data = _as_dict(raw, "face")
    cfg = FaceConfig(
        enabled=_get_optional_bool(data, "enabled", "face"),
        detector=_get_str(data, "detector", FaceConfig.detector, "face"),
        recognizer=_get_str(data, "recognizer", FaceConfig.recognizer, "face"),
        interval_s=_get_float(data, "interval_s", FaceConfig.interval_s, "face"),
        match_threshold=_get_optional_float(data, "match_threshold", "face"),
        impostor_hold_s=_get_float(
            data, "impostor_hold_s", FaceConfig.impostor_hold_s, "face"
        ),
        enroll_step_s=_get_float(
            data, "enroll_step_s", FaceConfig.enroll_step_s, "face"
        ),
        enroll_min_samples=_get_int(
            data, "enroll_min_samples", FaceConfig.enroll_min_samples, "face"
        ),
        score_threshold=_get_float(
            data, "score_threshold", FaceConfig.score_threshold, "face"
        ),
        store_path=_get_str(data, "store_path", FaceConfig.store_path, "face"),
    )
    if not cfg.detector.strip():
        raise ConfigError("'face.detector' không được để trống.")
    if not cfg.recognizer.strip():
        raise ConfigError("'face.recognizer' không được để trống.")
    if not cfg.store_path.strip():
        raise ConfigError(
            "'face.store_path' không được để trống; kho khuôn mặt cần một đường dẫn tệp."
        )
    if cfg.interval_s <= 0:
        raise ConfigError("'face.interval_s' phải là số dương (nhịp nhận diện, giây).")
    if cfg.impostor_hold_s < 0:
        raise ConfigError("'face.impostor_hold_s' không được âm.")
    if cfg.enroll_step_s <= 0:
        raise ConfigError("'face.enroll_step_s' phải là số dương (giây mỗi tư thế).")
    if cfg.enroll_min_samples <= 0:
        raise ConfigError("'face.enroll_min_samples' phải là số dương (số mẫu tối thiểu).")
    if not math.isfinite(cfg.score_threshold) or not (0.0 < cfg.score_threshold <= 1.0):
        raise ConfigError(
            "'face.score_threshold' phải nằm trong (0, 1] (ngưỡng điểm của "
            f"bộ phát hiện YuNet), nhận được {cfg.score_threshold!r}."
        )
    if cfg.match_threshold is not None:
        if not (-1.0 <= cfg.match_threshold <= 1.0):
            raise ConfigError(
                "'face.match_threshold' phải nằm trong [-1.0, 1.0] (miền giá "
                f"trị của cosine), nhận được {cfg.match_threshold!r}."
            )
        if not math.isfinite(cfg.match_threshold):
            raise ConfigError(
                f"'face.match_threshold' phải hữu hạn, nhận được {cfg.match_threshold!r}."
            )

    if cfg.enabled is None:
        cfg.enabled = cfg.match_threshold is not None
    elif cfg.enabled and cfg.match_threshold is None:
        _LOGGER.warning(
            "'face.enabled' là true nhưng 'face.match_threshold' đang null: "
            "ngưỡng sẽ được tự suy ra từ dữ liệu đăng ký khi có đủ %d mẫu; "
            "trước đó mọi quan sát là UNKNOWN. Muốn đặt tay, đo rồi điền vào.",
            cfg.enroll_min_samples,
        )
    return cfg


def _parse_web(raw: Any) -> WebConfig:
    data = _as_dict(raw, "web")
    cfg = WebConfig(
        host=_get_str(data, "host", WebConfig.host, "web"),
        port=_get_int(data, "port", WebConfig.port, "web"),
        stream_enabled=_get_bool(
            data, "stream_enabled", WebConfig.stream_enabled, "web"
        ),
    )
    if not 0 < cfg.port < 65536:
        raise ConfigError("'web.port' phải nằm trong khoảng 1..65535.")
    return cfg


def _validate_session_minutes(raw_minutes: Any) -> int:
    if isinstance(raw_minutes, bool) or not isinstance(raw_minutes, (int, float)):
        raise ConfigError(
            "'session.default_minutes' không hợp lệ: Thời lượng phiên học phải là "
            f"số phút, nhận được {type(raw_minutes).__name__}: {raw_minutes!r}."
        )
    number = float(raw_minutes)
    if not math.isfinite(number):
        raise ConfigError(
            f"'session.default_minutes' không hợp lệ: Thời lượng phiên học phải là số hữu hạn, nhận được {raw_minutes!r}."
        )
    rounded = int(round(number))
    if abs(number - rounded) > 1e-9:
        raise ConfigError(
            f"'session.default_minutes' không hợp lệ: Thời lượng phiên học phải là số phút nguyên, nhận được {raw_minutes!r}."
        )
    if not _MIN_SESSION_MINUTES <= rounded <= _MAX_SESSION_MINUTES:
        raise ConfigError(
            f"'session.default_minutes' không hợp lệ: Thời lượng phiên học phải trong khoảng "
            f"{_MIN_SESSION_MINUTES}–{_MAX_SESSION_MINUTES} phút, nhận được {rounded} phút."
        )
    return rounded


def _parse_session(raw: Any) -> SessionConfig:
    data = _as_dict(raw, "session")
    raw_minutes = data.get("default_minutes")
    minutes = (
        SessionConfig.default_minutes
        if raw_minutes is None
        else _validate_session_minutes(raw_minutes)
    )
    return SessionConfig(
        default_minutes=minutes,
        auto_start=_get_bool(data, "auto_start", SessionConfig.auto_start, "session"),
    )


def _parse_speaker_alert(raw: Any) -> SpeakerAlertConfig:
    data = _as_dict(raw, "speaker_alert")
    raw_voice = _get_str(data, "voice", SpeakerAlertConfig.voice, "speaker_alert")
    voice = normalise_voice(raw_voice)
    if isinstance(raw_voice, str) and raw_voice.strip().lower() not in VOICES:
        raise ConfigError(
            f"'speaker_alert.voice' phải là một trong "
            f"{', '.join(repr(v) for v in VOICES)} (nhãn: "
            f"{', '.join(VOICE_LABELS[v] for v in VOICES)}), nhận được {raw_voice!r}."
        )
    volume = _get_float(data, "volume", SpeakerAlertConfig.volume, "speaker_alert")
    if not math.isfinite(volume) or not (MIN_VOLUME <= volume <= MAX_VOLUME):
        raise ConfigError(
            f"'speaker_alert.volume' phải trong khoảng "
            f"{MIN_VOLUME:g}..{MAX_VOLUME:g} (1.0 = nguyên bản), nhận được {volume!r}."
        )
    speed = _get_float(data, "speed", SpeakerAlertConfig.speed, "speaker_alert")
    if not math.isfinite(speed) or not (MIN_SPEECH_SPEED <= speed <= MAX_SPEECH_SPEED):
        raise ConfigError(
            f"'speaker_alert.speed' phải trong khoảng "
            f"{MIN_SPEECH_SPEED:g}..{MAX_SPEECH_SPEED:g} (0.9 = chậm lại 10 %), "
            f"nhận được {speed!r}."
        )
    cfg = SpeakerAlertConfig(
        say=_get_bool(data, "say", SpeakerAlertConfig.say, "speaker_alert"),
        tone_fallback=_get_bool(
            data, "tone_fallback", SpeakerAlertConfig.tone_fallback, "speaker_alert"
        ),
        audio_dir=_get_str(
            data, "audio_dir", SpeakerAlertConfig.audio_dir, "speaker_alert"
        ),
        language=_get_str(
            data, "language", SpeakerAlertConfig.language, "speaker_alert"
        ),
        voice=voice,
        volume=volume,
        speed=speed,
    )
    if not cfg.audio_dir.strip():
        raise ConfigError("'speaker_alert.audio_dir' không được để trống.")
    return cfg
