"""Định nghĩa hồ sơ đo (``pose``, ``pose_phone``, ``pose_phone_face``) và model phụ."""

from __future__ import annotations

import time
from typing import Any, Callable

from ...core.config import Config, resolve_model_path
from ...core.logging_setup import get_logger
from ...vision.pose import pose_to_keypoints_array
from .telemetry import BenchmarkError, compute_stats

logger = get_logger("posture_monitor.cli.benchmark.profiles")

DEFAULT_PROFILE = "pose"

PROFILES: dict[str, str] = {
    "pose": "chỉ model tư thế (hành vi gốc của benchmark)",
    "pose_phone": "pose + model detect COCO cho điện thoại (cách khung)",
    "pose_phone_face": "pose + detect điện thoại + đường ống khuôn mặt",
}

_PHONE_PROFILES = frozenset({"pose_phone", "pose_phone_face"})
_FACE_PROFILES = frozenset({"pose_phone_face"})

PHONE_MISSING_MESSAGE = (
    "Hồ sơ đo cần model detect điện thoại, nhưng bản này KHÔNG có module "
    "'posture_monitor.vision.phone_detector' (tính năng thuộc nhánh r3-phone). "
    "Không đo thay bằng cấu hình khác: một bài đo in FPS của riêng pose mà "
    "dán nhãn 'pose_phone' là số liệu sai. Hãy kiểm tra cài đặt (và khối "
    "cấu hình 'phone') rồi chạy lại; muốn đo ngay bây giờ thì dùng "
    "--profile pose và ghi rõ chỉ có pose."
)

FACE_MISSING_MESSAGE = (
    "Hồ sơ đo cần đường ống khuôn mặt, nhưng cấu hình này KHÔNG có khối "
    "'face' (hoặc khối đó đang tắt, hoặc thiếu tệp 'yunet.onnx'/'sface.onnx'). "
    "Không đo thay bằng cấu hình khác vì báo cáo sẽ mang nhãn sai. Hãy thêm "
    "khối 'face' theo spec §6 và đặt sẵn hai tệp ONNX, rồi chạy lại; muốn đo "
    "ngay bây giờ thì dùng --profile pose_phone hoặc --profile pose."
)


def normalise_profile(profile: Any) -> str:
    if profile is None:
        return DEFAULT_PROFILE
    name = str(profile).strip()
    if name not in PROFILES:
        raise BenchmarkError(
            f"Hồ sơ đo --profile không hợp lệ: {name!r}. Chọn một trong "
            + ", ".join(f"'{key}' ({value})" for key, value in PROFILES.items())
            + "."
        )
    return name


class _ExtraModel:
    """Một model phụ chạy cạnh pose, kèm thống kê thời gian cho báo cáo."""

    def __init__(
        self,
        name: str,
        role: str,
        cadence: str,
        step: Callable[[Any, Any, float], None],
        meta: dict[str, Any],
    ) -> None:
        self.name = name
        self.role = role
        self.cadence = cadence
        self._step = step
        self.meta = meta
        self.errors = 0
        self.durations_ms: list[float] = []

    def step(self, frame: Any, pose: Any, now: float) -> None:
        start = time.perf_counter()
        try:
            self._step(frame, pose, now)
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            logger.warning("Model phụ '%s' lỗi ở khung này: %s", self.name, exc)
            return
        self.durations_ms.append((time.perf_counter() - start) * 1000.0)

    def describe(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "name": self.name,
            "role": self.role,
            "cadence": self.cadence,
            "errors": self.errors,
            "timing_ms": compute_stats(self.durations_ms),
        }
        entry.update(self.meta)
        return entry


def _build_phone_extra(config: Config) -> _ExtraModel:
    try:
        from ...vision.phone_detector import PhoneSignal  # noqa: PLC0415
    except ImportError as exc:
        raise BenchmarkError(PHONE_MISSING_MESSAGE) from exc

    phone_cfg = getattr(config, "phone", None)
    if phone_cfg is None:
        raise BenchmarkError(
            PHONE_MISSING_MESSAGE + " (Cấu hình đang nạp không có khối 'phone'.)"
        )
    if not bool(getattr(phone_cfg, "enabled", False)):
        raise BenchmarkError(
            "Hồ sơ đo cần model detect điện thoại nhưng 'phone.enabled' đang "
            "false, nên model đó sẽ không chạy. Không đo nhầm cấu hình: bật "
            "'phone.enabled: true' hoặc dùng --profile pose."
        )

    signal = PhoneSignal(config)
    every = int(getattr(phone_cfg, "detect_every_n_frames", 1) or 1)
    detect_model = str(getattr(phone_cfg, "detect_model", "yolo11n"))

    def step(frame: Any, pose: Any, now: float) -> None:
        if pose is None:
            return
        signal.observe(frame, pose_to_keypoints_array(pose), now)

    return _ExtraModel(
        name=detect_model,
        role="phone_detect",
        cadence=f"mỗi {every} khung",
        step=step,
        meta={
            "imgsz": int(getattr(phone_cfg, "imgsz", 320)),
            "format": config.model.format,
            "detect_every_n_frames": every,
        },
    )


def _build_face_extra(config: Config) -> _ExtraModel:
    face_cfg = getattr(config, "face", None)
    if face_cfg is None or not bool(getattr(face_cfg, "enabled", False)):
        raise BenchmarkError(FACE_MISSING_MESSAGE)

    from ...vision.faces import FaceRecognizer  # noqa: PLC0415

    raw_yunet = str(getattr(face_cfg, "detector", "")).strip()
    raw_sface = str(getattr(face_cfg, "recognizer", "")).strip()
    if not raw_yunet or not raw_sface:
        raise BenchmarkError(FACE_MISSING_MESSAGE)

    yunet = resolve_model_path(raw_yunet)
    sface = resolve_model_path(raw_sface)
    missing = [str(path) for path in (yunet, sface) if not path.is_file()]
    if missing:
        raise BenchmarkError(
            FACE_MISSING_MESSAGE + " (Thiếu tệp: " + ", ".join(missing) + ".)"
        )

    recognizer = FaceRecognizer(
        yunet,
        sface,
        score_threshold=float(getattr(face_cfg, "score_threshold", 0.9)),
    )
    interval_s = float(getattr(face_cfg, "interval_s", 2.0) or 2.0)
    state: dict[str, Any] = {"next_at": 0.0}

    def step(frame: Any, pose: Any, now: float) -> None:
        if now < state["next_at"]:
            return
        state["next_at"] = now + interval_s
        recognizer.embed_largest(frame)

    return _ExtraModel(
        name="yunet+sface",
        role="face",
        cadence=f"mỗi {interval_s:g} s",
        step=step,
        meta={
            "format": "onnx",
            "interval_s": interval_s,
        },
    )


def build_extras(config: Config, profile: str) -> list[_ExtraModel]:
    builders: list[tuple[bool, Callable[[Config], _ExtraModel]]] = [
        (profile in _PHONE_PROFILES, _build_phone_extra),
        (profile in _FACE_PROFILES, _build_face_extra),
    ]
    extras: list[_ExtraModel] = []
    problems: list[str] = []
    for needed, builder in builders:
        if not needed:
            continue
        try:
            extras.append(builder(config))
        except BenchmarkError as exc:
            problems.append(str(exc))
    if problems:
        raise BenchmarkError(
            problems[0]
            if len(problems) == 1
            else "Hồ sơ này chưa chạy được vì thiếu nhiều phần:\n- "
            + "\n- ".join(problems)
        )
    return extras
