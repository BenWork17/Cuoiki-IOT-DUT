"""Định nghĩa toàn bộ các dataclass cấu hình của ứng dụng."""

from __future__ import annotations

from dataclasses import dataclass, field

from .credentials import ConfigError, redact_camera_source
from .labels import (
    DEFAULT_SESSION_MINUTES,
    DEFAULT_SPEECH_SPEED,
    DEFAULT_VOLUME,
    FACE_STORE_FILENAME,
    MOCK_MODES,
    MODEL_FORMATS,
    VIEWS,
)
from ..domain.schedule import DEFAULT_PHONE_HOLD_S, ScheduleConfig


@dataclass
class OnvifConfig:
    """Điều khiển PTZ qua ONVIF (tuỳ chọn, mật khẩu đọc qua biến môi trường)."""

    enabled: bool | None = None
    host: str = ""
    port: int = 80
    user: str = "admin"


@dataclass
class CameraSpeakerConfig:
    """Loa của camera IP qua RTSP backchannel (cổng RTSP 554, tách biệt cổng HTTP ONVIF)."""

    enabled: bool = False
    host: str = ""
    port: int = 554
    user: str = ""
    stream_path: str = "/1/2"


@dataclass
class CameraConfig:
    source: str = "usb:0"
    width: int = 640
    height: int = 480
    view: str = "front"
    onvif: OnvifConfig = field(default_factory=OnvifConfig)
    speaker: CameraSpeakerConfig = field(default_factory=CameraSpeakerConfig)

    def __repr__(self) -> str:
        return (
            f"CameraConfig(source={redact_camera_source(self.source)!r}, "
            f"width={self.width}, height={self.height}, view={self.view!r}, "
            f"onvif={self.onvif!r}, speaker={self.speaker!r})"
        )


@dataclass
class FaceConfig:
    """Nhận diện khuôn mặt (YuNet + SFace), spec V3 §6."""

    enabled: bool | None = None
    detector: str = "models/yunet.onnx"
    recognizer: str = "models/sface.onnx"
    interval_s: float = 2.0
    match_threshold: float | None = None
    impostor_hold_s: float = 5.0
    enroll_step_s: float = 1.5
    enroll_min_samples: int = 3
    score_threshold: float = 0.9
    store_path: str = f"data/{FACE_STORE_FILENAME}"


@dataclass
class ModelConfig:
    name: str = "yolo11n-pose"
    format: str = "ncnn"
    imgsz: int = 320
    target_fps: int = 5
    kp_conf_min: float = 0.5
    export_on_pc: bool = False


@dataclass
class TrackingConfig:
    enabled: bool = True
    tracker: str = "botsort.yaml"


@dataclass
class PhoneConfig:
    """Phát hiện dùng điện thoại bằng model detect COCO thứ hai (lớp 67).

    Trên Pi 4 đo được 98,6 ms cho một lần suy luận trên khung tổng hợp 640x480
    (chỉ inference, không gồm capture). Phép đo pipeline thật duy nhất của dự án
    là pose-only: 199,25 ms/khung -> 5,02 FPS; vì vậy ``detect_every_n_frames: 2``
    chưa có ngân sách đo trên pipeline thật và cần đo bằng
    ``benchmark --profile pose_phone``.
    """

    enabled: bool = True
    detect_model: str = "yolo11n"
    detect_weights: str = ""
    detect_every_n_frames: int = 2
    imgsz: int = 320
    conf_threshold: float = 0.06
    wrist_conf_min: float = 0.25
    box_ttl_s: float = 0.5
    hold_s: float = DEFAULT_PHONE_HOLD_S
    touching_slack_px: float = 0.0
    shoulder_ratio: float = 1.0
    head_filter: bool = True
    phone_like_filter: bool = True
    min_size_ratio: float = 0.45
    max_above_shoulder_px: float = 10.0
    oversize_ratio: float = 2.25
    miss_tolerance_frames: int = 0


@dataclass
class ThresholdsConfig:
    head_down_ratio: float = 0.70
    too_close_ratio: float = 1.25
    shoulder_tilt_deg: float = 8.0
    head_tilt_deg: float = 12.0
    lean_x: float = 0.35
    look_away_yaw: float = 0.5
    neck_angle_drop_deg: float = 15.0


@dataclass
class TimingConfig:
    smooth_window_s: float = 1.0
    bad_hold_s: float = 5.0
    good_hold_s: float = 2.0
    alert_cooldown_s: float = 30.0
    escalate_after_s: float = 60.0
    break_after_min: float = 45.0
    absent_reset_s: float = 120.0
    drowsy_hold_s: float = 10.0


@dataclass
class AlertsConfig:
    buzzer_enabled: bool = True
    vibration_enabled: bool = True
    gpio_alert_enabled: bool = False


@dataclass
class PinsConfig:
    led_green: int = 17
    led_yellow: int = 27
    led_red: int = 22
    buzzer: int = 18
    vibration: int = 23
    trig: int = 5
    echo: int = 6


@dataclass
class HardwareConfig:
    mock: str | bool = "auto"
    pins: PinsConfig = field(default_factory=PinsConfig)


@dataclass
class SensorsConfig:
    ultrasonic_enabled: bool = True
    min_distance_cm: float = 35.0


@dataclass
class PresenceConfig:
    absent_grace_s: float = 3.0


@dataclass
class StorageConfig:
    db_path: str = "data/posture.db"
    retention_days: int = 30


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    stream_enabled: bool = False


@dataclass
class SessionConfig:
    default_minutes: int = DEFAULT_SESSION_MINUTES
    auto_start: bool = False


@dataclass
class SpeakerAlertConfig:
    say: bool = True
    tone_fallback: bool = True
    audio_dir: str = "data/audio"
    language: str = "vi"
    voice: str = "nam"
    volume: float = DEFAULT_VOLUME
    speed: float = DEFAULT_SPEECH_SPEED


@dataclass
class Config:
    """Cấu hình tổng của ứng dụng."""

    camera: CameraConfig = field(default_factory=CameraConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    phone: PhoneConfig = field(default_factory=PhoneConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    presence: PresenceConfig = field(default_factory=PresenceConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)
    face: FaceConfig = field(default_factory=FaceConfig)
    speaker_alert: SpeakerAlertConfig = field(default_factory=SpeakerAlertConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    posture_labels_enabled: bool = False
    path: str = ""


__all__ = [
    "AlertsConfig",
    "CameraConfig",
    "CameraSpeakerConfig",
    "Config",
    "ConfigError",
    "DEFAULT_SESSION_MINUTES",
    "FaceConfig",
    "HardwareConfig",
    "MOCK_MODES",
    "MODEL_FORMATS",
    "ModelConfig",
    "OnvifConfig",
    "PhoneConfig",
    "PinsConfig",
    "PresenceConfig",
    "SensorsConfig",
    "SessionConfig",
    "SpeakerAlertConfig",
    "StorageConfig",
    "ThresholdsConfig",
    "TimingConfig",
    "TrackingConfig",
    "VIEWS",
    "WebConfig",
]
