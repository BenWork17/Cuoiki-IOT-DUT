"""Điểm vào nạp cấu hình YAML (:func:`load_config`) và re-export schema/credentials."""

from __future__ import annotations

from pathlib import Path

import yaml

from .config_models import (
    MOCK_MODES,
    MODEL_FORMATS,
    VIEWS,
    AlertsConfig,
    CameraConfig,
    CameraSpeakerConfig,
    Config,
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
from .config_parsers import (
    _get_bool,
    _parse_alerts,
    _parse_camera,
    _parse_face,
    _parse_hardware,
    _parse_model,
    _parse_phone,
    _parse_presence,
    _parse_schedule,
    _parse_sensors,
    _parse_session,
    _parse_speaker_alert,
    _parse_storage,
    _parse_thresholds,
    _parse_timing,
    _parse_tracking,
    _parse_web,
)
from .credentials import (
    CAMERA_SOURCE_ENV,
    ONVIF_PASSWORD_ENV,
    REDACTED,
    _normalize_env_source,
    camera_credentials,
    camera_source_host,
    onvif_credentials,
    onvif_password,
    parse_camera_source,
    redact_camera_source,
    resolve_model_path,
)


def load_config(path: str | Path = "config.yaml") -> Config:
    """Nạp và kiểm tra file cấu hình YAML."""
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Không tìm thấy file cấu hình: {config_path.resolve()}. "
            "Hãy tạo config.yaml (xem config.yaml mẫu trong repo) hoặc "
            "truyền --config đường_dẫn."
        )

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"File cấu hình '{config_path}' không phải YAML hợp lệ: {exc}"
        ) from exc
    except OSError as exc:
        raise ConfigError(
            f"Không đọc được file cấu hình '{config_path}': {exc}"
        ) from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Gốc của '{config_path}' phải là ánh xạ (các mục camera, model, "
            f"...), nhận được {type(raw).__name__}."
        )

    return Config(
        camera=_parse_camera(raw.get("camera")),
        model=_parse_model(raw.get("model")),
        tracking=_parse_tracking(raw.get("tracking")),
        phone=_parse_phone(raw.get("phone")),
        thresholds=_parse_thresholds(raw.get("thresholds")),
        timing=_parse_timing(raw.get("timing")),
        alerts=_parse_alerts(raw.get("alerts")),
        hardware=_parse_hardware(raw.get("hardware")),
        sensors=_parse_sensors(raw.get("sensors")),
        presence=_parse_presence(raw.get("presence")),
        storage=_parse_storage(raw.get("storage")),
        web=_parse_web(raw.get("web")),
        face=_parse_face(raw.get("face")),
        speaker_alert=_parse_speaker_alert(raw.get("speaker_alert")),
        schedule=_parse_schedule(raw.get("schedule")),
        session=_parse_session(raw.get("session")),
        posture_labels_enabled=_get_bool(
            raw, "posture_labels_enabled", Config.posture_labels_enabled, ""
        ),
        path=str(config_path),
    )


__all__ = [
    "AlertsConfig",
    "CAMERA_SOURCE_ENV",
    "CameraConfig",
    "CameraSpeakerConfig",
    "Config",
    "ConfigError",
    "FaceConfig",
    "HardwareConfig",
    "MOCK_MODES",
    "MODEL_FORMATS",
    "ModelConfig",
    "ONVIF_PASSWORD_ENV",
    "OnvifConfig",
    "PhoneConfig",
    "PinsConfig",
    "PresenceConfig",
    "REDACTED",
    "SensorsConfig",
    "SessionConfig",
    "SpeakerAlertConfig",
    "StorageConfig",
    "ThresholdsConfig",
    "TimingConfig",
    "TrackingConfig",
    "VIEWS",
    "WebConfig",
    "_normalize_env_source",
    "_parse_face",
    "_parse_speaker_alert",
    "camera_credentials",
    "camera_source_host",
    "load_config",
    "onvif_credentials",
    "onvif_password",
    "parse_camera_source",
    "redact_camera_source",
    "resolve_model_path",
]
