"""Kiểm thử ``pose.py`` (spec v2 §5.2).

Test chạy trên PC, **không cần mạng**: hầu hết dùng backend giả. Bài tích hợp
cuối file cần trọng số thật và tự bỏ qua khi máy không có file — hợp đồng
``detect()`` vẫn được kiểm bằng dữ liệu tổng hợp.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import pose as pose_mod  # noqa: E402
from posture_monitor.config import Config, ModelConfig  # noqa: E402
from posture_monitor.pose import (  # noqa: E402
    NUM_KEYPOINTS,
    PoseError,
    PoseEstimator,
    PoseResult,
)


# --------------------------------------------------------------------------
# Đối tượng giả mô phỏng output của ultralytics
# --------------------------------------------------------------------------


class _FakeTensor:
    """Bọc numpy mô phỏng ``torch.Tensor`` có ``.cpu().numpy()``."""

    def __init__(self, array) -> None:
        self._array = np.asarray(array, dtype=np.float32)

    def cpu(self):
        return self

    def numpy(self):
        return self._array


class _FakeBoxes:
    def __init__(self, xyxy, ids=None) -> None:
        self.xyxy = _FakeTensor(xyxy)
        self.id = None if ids is None else _FakeTensor(ids)

    def __len__(self) -> int:
        return len(self.xyxy._array)


class _FakeKeypoints:
    def __init__(self, xy, conf) -> None:
        self.xy = [np.asarray(item, dtype=np.float32) for item in xy]
        self.conf = [np.asarray(item, dtype=np.float32) for item in conf]

    def __getitem__(self, index):
        return _FakeKeypointSingle(self.xy[index], self.conf[index])


class _FakeKeypointSingle:
    def __init__(self, xy, conf) -> None:
        self.xy = [xy]
        self.conf = [conf]


class _FakeResult:
    def __init__(self, boxes, keypoints) -> None:
        self.boxes = boxes
        self.keypoints = keypoints


def _result_for(boxes, ids=None, kp_xy=None, kp_conf=None):
    """Dựng một ``_FakeResult`` cho ``len(boxes)`` người."""
    count = len(boxes)
    if kp_xy is None:
        kp_xy = [np.zeros((NUM_KEYPOINTS, 2), dtype=np.float32)] * count
    if kp_conf is None:
        kp_conf = [np.full(NUM_KEYPOINTS, 0.9, dtype=np.float32)] * count
    return _FakeResult(_FakeBoxes(boxes, ids), _FakeKeypoints(kp_xy, kp_conf))


class _FakeModel:
    """Model giả: trả kết quả dựng sẵn, ghi lại cách được gọi."""

    def __init__(self, results, fail_track: bool = False) -> None:
        self._results = results
        self.fail_track = fail_track
        self.track_calls = 0
        self.predict_calls = 0

    def track(self, frame, **kwargs):
        self.track_calls += 1
        if self.fail_track:
            raise RuntimeError("tracker không dùng được")
        return self._results

    def predict(self, frame, **kwargs):
        self.predict_calls += 1
        return self._results


def _estimator(monkeypatch, model, weights="dummy.pt", **config_overrides):
    """Tạo PoseEstimator đã gắn model giả, không chạm ultralytics."""

    class _FakeYOLO:
        def __init__(self, source):
            self.source = source

        def export(self, **kwargs):  # pragma: no cover - nhánh export
            return "exported"

        def __call__(self, *args, **kwargs):  # pragma: no cover
            return model

    monkeypatch.setattr(
        PoseEstimator, "_yolo", staticmethod(lambda: _FakeYOLO)
    )
    monkeypatch.setattr(
        PoseEstimator, "_load_pt", lambda self: _set_model(self, model)
    )
    monkeypatch.setattr(
        PoseEstimator, "_load_onnx", lambda self: False
    )
    monkeypatch.setattr(
        PoseEstimator, "_load_ncnn", lambda self: False
    )
    config = Config(model=ModelConfig(format="pt"), **config_overrides)
    estimator = PoseEstimator(config, weights=weights)
    estimator._model = model
    estimator._backend = "pt"
    return estimator


def _set_model(estimator, model) -> bool:
    estimator._model = model
    estimator._backend = "pt"
    return True


# --------------------------------------------------------------------------
# Hợp đồng detect()
# --------------------------------------------------------------------------


def test_detect_returns_contract_shapes(monkeypatch):
    """``detect()`` trả ``xy`` (17,2), ``conf`` (17) và ``bbox`` (4,)."""
    xy = [
        np.arange(34, dtype=np.float32).reshape(NUM_KEYPOINTS, 2),
        np.zeros((NUM_KEYPOINTS, 2), dtype=np.float32),
    ]
    model = _FakeModel([_result_for([[0, 0, 10, 10], [5, 5, 50, 50]], kp_xy=xy)])
    estimator = _estimator(monkeypatch, model)

    pose = estimator.detect(np.zeros((48, 64, 3), dtype=np.uint8))

    assert isinstance(pose, PoseResult)
    assert pose.xy.shape == (NUM_KEYPOINTS, 2)
    assert pose.conf.shape == (NUM_KEYPOINTS,)
    assert pose.bbox.shape == (4,)
    assert pose.xy.dtype == np.float32
    assert pose.conf.dtype == np.float32


def test_detect_returns_none_when_no_person(monkeypatch):
    """Không có người → ``None`` và ``last_person_count == 0``."""
    model = _FakeModel([_result_for([])])
    estimator = _estimator(monkeypatch, model)

    assert estimator.detect(np.zeros((48, 64, 3), dtype=np.uint8)) is None
    assert estimator.last_person_count == 0


def test_detect_reports_person_count(monkeypatch):
    """``last_person_count`` phản ánh số người thấy, không chỉ người được chọn."""
    boxes = [[0, 0, 10, 10], [20, 20, 60, 60], [5, 5, 40, 40]]
    model = _FakeModel([_result_for(boxes)])
    estimator = _estimator(monkeypatch, model)

    estimator.detect(np.zeros((48, 64, 3), dtype=np.uint8))
    assert estimator.last_person_count == 3


def test_detect_selects_largest_box_initially(monkeypatch):
    """Chưa khoá ai thì chọn khung bao lớn nhất (spec §5.6)."""
    boxes = [[0, 0, 10, 10], [20, 20, 60, 60]]
    kp_xy = [
        np.full((NUM_KEYPOINTS, 2), 1.0, dtype=np.float32),
        np.full((NUM_KEYPOINTS, 2), 2.0, dtype=np.float32),
    ]
    model = _FakeModel([_result_for(boxes, kp_xy=kp_xy)])
    estimator = _estimator(monkeypatch, model)

    pose = estimator.detect(np.zeros((48, 64, 3), dtype=np.uint8))
    # Người thứ hai có diện tích 40x40 > 10x10.
    assert np.allclose(pose.bbox, [20, 20, 60, 60])


def test_detect_keeps_locked_track_when_other_person_bigger(monkeypatch):
    """Đã khoá track 7 thì người mới to hơn không cướp được (spec §5.6)."""
    estimator = _estimator(monkeypatch, _FakeModel([]))

    first = _result_for(
        [[0, 0, 100, 100], [0, 0, 10, 10]],
        ids=[7, 8],
        kp_xy=[
            np.full((NUM_KEYPOINTS, 2), 5.0, dtype=np.float32),
            np.full((NUM_KEYPOINTS, 2), 50.0, dtype=np.float32),
        ],
    )
    second = _result_for(
        [[0, 0, 10, 10], [0, 0, 200, 200]],
        ids=[7, 9],
        kp_xy=[
            np.full((NUM_KEYPOINTS, 2), 6.0, dtype=np.float32),
            np.full((NUM_KEYPOINTS, 2), 70.0, dtype=np.float32),
        ],
    )

    estimator._model = _FakeModel([first])
    pose_first = estimator.detect(np.zeros((8, 8, 3), dtype=np.uint8))
    assert np.allclose(pose_first.bbox, [0, 0, 100, 100])

    estimator._model = _FakeModel([second])
    pose_second = estimator.detect(np.zeros((8, 8, 3), dtype=np.uint8))
    # Track 7 vẫn còn: phải bám người nhỏ 10x10, không nhảy sang 200x200.
    assert np.allclose(pose_second.bbox, [0, 0, 10, 10])


def test_detect_returns_none_while_track_temporarily_absent(monkeypatch):
    """Track đang bám vắng tạm thời → ``None``, không nhảy sang người khác."""
    estimator = _estimator(monkeypatch, _FakeModel([]))
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()
    estimator._model = _FakeModel(
        [_result_for([[0, 0, 200, 200]], ids=[9])]
    )

    assert estimator.detect(np.zeros((8, 8, 3), dtype=np.uint8)) is None


def test_detect_releases_track_after_absent_reset(monkeypatch):
    """Vắng quá ``absent_reset_s`` thì nhả khoá và chọn người mới."""
    estimator = _estimator(monkeypatch, _FakeModel([]))
    estimator._locked_id = 7
    # Giả lập đã vắng lâu hơn absent_reset_s (mặc định 120 giây).
    estimator._last_seen_ts = pose_mod.time.monotonic() - 10_000
    estimator._model = _FakeModel(
        [_result_for([[0, 0, 200, 200]], ids=[9])]
    )

    pose = estimator.detect(np.zeros((8, 8, 3), dtype=np.uint8))
    assert pose is not None
    assert estimator._locked_id == 9


def test_tracking_failure_falls_back_to_predict(monkeypatch):
    """Tracker lỗi → chuyển sang ``predict`` và ghi cảnh báo, không crash."""
    model = _FakeModel([_result_for([[0, 0, 10, 10]])], fail_track=True)
    estimator = _estimator(monkeypatch, model)

    pose = estimator.detect(np.zeros((8, 8, 3), dtype=np.uint8))
    assert pose is not None
    assert model.predict_calls == 1
    assert estimator._tracking_on is False


# --------------------------------------------------------------------------
# Nạp model / rơi cấp backend
# --------------------------------------------------------------------------


def test_load_falls_back_through_backends(monkeypatch):
    """Nếu mọi backend lỗi thì ném ``PoseError`` với thông điệp rõ ràng."""
    monkeypatch.setattr(PoseEstimator, "_yolo", staticmethod(lambda: object))
    monkeypatch.setattr(PoseEstimator, "_load_ncnn", lambda self: False)
    monkeypatch.setattr(PoseEstimator, "_load_onnx", lambda self: False)
    monkeypatch.setattr(PoseEstimator, "_load_pt", lambda self: False)

    with pytest.raises(PoseError) as excinfo:
        PoseEstimator(Config(model=ModelConfig(format="ncnn")), weights="x.pt")
    assert "NCNN" in str(excinfo.value)


def test_export_failure_does_not_raise(monkeypatch):
    """Export lỗi phải trả ``False`` chứ không ném (spec §11.4)."""
    estimator = _estimator(monkeypatch, _FakeModel([]))

    class _Boom:
        def __init__(self, source):
            pass

        def export(self, **kwargs):
            raise RuntimeError("pnnx không cài được")

    monkeypatch.setattr(PoseEstimator, "_yolo", staticmethod(lambda: _Boom))
    assert estimator._export("ncnn", Path("khong_ton_tai_dir")) is False


def test_ncnn_directory_naming():
    """Tên thư mục NCNN theo quy ước ultralytics: ``<stem>_ncnn_model``."""
    config = Config(model=ModelConfig(name="yolo11n-pose"))
    estimator = PoseEstimator.__new__(PoseEstimator)
    estimator._weights = Path("yolo11n-pose.pt")
    assert estimator._ncnn_dir() == Path("yolo11n-pose_ncnn_model")
    assert estimator._onnx_path() == Path("yolo11n-pose.onnx")


# --------------------------------------------------------------------------
# Tích hợp: cần trọng số thật (bỏ qua nếu không có)
# --------------------------------------------------------------------------

_PC_WEIGHTS = Path(
    r"C:\Users\ACER\AppData\Local\Temp\pcbench\yolo11n-pose.pt"
)
_PC_BUS = Path(
    r"C:\Users\ACER\AppData\Local\Temp\pcbench\assets\bus.jpg"
)


def test_bus_image_has_three_persons():
    """Mốc đối chiếu: ``bus.jpg`` ở imgsz 320 phải ra đúng 3 người."""
    if not _PC_WEIGHTS.is_file() or not _PC_BUS.is_file():
        pytest.skip("Không có trọng số/ảnh mẫu trên máy này.")
    import cv2

    config = Config(model=ModelConfig(format="pt", imgsz=320))
    estimator = PoseEstimator(config, weights=_PC_WEIGHTS)
    frame = cv2.imread(str(_PC_BUS))
    assert frame is not None

    pose = estimator.detect(frame)
    assert estimator.last_person_count == 3
    assert pose is not None
    assert pose.xy.shape == (NUM_KEYPOINTS, 2)
