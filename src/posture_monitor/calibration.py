"""Hiệu chỉnh tư thế chuẩn và lưu ``calibration.json`` (spec v2 §5.4).

Baseline là **trung vị** từng đặc trưng trên các khung thu được khi người dùng
ngồi đúng tư thế. Trung vị được chọn thay vì trung bình để một vài khung
nhiễu (chớp mắt, xê dịch nhỏ) không kéo lệch baseline.

File lưu thêm độ phân giải, chế độ camera (``view``) và thời điểm hiệu chỉnh
để lần chạy sau phát hiện được môi trường đã đổi. Đổi độ phân giải hoặc đổi
``view`` làm mọi đặc trưng pixel (``shoulder_width``, ``head_height``, ...)
lệch thang đo, nên baseline cũ không còn nghĩa.

Module này **không** mở camera: nó nhận danh sách :class:`Features` đã trích
sẵn. Nhờ vậy unit test chạy được trên PC bằng dữ liệu tổng hợp, đúng tinh
thần spec §9.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from .features import ALL_NAMES, Features, VIEWS

#: Số khung hợp lệ tối thiểu để baseline có nghĩa (spec v2 §5.4).
MIN_VALID_FRAMES = 20

#: Thời gian đếm ngược trước khi thu (giây).
COUNTDOWN_S = 3.0

#: Thời gian thu (giây).
CAPTURE_S = 5.0

#: Định dạng file đã lưu; tăng khi cấu trúc thay đổi để đọc được file cũ.
CALIBRATION_FORMAT_VERSION = 1

DEFAULT_PATH = "calibration.json"


class CalibrationError(ValueError):
    """Không đủ dữ liệu hợp lệ để hiệu chỉnh."""


@dataclass(frozen=True)
class Baseline:
    """Giá trị chuẩn của từng đặc trưng, tính bằng trung vị.

    Đặc trưng thiếu ở mọi khung là ``None``. ``shoulder_width`` và
    ``shoulder_mid_x`` là bắt buộc: thiếu chúng thì mọi phép so sánh tương
    đối (``closeness``, ``lean_x``) vô nghĩa.
    """

    values: Mapping[str, float | None]
    view: str
    width: int
    height: int
    created_at: str
    frames: int

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
    """Tính baseline từ các khung đã trích đặc trưng (spec v2 §5.4).

    Khung không thấy người, sai ``view``, hoặc không có ``shoulder_width``
    (thiếu một trong hai vai) bị loại. Sau khi lọc còn dưới ``min_frames``
    khung thì ném :class:`CalibrationError` kèm hướng dẫn chỉnh camera —
    spec yêu cầu **không** âm thầm hiệu chỉnh bằng dữ liệu thiếu.

    ``median`` chỉ lấy các giá trị khác ``None`` của từng đặc trưng, nên một
    đặc trưng phụ (ví dụ ``head_tilt_deg`` phụ thuộc tai, thường xuyên thiếu
    theo §5.3) vẫn có baseline nếu đủ khung thấy tai.
    """
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
        # Chỉ xảy ra nếu mọi khung đều thiếu vai; đã lọc ở trên nên đây là
        # lỗi lập trình, nhưng vẫn báo rõ thay vì trả baseline hỏng.
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
    """Ghi ``calibration.json`` (spec v2 §5.4).

    Ghi ra file tạm rồi thay thế để lần ghi hỏng giữa chừng không xóa mất
    baseline cũ.
    """
    target = Path(path)
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
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def load(path: str | Path = DEFAULT_PATH) -> Baseline:
    """Đọc ``calibration.json``.

    Raises:
        FileNotFoundError: chưa hiệu chỉnh.
        CalibrationError: file hỏng, sai phiên bản, hoặc thiếu khóa bắt buộc.
    """
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
            f"File hiệu chỉnh '{source}': mục 'camera' thiếu hoặc sai kiểu "
            f"({exc})."
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
    """So sánh môi trường hiện tại với lúc hiệu chỉnh (spec v2 §5.4).

    Returns:
        Danh sách cảnh báo bằng tiếng Việt; rỗng nghĩa là khớp. Hàm **không**
        ném lỗi: spec yêu cầu cảnh báo, không chặn chạy.
    """
    warnings: list[str] = []
    if baseline.view != view:
        warnings.append(
            f"Chế độ camera hiện tại là '{view}' nhưng lúc hiệu chỉnh là "
            f"'{baseline.view}'. Baseline sẽ không còn chính xác; nên chạy "
            "lại calibrate."
        )
    if (baseline.width, baseline.height) != (int(width), int(height)):
        warnings.append(
            f"Độ phân giải hiện tại là {int(width)}x{int(height)} nhưng lúc "
            f"hiệu chỉnh là {baseline.width}x{baseline.height}. Đặc trưng "
            "theo pixel đã lệch thang đo; nên chạy lại calibrate."
        )
    # Chỉ cảnh báo đặc trưng của luật chính. ``head_tilt_deg``/``head_yaw``
    # phụ thuộc keypoint tai (conf thường dưới ngưỡng, spec §5.3) nên thiếu
    # chúng là chuyện bình thường, cảnh báo sẽ chỉ gây nhiễu.
    primary = ("head_height", "shoulder_tilt_deg", "closeness", "lean_x")
    missing = [name for name in primary if baseline.get(name) is None]
    if missing:
        warnings.append(
            "Baseline thiếu đặc trưng " + ", ".join(missing) + "; các nhãn "
            "dựa trên chúng sẽ không được đánh giá."
        )
    return warnings
