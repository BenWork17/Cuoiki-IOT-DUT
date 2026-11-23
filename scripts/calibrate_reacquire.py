"""Đo phân bố thực tế để người dùng tự hiệu chuẩn bốn hằng ``REACQUIRE_*``.

VÌ SAO CÓ CÔNG CỤ NÀY
=====================
``pose.py`` có bốn hằng quyết định khi nào ``PoseEstimator`` được phép bám lại
một track id mới (lỗi "vào phiên học thì mất skeleton"):

======================  =========  ====================================
Hằng                    Mặc định   Ý nghĩa
======================  =========  ====================================
``REACQUIRE_MIN_FRAME_RATIO``  0,05  hộp phải rộng **và** cao ≥ tỉ lệ này
``REACQUIRE_MIN_IOU``           0,1   **hoặc** IoU với hộp trước ≥ mức này
``REACQUIRE_MAX_CENTER_SHIFT_RATIO``  0,5  **hoặc** tâm dịch ≤ mức này
``REACQUIRE_MAX_ASPECT_RATIO``  4,0   hộp không được dẹt quá mức này
======================  =========  ====================================

Cả bốn đều đang ghi trong mã là **"CHƯA đo trên dữ liệu thật"** — người viết
không có camera của bạn. Script này trao cho bạn phép đo đó.

CÁCH DÙNG
=========
::

    # Đo trên camera USB (mặc định usb:0)
    python scripts/calibrate_reacquire.py --frames 300

    # Đo trên một đoạn video đã quay sẵn (không cần camera lúc chạy)
    python scripts/calibrate_reacquire.py --source file:buoi_hoc.mp4 --frames 600

    # Ghi kết quả ra chỗ khác
    python scripts/calibrate_reacquire.py --out .scratch/do_lan_1.json

    # Xem toàn bộ tuỳ chọn
    python scripts/calibrate_reacquire.py --help

Script chạy **đúng ``PoseEstimator`` và đúng ``config.yaml``** như lúc chạy
thật (cùng ``imgsz``, cùng tracker, cùng ngưỡng), nên số đo khớp với hành vi
thực của hệ thống chứ không phải của một bản mô phỏng.

Script đo GÌ
============
Với mỗi cặp hộp **liên tiếp**, script tính:

- ``iou`` — giao trên hợp với hộp trước;
- ``center_px`` và ``center_ratio`` — tâm dịch bao nhiêu pixel, và tỉ lệ so với
  **cạnh dài của hộp trước** (đúng mẫu số mà ``pose.py`` dùng);
- ``frame_ratio_w`` / ``frame_ratio_h`` — bề rộng và chiều cao chia cho cạnh
  tương ứng của khung. **Cổng của ``pose.py`` đòi cả hai**, nên script cũng in
  ``frame_ratio_min`` = giá trị nhỏ hơn — đó mới là đại lượng cần hiệu chuẩn;
- ``aspect`` — ``width / height``;
- ``area_ratio`` — diện tích chia diện tích khung.

Các cặp được chia **hai nhóm riêng**:

1. **CÙNG track id** (khung trước và khung này cùng một id): đây là "người
   dịch nhẹ, track chưa đổi". Cổng bám lại phải **chấp nhận** nhóm này.
2. **KHÁC track id** (id ở khung trước biến mất, một id khác xuất hiện ở khung
   này): đây là "ứng viên thay thế" — có thể là cùng người bị BotSORT đổi id
   (nên chấp nhận) hoặc người khác hẳn (phải từ chối). Script in thêm nhóm
   "khác id trong cùng khung" để bạn thấy hai người cùng lúc trông thế nào.

CÁCH ĐỌC KẾT QUẢ
================
Script in phân vị **p50 / p90 / p99** cho từng đại lượng và tách hai nhóm, rồi
nêu **khoảng trống** giữa chúng, ví dụ::

    IoU   nhóm KHÁC track: p99 = 0,03
    IoU   nhóm CÙNG track: p10 = 0,71
    → khoảng trống: 0,03 … 0,71 — chọn ngưỡng trong khoảng này

Script **không** in một con số duy nhất để chép vào mã. Khoảng trống rộng hay
hẹp là thông tin bạn cần: hẹp nghĩa là cảnh của bạn khó tách, phải quay lại
cảnh khác hoặc chấp nhận đánh đổi.

CẢNH BÁO — KHÔNG CÓ SỐ ĐO NÀO ĐƯỢC TỰ ÁP DỤNG
=============================================
Script này **chỉ đọc và in**. Nó **không** sửa ``pose.py``, **không** sửa
``config.yaml``, **không** ghi đè hằng số nào. Bốn hằng vẫn giữ nguyên giá trị
mặc định sau khi chạy. Muốn áp dụng, bạn tự sửa mã và tự ghi lại số đo cùng
điều kiện đo (camera, ánh sáng, khoảng cách) vào docstring của hằng.

MÃ THOÁT
========
- ``0`` — đo xong, in đủ bảng.
- ``1`` — không mở được nguồn ảnh, không nạp được model, hoặc không đo được
  cặp nào (thiếu dữ liệu). Thông điệp tiếng Việt nói rõ thiếu gì.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence, TextIO

import numpy as np

# Cho phép chạy trực tiếp bằng `python scripts/calibrate_reacquire.py` mà không
# cần cài gói: thêm thư mục src/ vào sys.path (cùng lối với scripts/ khác).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.camera.capture import (  # noqa: E402
    FrameSource,
    capture_from_config,
)
from posture_monitor.core.config import CameraConfig, load_config  # noqa: E402
from posture_monitor.vision import pose as pose_mod  # noqa: E402
from posture_monitor.vision.pose import (  # noqa: E402
    PoseError,
    PoseEstimator,
    # Dùng chính công thức của mã để số đo không bao giờ lệch khỏi hành vi thật.
    _box_center_shift_ratio,  # noqa: PLC2701
    _box_iou,  # noqa: PLC2701
)

#: Số khung mặc định. 300 khung ở ~5 FPS là một phút quay — đủ để thấy phân bố
#: mà không bắt người dùng ngồi chờ lâu. Không phải ngưỡng kỹ thuật.
DEFAULT_FRAMES = 300

#: Nơi ghi JSON mặc định. ``.scratch/`` đã gitignore và không phải ``data/``
#: (``data/`` là chỗ lưu lịch sử thật của ứng dụng — công cụ đo không được
#: trộn tệp của nó vào đó).
DEFAULT_OUT = ".scratch/reacquire_calibration.json"

#: Số khung đọc tối đa khi đóng nguồn — chặn trường hợp nguồn treo.
MAX_SOURCE_FRAMES = 100_000

#: Tên đại lượng đo, theo đúng thứ tự in.
METRICS = (
    "iou",
    "center_px",
    "center_ratio",
    "frame_ratio_w",
    "frame_ratio_h",
    "frame_ratio_min",
    "aspect",
    "area_ratio",
)

#: Nhãn tiếng Việt cho từng đại lượng (in ở bảng).
METRIC_LABELS = {
    "iou": "IoU với hộp trước",
    "center_px": "tâm dịch (px)",
    "center_ratio": "tâm dịch / cạnh dài hộp trước",
    "frame_ratio_w": "bề rộng / bề rộng khung",
    "frame_ratio_h": "chiều cao / chiều cao khung",
    "frame_ratio_min": "min(hai tỉ lệ khung) — cổng đòi cả hai",
    "aspect": "aspect = width / height",
    "area_ratio": "diện tích hộp / diện tích khung",
}


# ---------------------------------------------------------------------------
# Hình học — dùng lại đúng công thức của pose.py
# ---------------------------------------------------------------------------


def box_metrics(
    prev: np.ndarray, cur: np.ndarray, frame_shape
) -> dict[str, float]:
    """Tính các đại lượng của một cặp hộp (hộp trước → hộp hiện tại).

    Dùng lại :func:`pose._box_iou` và :func:`pose._box_center_shift_ratio` thay
    vì viết lại công thức: nếu ``pose.py`` đổi cách tính thì số đo ở đây cũng
    đổi theo, nên không bao giờ lệch khỏi thứ mã thật sự dùng.

    Args:
        prev: ``x1, y1, x2, y2`` của hộp ở khung trước.
        cur: ``x1, y1, x2, y2`` của hộp ở khung hiện tại.
        frame_shape: ``(height, width, ...)`` của khung.

    Returns:
        Dict với các khoá trong :data:`METRICS`. Giá trị ``nan`` khi không
        tính được (khung suy biến) — tầng in sẽ bỏ qua ``nan``.
    """
    prev = np.asarray(prev, dtype=np.float32).reshape(4)
    cur = np.asarray(cur, dtype=np.float32).reshape(4)

    width = max(0.0, float(cur[2] - cur[0]))
    height = max(0.0, float(cur[3] - cur[1]))

    try:
        frame_h = float(frame_shape[0])
        frame_w = float(frame_shape[1])
    except (TypeError, IndexError, ValueError):  # pragma: no cover - phòng vệ
        frame_h = frame_w = 0.0

    if frame_h > 0.0 and frame_w > 0.0:
        ratio_w = width / frame_w
        ratio_h = height / frame_h
        area_ratio = (width * height) / (frame_w * frame_h)
    else:  # pragma: no cover - chỉ khi khung hỏng
        ratio_w = ratio_h = area_ratio = float("nan")

    aspect = width / height if height > 0.0 else float("nan")
    dx = (float(cur[0]) + float(cur[2]) - float(prev[0]) - float(prev[2])) / 2.0
    dy = (float(cur[1]) + float(cur[3]) - float(prev[1]) - float(prev[3])) / 2.0
    center_px = float(np.hypot(dx, dy))
    center_ratio = float(_box_center_shift_ratio(cur, prev))
    if not np.isfinite(center_ratio):  # hộp trước suy biến
        center_ratio = float("nan")

    return {
        "iou": float(_box_iou(cur, prev)),
        "center_px": center_px,
        "center_ratio": center_ratio,
        "frame_ratio_w": float(ratio_w),
        "frame_ratio_h": float(ratio_h),
        "frame_ratio_min": float(min(ratio_w, ratio_h))
        if np.isfinite(ratio_w) and np.isfinite(ratio_h)
        else float("nan"),
        "aspect": float(aspect),
        "area_ratio": float(area_ratio),
    }


# ---------------------------------------------------------------------------
# Thu thập cặp từ chuỗi phát hiện
# ---------------------------------------------------------------------------


def _as_detections(raw: Any) -> list[tuple[int, np.ndarray]]:
    """Đổi ``(xyxy, ids)`` của một khung thành ``[(id, hộp), ...]``.

    Bỏ hộp không có id (tracking tắt thì không đo được "cùng track" — đó là
    giới hạn của phép đo, không phải lỗi). Bỏ luôn hộp suy biến.
    """
    if raw is None:
        return []
    xyxy, ids = raw
    if ids is None:
        return []
    boxes = np.asarray(xyxy, dtype=np.float32)
    out: list[tuple[int, np.ndarray]] = []
    for index, track_id in enumerate(ids):
        if index >= len(boxes):
            break
        box = boxes[index]
        width = float(box[2] - box[0])
        height = float(box[3] - box[1])
        if width <= 0.0 or height <= 0.0:
            continue
        out.append((int(track_id), box))
    return out


def collect_from_detections(
    detections: Sequence[tuple[Any, Any, Any]],
) -> dict[str, list[dict[str, float]]]:
    """Gom các cặp hộp từ chuỗi ``(xyxy, ids, frame_shape)`` của từng khung.

    Args:
        detections: iterable, mỗi phần tử là ``(xyxy, ids, frame_shape)`` của
            một khung, đúng thứ tự thời gian. ``ids`` là ``None`` khi tracking
            tắt (khi đó không đo được "cùng track" — giới hạn của phép đo).

    Returns:
        Dict ba khoá:

        - ``"same_track"`` — cùng id ở hai khung liền nhau (nhóm phải ĐƯỢC
          chấp nhận bởi cổng bám lại);
        - ``"different_track"`` — id ở khung trước mất, id khác xuất hiện ở
          khung này (nhóm "ứng viên thay thế");
        - ``"same_frame"`` — hai id khác nhau trong **cùng** một khung (để thấy
          hai người cùng lúc trông thế nào).

        Mỗi phần tử là dict từ :func:`box_metrics` cộng thêm ``id_prev`` và
        ``id_cur``.
    """
    same_track: list[dict[str, float]] = []
    different_track: list[dict[str, float]] = []
    same_frame: list[dict[str, float]] = []

    previous: list[tuple[int, np.ndarray]] = []
    for xyxy, ids, shape in detections:
        current = _as_detections((xyxy, ids))
        if previous:
            prev_by_id = dict(previous)
            for track_id, box in current:
                if track_id in prev_by_id:
                    item = box_metrics(prev_by_id[track_id], box, shape)
                    item["id_prev"] = float(track_id)
                    item["id_cur"] = float(track_id)
                    same_track.append(item)
            for prev_id, prev_box in previous:
                for cur_id, cur_box in current:
                    if cur_id != prev_id:
                        item = box_metrics(prev_box, cur_box, shape)
                        item["id_prev"] = float(prev_id)
                        item["id_cur"] = float(cur_id)
                        different_track.append(item)
            for i, (id_a, box_a) in enumerate(current):
                for id_b, box_b in current[i + 1 :]:
                    item = box_metrics(box_a, box_b, shape)
                    item["id_prev"] = float(id_a)
                    item["id_cur"] = float(id_b)
                    same_frame.append(item)
        previous = current
    return {
        "same_track": same_track,
        "different_track": different_track,
        "same_frame": same_frame,
    }


# ---------------------------------------------------------------------------
# Thống kê
# ---------------------------------------------------------------------------


#: Các phân vị cần tính. Không chỉ p50/p90/p99: gợi ý ngưỡng cần **đuôi đối
#: diện** của mỗi nhóm — p10 của nhóm "cùng track" (mức giống nhau *kém nhất*
#: mà cổng còn phải chấp nhận) và p1 của nhóm "khác track" (mức *giống nhất*
#: mà cổng còn phải từ chối). Thiếu hai mốc đó thì không nêu được khoảng trống.
PERCENTILE_POINTS = (1, 10, 50, 90, 99)


def percentiles(
    values: Sequence[float], points: Sequence[float] = PERCENTILE_POINTS
) -> dict[str, float]:
    """Phân vị của ``values``; bỏ ``nan``/``inf``. Rỗng thì trả ``{}``.

    Dùng nội suy tuyến tính (mặc định của ``numpy.percentile``) để p99 của một
    mẫu nhỏ vẫn có nghĩa thay vì nhảy bậc.
    """
    clean = [float(v) for v in values if np.isfinite(v)]
    if not clean:
        return {}
    array = np.asarray(clean, dtype=float)
    return {
        f"p{int(point)}": float(np.percentile(array, point)) for point in points
    }


def summarize(groups: dict[str, list[dict[str, float]]]) -> dict[str, Any]:
    """Tính phân vị cho từng nhóm × từng đại lượng, kèm số mẫu.

    Đại lượng không có trong mẫu (ví dụ dict tổng hợp chỉ có ``iou``) được bỏ
    qua thay vì ném ``KeyError`` — tầng in cũng bỏ qua đại lượng rỗng.
    """
    summary: dict[str, Any] = {}
    for group_name, items in groups.items():
        block: dict[str, Any] = {"count": len(items)}
        for metric in METRICS:
            values = [item[metric] for item in items if metric in item]
            block[metric] = percentiles(values)
        summary[group_name] = block
    return summary


def suggest_gaps(summary: dict[str, Any]) -> dict[str, Any]:
    """Nêu **khoảng trống** giữa hai nhóm cho **hai đại lượng đo độ giống nhau**.

    Chỉ ``iou`` và ``center_ratio`` là thước đo "hai hộp này giống nhau tới
    đâu", nên chỉ chúng mới có khái niệm khoảng trống giữa "cùng người" và
    "khác người":

    - ``iou``: càng **cao** càng giống. Khoảng = [p99 nhóm khác-track,
      p10 nhóm cùng-track].
    - ``center_ratio``: càng **thấp** càng giống. Khoảng = [p90 nhóm
      cùng-track, p1 nhóm khác-track].

    **Vì sao KHÔNG nêu khoảng cho ``frame_ratio``, ``aspect``, ``area_ratio``:**
    đó là các đại lượng **kích thước/hình dáng tuyệt đối**, không phải độ
    giống nhau. Nhóm "khác track" chứa lẫn cả *cùng người bị đổi id* (kích
    thước y hệt, phải chấp nhận) lẫn *người khác hẳn*, nên phân bố kích thước
    của nó trải rộng và chồng lên nhóm cùng-track một cách tự nhiên. Nêu một
    "khoảng trống" từ hai phân bố đó là **bịa**. Với hai đại lượng này, script
    chỉ in phân bố để người dùng tự xem, đúng như yêu cầu "chỉ ĐO và IN".

    Returns:
        Dict theo tên đại lượng, mỗi mục có ``lower``/``upper``/``empty``/
        ``better``. Rỗng nếu thiếu một trong hai nhóm.
    """
    gaps: dict[str, Any] = {}
    same = summary.get("same_track") or {}
    diff = summary.get("different_track") or {}

    s_iou = (same.get("iou") or {}).get("p10")
    d_iou = (diff.get("iou") or {}).get("p99")
    if s_iou is not None and d_iou is not None:
        gaps["iou"] = {
            "lower": d_iou,
            "upper": s_iou,
            "empty": not (d_iou < s_iou),
            "better": "cao hơn = giống nhau hơn",
        }

    s_shift = (same.get("center_ratio") or {}).get("p90")
    d_shift = (diff.get("center_ratio") or {}).get("p1")
    if s_shift is not None and d_shift is not None:
        gaps["center_ratio"] = {
            "lower": s_shift,
            "upper": d_shift,
            "empty": not (s_shift < d_shift),
            "better": "thấp hơn = giống nhau hơn",
        }
    return gaps


# ---------------------------------------------------------------------------
# In báo cáo
# ---------------------------------------------------------------------------


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    if not np.isfinite(value):
        return "—"
    if abs(value) >= 1000:
        return f"{value:.0f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.4f}"


def _print_group(out: TextIO, title: str, block: dict[str, Any], note: str) -> None:
    print(f"  {title}", file=out)
    print(f"    {note}", file=out)
    count = block.get("count", 0)
    print(f"    số cặp: {count}", file=out)
    if not count:
        print("    (không có cặp nào — xem cảnh báo bên dưới)", file=out)
        print(file=out)
        return
    header = f"    {'Đại lượng':<34}{'p50':>10}{'p90':>10}{'p99':>10}"
    print(header, file=out)
    print("    " + "-" * 64, file=out)
    for metric in METRICS:
        stats = block.get(metric) or {}
        if not stats:
            continue
        print(
            f"    {METRIC_LABELS[metric]:<34}"
            f"{_fmt(stats.get('p50')):>10}"
            f"{_fmt(stats.get('p90')):>10}"
            f"{_fmt(stats.get('p99')):>10}",
            file=out,
        )
    print(file=out)


#: Hằng số của ``pose.py`` gắn với từng đại lượng, để bảng gợi ý nêu đúng tên.
GATE_FOR_METRIC = {
    "iou": "REACQUIRE_MIN_IOU",
    "center_ratio": "REACQUIRE_MAX_CENTER_SHIFT_RATIO",
    "frame_ratio_min": "REACQUIRE_MIN_FRAME_RATIO",
    "aspect": "REACQUIRE_MAX_ASPECT_RATIO",
}


def _print_gaps(out: TextIO, gaps: dict[str, Any]) -> None:
    print("  GỢI Ý NGƯỠNG — KHÔNG CÓ SỐ DUY NHẤT, CHỌN TRONG KHOẢNG TRỐNG", file=out)
    print(file=out)
    if not gaps:
        print(
            "    (thiếu một trong hai nhóm nên chưa nêu được khoảng trống — "
            "xem cảnh báo bên trên)",
            file=out,
        )
        print(file=out)
    for metric, gap in gaps.items():
        gate = GATE_FOR_METRIC.get(metric, f"(đại lượng {metric})")
        print(f"    {gate}  ← theo dõi '{METRIC_LABELS[metric]}'", file=out)
        lower = _fmt(gap["lower"])
        upper = _fmt(gap["upper"])
        if gap["empty"]:
            print(
                f"      KHOẢNG RỖNG: {lower} … {upper} — hai nhóm chồng lên nhau "
                f"trên cảnh này; đại lượng này KHÔNG tách được chúng. "
                f"Quay cảnh khác hoặc chấp nhận đánh đổi.",
                file=out,
            )
        else:
            print(
                f"      khoảng trống: {lower} … {upper} — chọn một giá trị "
                f"trong khoảng này ({gap['better']}).",
                file=out,
            )
        print(file=out)

    # Luôn in bốn hằng hiện có, kể cả khi chưa nêu được khoảng — người dùng cần
    # biết mình đang so với con số nào.
    print("  Bốn hằng ĐANG CÓ trong pose.py (để đối chiếu, KHÔNG bị sửa):", file=out)
    for gate, value in (
        ("REACQUIRE_MIN_IOU", pose_mod.REACQUIRE_MIN_IOU),
        ("REACQUIRE_MAX_CENTER_SHIFT_RATIO", pose_mod.REACQUIRE_MAX_CENTER_SHIFT_RATIO),
        ("REACQUIRE_MIN_FRAME_RATIO", pose_mod.REACQUIRE_MIN_FRAME_RATIO),
        ("REACQUIRE_MAX_ASPECT_RATIO", pose_mod.REACQUIRE_MAX_ASPECT_RATIO),
    ):
        print(f"    {gate} = {value}", file=out)
    print(file=out)


# ---------------------------------------------------------------------------
# Nguồn ảnh
# ---------------------------------------------------------------------------


def _open_source(source_text: str) -> FrameSource | None:
    """Mở nguồn ảnh qua đúng đường của ứng dụng chính."""
    from types import SimpleNamespace  # noqa: PLC0415 - chỉ cần ở đây

    config = SimpleNamespace(camera=CameraConfig(source=source_text))
    return capture_from_config(config)


def _default_source() -> str:
    """Nguồn mặc định: ``config.yaml`` → biến môi trường → ``usb:0``."""
    try:
        config = load_config(_REPO_ROOT / "config.yaml")
        source = getattr(getattr(config, "camera", None), "source", "")
        if source:
            return str(source)
    except Exception:  # noqa: BLE001 - thiếu/hỏng config không được chặn đo
        pass
    return "usb:0"


def _build_estimator() -> PoseEstimator:
    """Dựng ``PoseEstimator`` với **đúng** config đang chạy thật."""
    config = load_config(_REPO_ROOT / "config.yaml")
    return PoseEstimator(config)


def _detect_boxes(estimator: PoseEstimator, frame: np.ndarray):
    """Lấy **toàn bộ** hộp + id của khung, không chỉ người đang chọn.

    ``PoseEstimator.detect`` chỉ trả người đang theo dõi, nhưng công cụ này cần
    mọi cặp (cả nhóm "khác track"), nên gọi thẳng ``_infer`` — tầng suy luận
    mà ``detect`` cũng dùng. Không sửa ``pose.py``: chỉ đọc kết quả thô.
    """
    results = estimator._infer(frame)  # noqa: PLC2701 - cần mọi hộp, không chỉ 1
    if not results:
        return np.zeros((0, 4), np.float32), None
    result = results[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return np.zeros((0, 4), np.float32), None
    xyxy = np.asarray(boxes.xyxy.cpu().numpy(), dtype=np.float32)
    ids = None
    if getattr(boxes, "id", None) is not None:
        ids = [int(value) for value in boxes.id.cpu().numpy().tolist()]
    return xyxy, ids


def collect_from_source(
    open_source: Callable[[str], FrameSource | None],
    source_text: str,
    estimator: PoseEstimator,
    max_frames: int,
    *,
    stderr: TextIO | None = None,
) -> tuple[list[tuple[Any, Any, Any]], int]:
    """Đọc ``max_frames`` khung từ nguồn và trả ``(detections, số_khung_đọc)``.

    Mỗi phần tử là ``(xyxy, ids, frame_shape)``. Không ném lỗi khi nguồn chết
    giữa chừng: dừng và trả những gì đã đọc được, vì một đoạn video ngắn vẫn
    cho phân bố có ích.
    """
    err = stderr if stderr is not None else sys.stderr
    detections: list[tuple[Any, Any, Any]] = []
    source = open_source(source_text)
    if source is None:
        print(f"  LỖI: không mở được nguồn ảnh '{source_text}'.", file=err)
        return detections, 0
    read_count = 0
    try:
        for _ in range(max(0, min(int(max_frames), MAX_SOURCE_FRAMES))):
            frame = source.read()
            if frame is None:
                break
            read_count += 1
            xyxy, ids = _detect_boxes(estimator, frame)
            detections.append((xyxy, ids, getattr(frame, "shape", None)))
    finally:
        try:
            source.close()
        except Exception:  # noqa: BLE001 - đóng lỗi không được che kết quả đo
            pass
    return detections, read_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Tham số dòng lệnh, toàn bộ trợ giúp bằng tiếng Việt."""
    defaults = (
        f"REACQUIRE_MIN_FRAME_RATIO={pose_mod.REACQUIRE_MIN_FRAME_RATIO}, "
        f"REACQUIRE_MIN_IOU={pose_mod.REACQUIRE_MIN_IOU}, "
        f"REACQUIRE_MAX_CENTER_SHIFT_RATIO="
        f"{pose_mod.REACQUIRE_MAX_CENTER_SHIFT_RATIO}, "
        f"REACQUIRE_MAX_ASPECT_RATIO={pose_mod.REACQUIRE_MAX_ASPECT_RATIO}"
    )
    parser = argparse.ArgumentParser(
        prog="calibrate_reacquire",
        description=(
            "Đo phân bố IoU / khoảng cách tâm / tỉ lệ khung / aspect của các "
            "cặp hộp liên tiếp trên CẢNH CỦA BẠN, để bạn tự chọn ngưỡng cho "
            "bốn hằng REACQUIRE_* trong pose.py. Chỉ đọc và in — không sửa "
            "pose.py, không sửa config.yaml, không áp dụng số đo nào."
        ),
        epilog=(
            "Giá trị đang có trong mã (CHƯA đo trên dữ liệu thật): "
            f"{defaults}. "
            "Cách đọc kết quả: mỗi đại lượng in phân vị p50/p90/p99 cho hai "
            "nhóm 'cùng track' và 'khác track'; ngưỡng tốt nằm trong KHOẢNG "
            "TRỐNG giữa hai nhóm. Khoảng rỗng nghĩa là cảnh này khó tách bằng "
            "đại lượng đó. Xem docstring đầu tệp để biết chi tiết."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        default=None,
        help=(
            "nguồn ảnh, cùng cú pháp với camera.source: 'usb:0', "
            "'picamera', 'file:duong/dan/video.mp4', 'rtsp:rtsp://...'. "
            f"Mặc định: lấy từ config.yaml, không có thì usb:0"
        ),
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=DEFAULT_FRAMES,
        help=(
            f"số khung cần đọc (mặc định {DEFAULT_FRAMES}). Ở ~5 FPS, 300 "
            f"khung là khoảng một phút quay."
        ),
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=(
            f"tệp JSON để ghi kết quả (mặc định {DEFAULT_OUT}). Không bao giờ "
            f"ghi vào data/ — đó là chỗ lưu lịch sử thật của ứng dụng."
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    source_factory: Callable[[str], FrameSource | None] | None = None,
    estimator_factory: Callable[[], PoseEstimator] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Chạy công cụ; trả mã thoát. Tham số tiêm được để test không cần camera."""
    _ensure_utf8_stdio()
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    args = build_parser().parse_args(list(argv) if argv is not None else None)

    source_text = str(args.source) if args.source else _default_source()
    frames = int(args.frames)
    out_path = Path(args.out)

    print("=" * 74, file=out)
    print("  ĐO NGƯỠNG BÁM LẠI TRACK — Hệ thống giám sát tư thế", file=out)
    print("=" * 74, file=out)
    print(f"  Nguồn ảnh : {source_text}", file=out)
    print(f"  Số khung  : {frames}", file=out)
    print(file=out)

    if frames <= 0:
        print("  LỖI: --frames phải là số dương.", file=err)
        return 1

    make_estimator = estimator_factory or _build_estimator
    try:
        estimator = make_estimator()
    except PoseError as exc:
        print("  LỖI: không nạp được model pose nên không đo được.", file=err)
        print(f"  Chi tiết: {exc}", file=err)
        print(
            "  Cách xử lý: đặt trọng số yolo11n-pose.pt vào thư mục gốc repo "
            "(hoặc để ultralytics tự tải ở lần chạy đầu), rồi chạy lại. "
            "Script không tự tải và không cần mạng để chạy phần còn lại.",
            file=err,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - thiếu thư viện cũng phải báo rõ
        print(f"  LỖI: không dựng được PoseEstimator ({exc}).", file=err)
        print(
            "  Kiểm tra đã cài ultralytics + torch chưa (xem requirements.txt).",
            file=err,
        )
        return 1

    open_source = source_factory or _open_source
    detections, read_count = collect_from_source(
        open_source, source_text, estimator, frames, stderr=err
    )

    print(f"  Đã đọc {read_count} khung.", file=out)
    if read_count == 0:
        print(
            "  LỖI: không đọc được khung nào từ nguồn trên nên chưa có gì để đo.",
            file=err,
        )
        print(
            "  Kiểm tra: camera đã cắm chưa (usb:0), đường dẫn video có đúng "
            "không (file:...), hoặc thử 'python scripts/camera_probe.py'.",
            file=err,
        )
        return 1

    groups = collect_from_detections(detections)
    summary = summarize(groups)
    gaps = suggest_gaps(summary)

    with_tracks = sum(1 for item in detections if item[1] is not None)
    print(f"  Khung có track id: {with_tracks}/{read_count}", file=out)
    if with_tracks == 0:
        print(
            "  CẢNH BÁO: không khung nào có track id. Nhiều khả năng "
            "tracking đang tắt trong config.yaml (tracking.enabled: false) — "
            "khi đó không có 'cùng track' để so và công cụ này không dùng được. "
            "Bật tracking rồi chạy lại.",
            file=out,
        )
    print(file=out)

    _print_group(
        out,
        "NHÓM 1 — CÙNG track id (người dịch nhẹ; cổng bám lại PHẢI chấp nhận)",
        summary.get("same_track") or {},
        "Hai khung liền nhau, cùng một id: đây là lúc track chưa đổi.",
    )
    _print_group(
        out,
        "NHÓM 2 — KHÁC track id, khung liền sau (ứng viên thay thế)",
        summary.get("different_track") or {},
        "Id cũ mất, id khác xuất hiện. Gồm cả ca 'cùng người bị đổi id' "
        "(nên chấp nhận) lẫn 'người khác hẳn' (phải từ chối).",
    )
    _print_group(
        out,
        "NHÓM 3 — HAI id KHÁC NHAU trong CÙNG một khung (để tham khảo)",
        summary.get("same_frame") or {},
        "Hai người cùng lúc trong khung — mốc so sánh cho 'khác người'.",
    )

    _print_gaps(out, gaps)

    payload = {
        "source": source_text,
        "frames_requested": frames,
        "frames_read": read_count,
        "frames_with_tracking": with_tracks,
        "frame_shape": list(detections[-1][2]) if detections and detections[-1][2] else None,
        "summary": summary,
        "suggested_gaps": gaps,
        "gate_values_in_code": {
            "REACQUIRE_MIN_FRAME_RATIO": pose_mod.REACQUIRE_MIN_FRAME_RATIO,
            "REACQUIRE_MIN_IOU": pose_mod.REACQUIRE_MIN_IOU,
            "REACQUIRE_MAX_CENTER_SHIFT_RATIO": (
                pose_mod.REACQUIRE_MAX_CENTER_SHIFT_RATIO
            ),
            "REACQUIRE_MAX_ASPECT_RATIO": pose_mod.REACQUIRE_MAX_ASPECT_RATIO,
        },
        "note": (
            "Số đo chỉ để tham khảo. Công cụ này KHÔNG sửa pose.py và KHÔNG "
            "áp dụng giá trị nào vào config."
        ),
    }

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        print(f"  CẢNH BÁO: không ghi được JSON ra '{out_path}' ({exc}).", file=err)
        print("  Bảng ở trên vẫn dùng được.", file=err)
    else:
        print(f"  Đã ghi kết quả: {out_path}", file=out)

    print(file=out)
    print("  LƯU Ý: công cụ này CHỈ ĐO. Không có số nào được tự áp vào mã.", file=out)
    print(
        "  Muốn dùng, bạn tự sửa hằng trong src/posture_monitor/vision/pose.py và tự "
        "ghi lại điều kiện đo (camera, ánh sáng, khoảng cách) vào docstring.",
        file=out,
    )
    return 0


def _ensure_utf8_stdio() -> None:
    """Ép ``stdout``/``stderr`` sang UTF-8 khi có thể.

    Thông điệp là tiếng Việt. Trên Windows, khi đầu ra bị chuyển hướng,
    ``sys.stdout`` mặc định dùng code page ANSI và ``print`` ném
    ``UnicodeEncodeError`` giữa chừng — công cụ chết trước khi in xong bảng.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
