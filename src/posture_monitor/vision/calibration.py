"""Hiệu chỉnh tư thế chuẩn và lưu/đọc ``calibration.json`` (spec v2 §5.4)."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from ..core.atomic_io import write_json_atomic
from .features import ALL_NAMES, VIEWS, Features

MIN_VALID_FRAMES = 20
COUNTDOWN_S = 3.0
CAPTURE_S = 5.0
CALIBRATION_FORMAT_VERSION = 1
DEFAULT_PATH = "calibration.json"


class CalibrationError(ValueError):
    """Không đủ dữ liệu hợp lệ để hiệu chỉnh hoặc file hiệu chỉnh hỏng."""


@dataclass(frozen=True)
class Baseline:
    """Giá trị chuẩn của từng đặc trưng, tính bằng trung vị."""

    values: Mapping[str, float | None]
    view: str
    width: int
    height: int
    created_at: str
    frames: int

    @classmethod
    def empty(cls, *, view: str, width: int, height: int) -> "Baseline":
        """Tạo baseline rỗng (khi chạy chưa hiệu chỉnh) dùng chung cho run/replay/benchmark."""
        return cls(
            values={name: None for name in ALL_NAMES},
            view=view,
            width=int(width),
            height=int(height),
            created_at="",
            frames=0,
        )

    def get(self, name: str) -> float | None:
        return self.values.get(name)

    def __getitem__(self, name: str) -> float | None:
        return self.values[name]

    @property
    def shoulder_width(self) -> float:
        value = self.values.get("shoulder_width")
        if value is None:
            raise CalibrationError(
                "Baseline không có 'shoulder_width'; chạy lại calibrate."
            )
        return float(value)

    @property
    def shoulder_mid_x(self) -> float:
        value = self.values.get("shoulder_mid_x")
        if value is None:
            raise CalibrationError(
                "Baseline không có 'shoulder_mid_x'; chạy lại calibrate."
            )
        return float(value)


def compute_baseline(
    frames: Iterable[Features],
    *,
    view: str,
    width: int,
    height: int,
    min_frames: int = MIN_VALID_FRAMES,
    created_at: str | None = None,
) -> Baseline:
    """Tính baseline từ các khung đã trích đặc trưng."""
    if view not in VIEWS:
        raise ValueError(f"view phải là một trong {VIEWS}, nhận được {view!r}.")

    valid = [
        frame
        for frame in frames
        if frame.person
        and frame.view == view
        and frame.get("shoulder_width") is not None
    ]

    if len(valid) < min_frames:
        raise CalibrationError(
            f"Chỉ có {len(valid)} khung hợp lệ, cần tối thiểu {min_frames}. "
            "Hãy kiểm tra: người ngồi trọn trong khung hình, đủ sáng, camera "
            "nhìn thấy cả hai vai, rồi chạy lại 'calibrate'."
        )

    medians: dict[str, float | None] = {}
    for name in ALL_NAMES:
        samples = [
            float(value)
            for frame in valid
            if (value := frame.get(name)) is not None
            and math.isfinite(float(value))
        ]
        medians[name] = statistics.median(samples) if samples else None

    if medians.get("shoulder_mid_x") is None:
        raise CalibrationError(
            "Không tính được baseline 'shoulder_mid_x'; chạy lại calibrate."
        )

    return Baseline(
        values=medians,
        view=view,
        width=int(width),
        height=int(height),
        created_at=created_at or _now_iso(),
        frames=len(valid),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def save(baseline: Baseline, path: str | Path = DEFAULT_PATH) -> Path:
    """Ghi nguyên tử ``calibration.json``."""
    payload = {
        "version": CALIBRATION_FORMAT_VERSION,
        "baseline": {name: baseline.get(name) for name in ALL_NAMES},
        "camera": {
            "view": baseline.view,
            "width": baseline.width,
            "height": baseline.height,
        },
        "created_at": baseline.created_at,
        "frames": baseline.frames,
    }
    return write_json_atomic(path, payload)


def load(path: str | Path = DEFAULT_PATH) -> Baseline:
    """Đọc ``calibration.json``."""
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Chưa có file hiệu chỉnh '{source}'. Chạy "
            "'python -m posture_monitor calibrate' trước."
        ) from None
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(
            f"Không đọc được file hiệu chỉnh '{source}': {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise CalibrationError(
            f"File hiệu chỉnh '{source}' phải là một ánh xạ JSON."
        )

    version = raw.get("version")
    if version != CALIBRATION_FORMAT_VERSION:
        raise CalibrationError(
            f"File hiệu chỉnh '{source}' có version={version!r}, code cần "
            f"{CALIBRATION_FORMAT_VERSION}. Chạy lại calibrate."
        )

    values_raw = raw.get("baseline")
    camera = raw.get("camera")
    if not isinstance(values_raw, dict) or not isinstance(camera, dict):
        raise CalibrationError(
            f"File hiệu chỉnh '{source}' thiếu mục 'baseline' hoặc 'camera'."
        )

    values: dict[str, float | None] = {}
    for name in ALL_NAMES:
        value = values_raw.get(name)
        if value is None:
            values[name] = None
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CalibrationError(
                f"File hiệu chỉnh '{source}': baseline[{name!r}] phải là số "
                f"hoặc null, nhận được {type(value).__name__}."
            )
        else:
            values[name] = float(value)

    try:
        view = str(camera["view"])
        width = int(camera["width"])
        height = int(camera["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationError(
            f"File hiệu chỉnh '{source}': mục 'camera' thiếu hoặc sai kiểu ({exc})."
        ) from exc

    if view not in VIEWS:
        raise CalibrationError(
            f"File hiệu chỉnh '{source}': view={view!r} không hỗ trợ."
        )

    return Baseline(
        values=values,
        view=view,
        width=width,
        height=height,
        created_at=str(raw.get("created_at", "")),
        frames=int(raw.get("frames", 0) or 0),
    )


def check_environment(
    baseline: Baseline, *, view: str, width: int, height: int
) -> list[str]:
    """So sánh môi trường hiện tại với lúc hiệu chỉnh."""
    warnings: list[str] = []
    if baseline.view != view:
        warnings.append(
            f"Chế độ camera hiện tại là '{view}' nhưng lúc hiệu chỉnh là "
            f"'{baseline.view}'. Baseline sẽ không còn chính xác; nên chạy lại calibrate."
        )
    if (baseline.width, baseline.height) != (int(width), int(height)):
        warnings.append(
            f"Độ phân giải hiện tại là {int(width)}x{int(height)} nhưng lúc "
            f"hiệu chỉnh là {baseline.width}x{baseline.height}. Đặc trưng "
            "theo pixel đã lệch thang đo; nên chạy lại calibrate."
        )
    primary = ("head_height", "shoulder_tilt_deg", "closeness", "lean_x")
    missing = [name for name in primary if baseline.get(name) is None]
    if missing:
        warnings.append(
            "Baseline thiếu đặc trưng " + ", ".join(missing) + "; các nhãn "
            "dựa trên chúng sẽ không được đánh giá."
        )
    return warnings
