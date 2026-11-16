"""Kiểm thử ``scripts/calibrate_reacquire.py`` bằng hộp tổng hợp.

Không cần camera, không cần model, không cần mạng: mọi phép đo ở đây chạy trên
hộp dựng bằng numpy và trên một ``FrameSource`` giả. Đó chính là điểm mạnh của
thiết kế script — toàn bộ phần tính toán tách khỏi phần đọc camera, nên kiểm
được mà không cần phần cứng.

Cái được khoá:

1. ``box_metrics`` tính đúng IoU / tâm dịch / tỉ lệ khung / aspect trên số
   tổng hợp (so với giá trị tính tay).
2. Ba nhóm cặp được tách đúng: cùng track, khác track, hai id trong cùng khung.
3. Phân vị p50/p90/p99 đúng và bỏ ``nan``.
4. ``suggest_gaps`` nêu **khoảng** (hai đầu), không trả một số duy nhất; và
   phát hiện đúng khoảng rỗng khi hai nhóm chồng nhau.
5. ``main`` chạy được đầu-cuối với nguồn + estimator giả, ghi JSON, và in bảng
   có cả hai nhóm + phần gợi ý.
6. ``main`` báo lỗi tiếng Việt (không crash) khi không có trọng số.
7. Không có số đo nào bị áp vào ``pose.py``: chạy xong, bốn hằng ``REACQUIRE_*``
   vẫn đúng giá trị cũ.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for _path in (str(_SRC), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import calibrate_reacquire as cal  # noqa: E402
from posture_monitor import pose as pose_mod  # noqa: E402

#: Khung tổng hợp 640x480 — cùng kích thước với camera thật của dự án.
FRAME_SHAPE = (480, 640, 3)


class _Scratch:
    """Thư mục tạm tự quản, KHÔNG dùng fixture ``tmp_path``.

    Vì sao không dùng ``tmp_path``: sandbox của máy này chặn mọi thư mục tạo
    bằng ``mkdir(mode=0o700)``, mà pytest luôn tạo ``tmp_path`` đúng mode đó.
    Sáu bài dưới đây sẽ đỏ vì lý do **môi trường**, không phải vì mã — và
    lệnh verify của hợp đồng không nạp plugin vá mode. Dùng ``os.makedirs``
    với mode mặc định (``0o777``) là thư mục quét được, nên bộ test này chạy
    đúng bằng lệnh trần.

    Thư mục nằm trong ``.scratch/`` (đã gitignore), không phải ``data/``.
    """

    def __init__(self, name: str) -> None:
        self.path = _REPO_ROOT / ".scratch" / f"calib_test_{name}"

    def __enter__(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        # Dọn tệp cũ để mỗi lần chạy thấy đúng thứ bài test vừa ghi.
        for stale in self.path.glob("*.json"):
            try:
                stale.unlink()
            except OSError:  # pragma: no cover - phòng vệ
                pass
        return self.path

    def __exit__(self, *exc_info) -> None:
        for item in self.path.glob("*"):
            try:
                item.unlink()
            except OSError:  # pragma: no cover - phòng vệ
                pass
        try:
            self.path.rmdir()
        except OSError:  # pragma: no cover - phòng vệ
            pass


# --------------------------------------------------------------------------
# box_metrics — số tổng hợp, đối chiếu tính tay
# --------------------------------------------------------------------------


def test_box_metrics_identical_boxes():
    """Hộp không đổi: IoU = 1, tâm dịch = 0, tỉ lệ khung đúng."""
    box = np.array([100.0, 100.0, 300.0, 400.0], dtype=np.float32)

    m = cal.box_metrics(box, box, FRAME_SHAPE)

    assert m["iou"] == pytest.approx(1.0)
    assert m["center_px"] == pytest.approx(0.0)
    assert m["center_ratio"] == pytest.approx(0.0)
    # 200/640 và 300/480.
    assert m["frame_ratio_w"] == pytest.approx(200 / 640)
    assert m["frame_ratio_h"] == pytest.approx(300 / 480)
    assert m["frame_ratio_min"] == pytest.approx(200 / 640)
    assert m["aspect"] == pytest.approx(200 / 300)


def test_box_metrics_known_iou():
    """IoU của hai hộp chồng lấn một nửa — so với giá trị tính tay."""
    prev = np.array([0.0, 0.0, 100.0, 100.0], dtype=np.float32)
    cur = np.array([50.0, 0.0, 150.0, 100.0], dtype=np.float32)

    m = cal.box_metrics(prev, cur, FRAME_SHAPE)

    # Giao 50x100 = 5000; hợp 2*10000 - 5000 = 15000.
    assert m["iou"] == pytest.approx(5000 / 15000)
    assert m["center_px"] == pytest.approx(50.0)
    # Cạnh dài hộp trước = 100, nên tỉ lệ = 0,5.
    assert m["center_ratio"] == pytest.approx(0.5)


def test_box_metrics_disjoint_boxes_have_zero_iou():
    """Hai hộp rời nhau: IoU = 0 nhưng tâm vẫn đo được."""
    prev = np.array([0.0, 0.0, 100.0, 100.0], dtype=np.float32)
    cur = np.array([500.0, 300.0, 600.0, 400.0], dtype=np.float32)

    m = cal.box_metrics(prev, cur, FRAME_SHAPE)

    assert m["iou"] == pytest.approx(0.0)
    assert m["center_px"] > 0.0
    assert m["center_ratio"] > 0.5


def test_box_metrics_flat_box_has_large_aspect():
    """Mép bàn 400x4 phải cho aspect rất lớn — đúng thứ cổng aspect chặn."""
    prev = np.array([100.0, 300.0, 500.0, 304.0], dtype=np.float32)

    m = cal.box_metrics(prev, prev, FRAME_SHAPE)

    assert m["aspect"] == pytest.approx(400 / 4)
    assert m["aspect"] > pose_mod.REACQUIRE_MAX_ASPECT_RATIO
    # frame_ratio_min lấy chiều cao vì nó nhỏ hơn — cổng của pose.py đòi cả hai.
    assert m["frame_ratio_min"] == pytest.approx(4 / 480)


def test_box_metrics_zero_height_is_nan_not_crash():
    """Hộp suy biến cho ``nan`` thay vì ném ZeroDivisionError."""
    prev = np.array([0.0, 10.0, 100.0, 10.0], dtype=np.float32)

    m = cal.box_metrics(prev, prev, FRAME_SHAPE)

    assert np.isnan(m["aspect"])


# --------------------------------------------------------------------------
# collect_from_detections — tách ba nhóm
# --------------------------------------------------------------------------


def _frame(boxes, ids, shape=FRAME_SHAPE):
    return (np.asarray(boxes, dtype=np.float32), ids, shape)


def test_collect_separates_same_and_different_track():
    """Cùng id → nhóm 1; id đổi → nhóm 2; hai id trong khung → nhóm 3."""
    home = [100.0, 100.0, 300.0, 400.0]
    nudge = [110.0, 105.0, 310.0, 405.0]
    far = [450.0, 50.0, 620.0, 300.0]

    detections = [
        _frame([home], [7]),
        _frame([nudge], [7]),          # cùng track 7, dịch nhẹ
        _frame([far], [13]),           # id đổi sang người khác ở chỗ khác
        _frame([far, home], [13, 21]),  # hai người cùng lúc
    ]

    groups = cal.collect_from_detections(detections)

    # Hai cặp cùng track: 7→7 (dịch nhẹ) và 13→13 (đứng yên).
    assert len(groups["same_track"]) == 2, "id 7→7 và id 13→13"
    id7_pair = [
        item for item in groups["same_track"] if item["id_prev"] == 7.0
    ]
    assert len(id7_pair) == 1
    assert id7_pair[0]["iou"] > 0.5, "người dịch nhẹ vẫn chồng lấn nhiều"

    # Khung 2→3: id 7 mất, id 13 xuất hiện ở chỗ khác hẳn.
    pairs_2_3 = [
        item
        for item in groups["different_track"]
        if item["id_prev"] == 7.0 and item["id_cur"] == 13.0
    ]
    assert len(pairs_2_3) == 1
    assert pairs_2_3[0]["iou"] == pytest.approx(0.0), "người khác chỗ khác"

    # Khung 4 có hai id → một cặp trong cùng khung.
    assert len(groups["same_frame"]) == 1
    assert groups["same_frame"][0]["iou"] == pytest.approx(0.0)


def test_collect_ignores_frames_without_ids():
    """``ids is None`` (tracking tắt) không tạo cặp nào, không ném lỗi."""
    detections = [
        _frame([[0.0, 0.0, 10.0, 10.0]], None),
        _frame([[0.0, 0.0, 10.0, 10.0]], None),
    ]

    groups = cal.collect_from_detections(detections)

    assert groups == {"same_track": [], "different_track": [], "same_frame": []}


def test_collect_skips_degenerate_boxes():
    """Hộp rộng hoặc cao bằng 0 bị bỏ, không làm hỏng phép đo."""
    detections = [
        _frame([[10.0, 10.0, 10.0, 50.0]], [7]),  # rộng 0
        _frame([[10.0, 10.0, 60.0, 50.0]], [7]),
    ]

    groups = cal.collect_from_detections(detections)

    assert groups["same_track"] == [], "hộp suy biến bị bỏ nên không có cặp"


# --------------------------------------------------------------------------
# percentiles / summarize / suggest_gaps
# --------------------------------------------------------------------------


def test_percentiles_on_known_values():
    """p50/p90/p99 của dãy 1..100 — so với numpy."""
    values = list(range(1, 101))

    stats = cal.percentiles(values)

    assert stats["p50"] == pytest.approx(50.5)
    assert stats["p90"] == pytest.approx(90.1)
    assert stats["p99"] == pytest.approx(99.01)


def test_percentiles_drops_nan_and_inf():
    """``nan``/``inf`` bị loại, không làm hỏng phân vị."""
    values = [1.0, 2.0, float("nan"), 3.0, float("inf")]

    stats = cal.percentiles(values)

    assert stats["p50"] == pytest.approx(2.0)


def test_percentiles_empty_returns_empty():
    assert cal.percentiles([]) == {}
    assert cal.percentiles([float("nan")]) == {}


def test_summarize_counts_each_group():
    """``summarize`` báo đúng số mẫu từng nhóm."""
    groups = {
        "same_track": [{"iou": 0.9, "center_px": 5.0}],
        "different_track": [{"iou": 0.0, "center_px": 300.0}] * 3,
    }

    summary = cal.summarize(groups)

    assert summary["same_track"]["count"] == 1
    assert summary["different_track"]["count"] == 3


def test_suggest_gaps_returns_range_not_single_number():
    """Gợi ý phải là **khoảng** hai đầu, không phải một con số."""
    summary = {
        "same_track": {"iou": {"p10": 0.80}, "center_ratio": {"p90": 0.10}},
        "different_track": {"iou": {"p99": 0.02}, "center_ratio": {"p1": 0.60}},
    }

    gaps = cal.suggest_gaps(summary)

    assert gaps["iou"]["lower"] == pytest.approx(0.02)
    assert gaps["iou"]["upper"] == pytest.approx(0.80)
    assert gaps["iou"]["empty"] is False
    assert gaps["center_ratio"]["lower"] == pytest.approx(0.10)
    assert gaps["center_ratio"]["upper"] == pytest.approx(0.60)


def test_suggest_gaps_flags_empty_when_groups_overlap():
    """Hai nhóm chồng nhau → ``empty`` True, không bịa ngưỡng."""
    summary = {
        "same_track": {"iou": {"p10": 0.01}},
        "different_track": {"iou": {"p99": 0.50}},
    }

    gaps = cal.suggest_gaps(summary)

    assert gaps["iou"]["empty"] is True
    assert gaps["iou"]["lower"] > gaps["iou"]["upper"]


def test_suggest_gaps_without_both_groups_returns_nothing():
    """Thiếu một nhóm thì không nêu khoảng — thà im còn hơn bịa."""
    assert cal.suggest_gaps({"same_track": {"iou": {"p10": 0.9}}}) == {}


def test_suggest_gaps_only_covers_similarity_metrics():
    """Chỉ ``iou`` và ``center_ratio`` có khoảng trống.

    ``frame_ratio``, ``aspect``, ``area_ratio`` là đại lượng **kích thước tuyệt
    đối**, không phải độ giống nhau. Nhóm "khác track" chứa lẫn cả cùng-người-
    bị-đổi-id (kích thước y hệt) lẫn người-khác-hẳn, nên phân bố của nó chồng
    lên nhóm cùng-track một cách tự nhiên. Nêu "khoảng trống" từ đó là bịa.
    """
    summary = {
        "same_track": {
            "iou": {"p10": 0.8},
            "center_ratio": {"p90": 0.1},
            "frame_ratio_min": {"p90": 0.3},
            "aspect": {"p90": 0.7},
            "area_ratio": {"p90": 0.2},
        },
        "different_track": {
            "iou": {"p99": 0.02},
            "center_ratio": {"p1": 0.9},
            "frame_ratio_min": {"p1": 0.25},
            "aspect": {"p1": 0.6},
            "area_ratio": {"p1": 0.1},
        },
    }

    gaps = cal.suggest_gaps(summary)

    assert set(gaps) == {"iou", "center_ratio"}, (
        "chỉ hai đại lượng đo độ giống nhau mới được nêu khoảng"
    )


# --------------------------------------------------------------------------
# main — đầu-cuối với nguồn + estimator giả
# --------------------------------------------------------------------------


class _FakeSource:
    """Nguồn ảnh giả: trả ``frames`` khung rồi ``None``."""

    backend = "fake"

    def __init__(self, count: int) -> None:
        self.left = count
        self.closed = 0

    def read(self):
        if self.left <= 0:
            return None
        self.left -= 1
        return np.zeros(FRAME_SHAPE, dtype=np.uint8)

    def close(self) -> None:
        self.closed += 1


class _FakeEstimator:
    """``PoseEstimator`` giả: trả các hộp dựng sẵn, không chạm model."""

    def __init__(self, frames_boxes) -> None:
        self._frames = list(frames_boxes)
        self._index = 0

    def _infer(self, frame):
        boxes, ids = self._frames[min(self._index, len(self._frames) - 1)]
        self._index += 1

        class _Boxes:
            def __init__(self, xyxy, track_ids):
                self.xyxy = _Tensor(xyxy)
                self.id = None if track_ids is None else _Tensor(track_ids)

            def __len__(self):
                return len(self.xyxy.array)

        class _Result:
            def __init__(self, xyxy, track_ids):
                self.boxes = _Boxes(xyxy, track_ids)

        return [_Result(boxes, ids)]


class _Tensor:
    def __init__(self, value) -> None:
        self.array = np.asarray(value, dtype=np.float32)

    def cpu(self):
        return self

    def numpy(self):
        return self.array


def _run_main(*, frames, source_frames, argv):
    out, err = io.StringIO(), io.StringIO()
    code = cal.main(
        argv,
        source_factory=lambda _text: _FakeSource(source_frames),
        estimator_factory=lambda: _FakeEstimator(frames),
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue()


def test_main_prints_two_groups_and_gap_table():
    """Đầu-cuối: in cả hai nhóm + phần gợi ý khoảng, và ghi JSON."""
    home = [[100.0, 100.0, 300.0, 400.0]]
    nudge = [[110.0, 105.0, 310.0, 405.0]]
    far = [[450.0, 50.0, 620.0, 300.0]]
    frames = [(home, [7]), (nudge, [7]), (far, [13])]

    with _Scratch("groups") as scratch:
        target = scratch / "out.json"
        code, text, _err = _run_main(
            frames=frames,
            source_frames=3,
            argv=["--frames", "3", "--out", str(target)],
        )

        assert code == 0
        assert "NHÓM 1" in text and "CÙNG track id" in text
        assert "NHÓM 2" in text and "KHÁC track id" in text
        assert "GỢI Ý NGƯỠNG" in text
        assert "REACQUIRE_MIN_IOU" in text
        assert "REACQUIRE_MAX_CENTER_SHIFT_RATIO" in text
        assert "CHỈ ĐO" in text, "phải nói rõ không áp dụng số nào"

        # Đọc JSON **trong** khối ``with``: ``_Scratch`` dọn thư mục khi ra.
        payload = json.loads(target.read_text(encoding="utf-8"))

    assert payload["frames_read"] == 3
    assert "same_track" in payload["summary"]
    assert payload["suggested_gaps"], "phải có khoảng gợi ý"
    assert "KHÔNG sửa pose.py" in payload["note"]


def test_main_does_not_modify_pose_constants():
    """Chạy xong, bốn hằng ``REACQUIRE_*`` trong ``pose.py`` phải y nguyên."""
    before = {
        name: getattr(pose_mod, name)
        for name in (
            "REACQUIRE_MIN_FRAME_RATIO",
            "REACQUIRE_MIN_IOU",
            "REACQUIRE_MAX_CENTER_SHIFT_RATIO",
            "REACQUIRE_MAX_ASPECT_RATIO",
        )
    }
    home = [[100.0, 100.0, 300.0, 400.0]]
    frames = [(home, [7]), (home, [7])]

    with _Scratch("constants") as scratch:
        code, _text, _err = _run_main(
            frames=frames,
            source_frames=2,
            argv=["--frames", "2", "--out", str(scratch / "o.json")],
        )

    assert code == 0
    for name, value in before.items():
        assert getattr(pose_mod, name) == value, f"{name} bị đổi!"


def test_main_reports_missing_weights_in_vietnamese():
    """Không nạp được model → lỗi tiếng Việt rõ ràng, không traceback."""
    out, err = io.StringIO(), io.StringIO()

    def _boom():
        raise pose_mod.PoseError("không thấy yolo11n-pose.pt")

    with _Scratch("weights") as scratch:
        code = cal.main(
            ["--frames", "5", "--out", str(scratch / "o.json")],
            source_factory=lambda _t: _FakeSource(1),
            estimator_factory=_boom,
            stdout=out,
            stderr=err,
        )

    assert code == 1
    message = err.getvalue()
    assert "LỖI" in message
    assert "không nạp được model pose" in message
    assert "yolo11n-pose.pt" in message
    assert "Traceback" not in message


def test_main_reports_unreadable_source():
    """Không mở được nguồn → lỗi tiếng Việt, mã thoát 1."""
    out, err = io.StringIO(), io.StringIO()

    with _Scratch("nosource") as scratch:
        code = cal.main(
            ["--frames", "5", "--out", str(scratch / "o.json")],
            source_factory=lambda _t: None,
            estimator_factory=lambda: _FakeEstimator(
                [([[0.0, 0.0, 10.0, 10.0]], [7])]
            ),
            stdout=out,
            stderr=err,
        )

    assert code == 1
    assert "không mở được nguồn ảnh" in err.getvalue()


def test_main_warns_when_tracking_is_off():
    """Nguồn đọc được nhưng không có track id → cảnh báo tracking đang tắt."""
    frame = ([[100.0, 100.0, 300.0, 400.0]], None)

    with _Scratch("notracking") as scratch:
        code, text, _err = _run_main(
            frames=[frame],
            source_frames=2,
            argv=["--frames", "2", "--out", str(scratch / "o.json")],
        )

    assert code == 0
    assert "CẢNH BÁO" in text
    assert "tracking" in text


def test_main_rejects_non_positive_frames():
    """``--frames 0`` bị từ chối trước khi mở camera."""
    out, err = io.StringIO(), io.StringIO()

    with _Scratch("badframes") as scratch:
        code = cal.main(
            ["--frames", "0", "--out", str(scratch / "o.json")],
            source_factory=lambda _t: _FakeSource(1),
            estimator_factory=lambda: _FakeEstimator(
                [([[0.0, 0.0, 10.0, 10.0]], [7])]
            ),
            stdout=out,
            stderr=err,
        )

    assert code == 1
    assert "--frames" in err.getvalue()


def test_help_text_is_vietnamese():
    """``--help`` có mô tả tiếng Việt và nêu cả bốn hằng."""
    text = cal.build_parser().format_help()

    assert "hộp liên tiếp" in text
    assert "REACQUIRE_MIN_IOU" in text
    assert "REACQUIRE_MAX_CENTER_SHIFT_RATIO" in text
    assert "không sửa" in text.lower()


def test_default_out_is_not_in_data_dir():
    """Mặc định không ghi vào ``data/`` — đó là chỗ lưu lịch sử thật."""
    parser = cal.build_parser()
    default_out = parser.get_default("out")

    assert "data/" not in str(default_out).replace("\\", "/")
    assert str(default_out).startswith(".scratch/")
