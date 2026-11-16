"""Khoá hành vi **bám lại track** trong ``pose.py`` (sửa lỗi mất skeleton).

Bối cảnh lỗi: khi ``tracking.enabled``, ``PoseEstimator`` bám một track id.
BotSORT đổi id khi người cúi xuống, rời nửa khung hoặc ánh sáng đổi — trong
khi người vẫn ngồi trong hình. Bản cũ giữ khoá tới hết
``timing.absent_reset_s`` (mặc định 120 s), nên ``detect()`` trả ``None`` suốt
khoảng đó: ``__main__._monitor_loop`` không gọi ``draw_pose`` (mất skeleton)
và ``PresenceTracker.update(None)`` đếm 0 keypoint, đẩy ``held["leave_frame"]``
vượt ngưỡng của ``schedule.should_alert`` → loa lặp "quay lại bàn học" mỗi
``cooldown_s`` dù người vẫn ngồi đó.

File này khoá **cả hai** chiều của bản sửa:

- khung còn người ⇒ bám lại ngay trong khung đó, ``_locked_id`` đổi sang id
  mới, ``last_person_count`` vẫn đúng;
- khung chỉ còn hộp rác quá nhỏ ⇒ **không** cướp khoá (không đổi lỗi "mất
  skeleton" thành lỗi "skeleton nhảy sang góc bàn");
- khung không còn ai ⇒ ``None`` và ``last_person_count == 0`` (vắng thật).

Cách làm giống ``tests/test_pose.py``: model giả, không cần trọng số, không
cần mạng, không ``sleep`` thật. Hai lớp giả được viết lại tại đây thay vì
import từ ``test_pose.py`` để file này tự chạy độc lập (repo không có
``tests/__init__.py`` và không test nào import test khác).
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
from posture_monitor.config import (  # noqa: E402
    Config,
    ModelConfig,
    TimingConfig,
)
from posture_monitor.pose import (  # noqa: E402
    NUM_KEYPOINTS,
    REACQUIRE_MIN_FRAME_RATIO,
    PoseEstimator,
    PoseResult,
    _box_is_big_enough,
)
from posture_monitor.presence import (  # noqa: E402
    STATE_PRESENT,
    PresenceTracker,
)

#: Khung hình tổng hợp dùng chung: 640x480 như camera thật của dự án, để ngưỡng
#: tỉ lệ khung bao có ý nghĩa (khung 8x8 của vài bài cũ làm mọi hộp đều "to").
FRAME_SHAPE = (480, 640, 3)


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


class _FakeKeypointSingle:
    def __init__(self, xy, conf) -> None:
        self.xy = [xy]
        self.conf = [conf]


class _FakeKeypoints:
    def __init__(self, xy, conf) -> None:
        self.xy = [np.asarray(item, dtype=np.float32) for item in xy]
        self.conf = [np.asarray(item, dtype=np.float32) for item in conf]

    def __getitem__(self, index):
        return _FakeKeypointSingle(self.xy[index], self.conf[index])


class _FakeResult:
    def __init__(self, boxes, keypoints) -> None:
        self.boxes = boxes
        self.keypoints = keypoints


def _result_for(boxes, ids=None, kp_conf=None):
    """Dựng ``_FakeResult`` cho ``len(boxes)`` người, toạ độ keypoint = 0."""
    count = len(boxes)
    kp_xy = [np.zeros((NUM_KEYPOINTS, 2), dtype=np.float32)] * count
    if kp_conf is None:
        kp_conf = [np.full(NUM_KEYPOINTS, 0.9, dtype=np.float32)] * count
    return _FakeResult(_FakeBoxes(boxes, ids), _FakeKeypoints(kp_xy, kp_conf))


class _FakeModel:
    """Model giả: luôn trả cùng một kết quả dựng sẵn."""

    def __init__(self, result) -> None:
        self._result = result

    def track(self, frame, **kwargs):
        return [self._result]

    def predict(self, frame, **kwargs):
        return [self._result]


def _estimator(boxes, ids=None, *, absent_reset_s: float = 120.0):
    """``PoseEstimator`` gắn model giả, không chạm ultralytics."""
    config = Config(
        model=ModelConfig(format="pt"),
        timing=TimingConfig(absent_reset_s=absent_reset_s),
    )
    # Dựng qua ``__new__`` rồi tự đặt thuộc tính: bỏ được cả ``_load()`` (chạm
    # ultralytics) lẫn ``monkeypatch`` toàn cục, nhờ vậy bài test không phụ
    # thuộc thứ tự chạy với các file test khác.
    estimator = PoseEstimator.__new__(PoseEstimator)
    estimator._model_cfg = config.model
    estimator._tracking = config.tracking
    estimator._absent_reset_s = float(config.timing.absent_reset_s)
    estimator._weights = Path("dummy.pt")
    estimator._model = _FakeModel(_result_for(boxes, ids))
    estimator._backend = "pt"
    estimator._tracking_on = bool(config.tracking.enabled)
    estimator._locked_id = None
    estimator._last_seen_ts = 0.0
    estimator._last_box = None
    estimator.last_person_count = 0
    return estimator


def _frame() -> np.ndarray:
    return np.zeros(FRAME_SHAPE, dtype=np.uint8)


class _FakeClock:
    """Đồng hồ tiêm được: thời gian chỉ chạy khi test tự đẩy."""

    def __init__(self, start: float = 100.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


# --------------------------------------------------------------------------
# (a) Track đang khoá mất, khung còn người ⇒ bám lại ngay trong khung đó
# --------------------------------------------------------------------------


def test_reacquires_new_track_id_in_same_frame():
    """Khoá 7 mất, khung chỉ còn id 9 với khung bao lớn → chọn 9 ngay."""
    estimator = _estimator([[100, 120, 400, 460]], ids=[9])
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()

    pose = estimator.detect(_frame())

    assert isinstance(pose, PoseResult)
    assert estimator._locked_id == 9
    assert estimator.last_person_count == 1
    assert np.allclose(pose.bbox, [100, 120, 400, 460])


def test_reacquire_picks_largest_person_and_keeps_true_count():
    """Bám người to nhất; ``last_person_count`` = số người thật trong khung."""
    estimator = _estimator(
        [[10, 10, 60, 90], [100, 100, 500, 470], [5, 200, 40, 260]],
        ids=[9, 10, 11],
    )
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()

    pose = estimator.detect(_frame())

    assert pose is not None
    assert estimator._locked_id == 10
    assert np.allclose(pose.bbox, [100, 100, 500, 470])
    assert estimator.last_person_count == 3


# --------------------------------------------------------------------------
# (a2) CỔNG LIÊN TỤC KHÔNG GIAN — người khác ở chỗ khác KHÔNG được cướp khoá
#
# Đây là lỗi nghiêm trọng nhất của bản bám lại đầu tiên, do vòng phản biện
# (t6) phát hiện: khi người học RỜI BÀN mà trong khung còn một người khác,
# ``_locked_id`` nhảy sang người kia và ``presence`` **không bao giờ** báo
# vắng — tức bản sửa phá đúng tính năng nó định cứu, từ chiều ngược lại.
# --------------------------------------------------------------------------

#: Hộp của người học đang ngồi, dùng làm mốc ``_last_box`` cho các bài dưới.
#: 220x360 px — cao hơn rộng, đúng dáng người ngồi cạnh bàn.
_HOME_BOX = [200.0, 100.0, 420.0, 460.0]


def _estimator_locked_with_history(boxes, ids, *, absent_reset_s: float = 120.0):
    """Như :func:`_estimator` nhưng đã có ``_last_box`` của khung trước."""
    estimator = _estimator(boxes, ids, absent_reset_s=absent_reset_s)
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()
    estimator._last_box = np.array(_HOME_BOX, dtype=np.float32)
    return estimator


def test_other_person_far_away_does_not_steal_lock():
    """Người học rời bàn, người khác ở góc khác → ``None``, khoá vẫn 7.

    Đây là bài khoá lỗi F1. Hộp mới **đủ lớn** (nên qua cổng kích thước) nhưng
    ở góc khác hẳn: IoU = 0 và tâm cách 316 px > 0,5 × 360 px. Không có cổng
    không gian thì ``_locked_id`` thành 13 và ``presence`` không bao giờ báo
    vắng — người học bỏ đi cả buổi mà hệ thống vẫn báo "có mặt".
    """
    # Người khác đứng ở góc phải trên khung, không giao với hộp người học.
    estimator = _estimator_locked_with_history([[500, 0, 640, 200]], ids=[13])

    pose = estimator.detect(_frame())

    assert pose is None, "người ở chỗ khác không được coi là người đang theo dõi"
    assert estimator._locked_id == 7, "khoá phải giữ nguyên để presence báo vắng"
    assert estimator.last_person_count == 1, "khung vẫn có 1 người"


def test_other_person_opposite_corner_does_not_steal_lock():
    """Cùng ý trên với góc đối diện — không phụ thuộc một phía cụ thể."""
    estimator = _estimator_locked_with_history([[0, 0, 180, 300]], ids=[13])

    assert estimator.detect(_frame()) is None
    assert estimator._locked_id == 7


def test_same_person_shifted_slightly_still_reacquires():
    """Cùng người, id đổi 7→9, hộp dịch nhẹ và chồng lấn → vẫn bám lại.

    Chiều ngược lại của bài trên: cổng không gian **không** được chặn oan ca
    cần cứu. Đây chính là lúc BotSORT đổi id vì người cúi xuống/xê dịch.
    """
    estimator = _estimator_locked_with_history([[210, 105, 430, 465]], ids=[9])

    pose = estimator.detect(_frame())

    assert isinstance(pose, PoseResult)
    assert estimator._locked_id == 9
    assert np.allclose(pose.bbox, [210, 105, 430, 465])


def test_same_person_contracted_box_still_reacquires():
    """Người cúi xuống làm hộp co mạnh: IoU tụt nhưng tâm gần như đứng yên.

    Đây là ca mà điều kiện "dịch tâm" cứu được trong khi IoU không đủ — lý do
    phải dùng **hoặc** chứ không phải chỉ IoU.
    """
    estimator = _estimator_locked_with_history([[220, 200, 400, 460]], ids=[9])

    assert isinstance(estimator.detect(_frame()), PoseResult)
    assert estimator._locked_id == 9


def test_last_box_is_updated_after_each_pose():
    """``_last_box`` phải theo hộp mới nhất, để khung sau còn mốc mà so."""
    estimator = _estimator_locked_with_history([[210, 105, 430, 465]], ids=[9])

    pose = estimator.detect(_frame())

    assert estimator._last_box is not None
    assert np.allclose(estimator._last_box, pose.bbox)


def test_first_frame_has_no_history_and_still_reacquires():
    """Chưa từng có hộp nào (``_last_box is None``) → không chặn oan.

    Chặn ở đây chỉ tạo lỗi giả: chưa có gì để so thì không thể nói "khác chỗ".
    """
    estimator = _estimator([[100, 120, 400, 460]], ids=[9])
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()
    estimator._last_box = None

    assert isinstance(estimator.detect(_frame()), PoseResult)
    assert estimator._locked_id == 9


def test_reacquire_does_not_wait_for_absent_reset():
    """Bám lại xảy ra ngay, không phụ thuộc ``timing.absent_reset_s``."""
    for absent_reset_s in (0.0, 120.0):
        estimator = _estimator([[100, 120, 400, 460]], ids=[9])
        estimator._absent_reset_s = absent_reset_s
        estimator._locked_id = 7
        # Vừa mới thấy track 7 ở khung trước, tức đồng hồ vắng = 0 s.
        estimator._last_seen_ts = pose_mod.time.monotonic()

        assert isinstance(estimator.detect(_frame()), PoseResult), absent_reset_s
        assert estimator._locked_id == 9, absent_reset_s


def test_after_reacquire_new_id_is_locked_against_bigger_newcomer():
    """Sau khi bám lại, id mới phải giữ được khoá như id cũ.

    Nếu không, mỗi khung người thứ hai đi ngang qua to hơn sẽ cướp khoá — đúng
    hành vi mà
    ``test_pose.test_detect_keeps_locked_track_when_other_person_bigger`` đang
    bảo vệ.
    """
    estimator = _estimator([[100, 120, 400, 460]], ids=[9])
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()
    estimator.detect(_frame())
    assert estimator._locked_id == 9

    # Khung sau: id 9 vẫn còn (hộp nhỏ hơn) và một người mới id 12 to hơn.
    estimator._model = _FakeModel(
        _result_for([[100, 120, 300, 400], [0, 0, 640, 480]], ids=[9, 12])
    )
    pose = estimator.detect(_frame())

    assert np.allclose(pose.bbox, [100, 120, 300, 400])
    assert estimator._locked_id == 9
    assert estimator.last_person_count == 2


# --------------------------------------------------------------------------
# (b) Khung không còn ai ⇒ None và last_person_count == 0
# --------------------------------------------------------------------------


def test_returns_none_when_no_person_left():
    """Vắng thật: ``None`` và ``last_person_count == 0``."""
    estimator = _estimator([], ids=None)
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()

    assert estimator.detect(_frame()) is None
    assert estimator.last_person_count == 0


def test_lock_is_kept_while_nobody_is_visible():
    """Chưa hết ``absent_reset_s`` thì khoá cũ vẫn còn (để đồng hồ chạy tiếp)."""
    estimator = _estimator([], ids=None)
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()

    estimator.detect(_frame())

    assert estimator._locked_id == 7


# --------------------------------------------------------------------------
# (c) Người quay lại ⇒ PresenceTracker thấy ngay, không chờ absent_reset_s
# --------------------------------------------------------------------------


@pytest.mark.parametrize("absent_reset_s", [0.0, 120.0])
def test_presence_recovers_on_first_frame_after_reacquire(absent_reset_s):
    """Chuỗi lỗi thật: mất track → ``pose=None`` → vắng; bám lại → hết vắng ngay.

    Đồng hồ giả đẩy 10 giây vắng (quá ``absent_hold_s`` 3 s, còn xa
    ``absent_reset_s`` 120 s). Khung đầu tiên bám lại được track mới phải làm
    ``absent_for_s`` về 0,0 và ``state == "co_mat"`` ngay — đây chính là chỗ
    bản cũ báo "quay lại bàn học" oan suốt 120 s.
    """
    clock = _FakeClock()
    tracker = PresenceTracker(absent_hold_s=3.0, clock=clock)

    # Giai đoạn mất track: bản cũ trả ``None`` ở đây nên presence đếm 0 keypoint.
    for _ in range(10):
        tracker.update(None)
        clock.advance(1.0)

    absent = tracker.update(None)
    assert absent.present is False, "sau 10 s vắng phải báo vắng"

    # BotSORT đổi id; người vẫn ngồi đó. Bản sửa phải trả pose ngay khung này.
    estimator = _estimator([[100, 120, 400, 460]], ids=[9])
    estimator._absent_reset_s = absent_reset_s
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()
    pose = estimator.detect(_frame())

    assert isinstance(pose, PoseResult)
    result = tracker.update(pose)
    assert result.absent_for_s == 0.0
    assert result.state == STATE_PRESENT
    assert result.visible is True


# --------------------------------------------------------------------------
# (d) Hộp rác quá nhỏ không được cướp khoá
# --------------------------------------------------------------------------


def test_tiny_trash_box_does_not_steal_lock():
    """Hộp rác 3x3 trên khung 640x480 không đủ lớn để bám lại.

    **Đây là CA LOẠI TRỪ của tiêu chí (a)**, không phải mã sai: tiêu chí (a)
    nói "0 khung trả ``None`` khi ``last_person_count >= 1``", nhưng khung chỉ
    còn hộp rác là trường hợp được phép trả ``None`` (và được đo riêng bằng
    đếm "khoá bị cướp" = 0). Xem docs §3(a).
    """
    estimator = _estimator([[100, 100, 103, 103]], ids=[9])
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()

    assert estimator.detect(_frame()) is None
    assert estimator._locked_id == 7, "khoá phải giữ nguyên"
    assert estimator.last_person_count == 1, "nhưng vẫn phải báo đúng số người"


def test_trash_boxes_detected_by_flatness():
    """Hộp DẸT (mép bàn, bóng đổ, thanh ghế) phải bị loại bằng **cả hai trục**.

    Đây là bài khoá lỗi F2. Bản đầu tiên dùng
    ``max(width / frame_w, height / frame_h)`` nên một mép bàn 400x4 chỉ cao
    4 px vẫn qua cổng — vì nó rộng 62 % chiều rộng khung. Cùng lỗi với bóng
    đổ 500x6 và thanh ghế 350x10. Đòi **cả hai** trục loại được cả ba, mà
    không đụng tới người ngồi thật.
    """
    frames = [
        ("mép bàn", [100, 300, 500, 304]),
        ("bóng đổ", [70, 400, 570, 406]),
        ("thanh ghế", [150, 200, 500, 210]),
    ]
    for label, box in frames:
        estimator = _estimator([box], ids=[9])
        estimator._locked_id = 7
        estimator._last_seen_ts = pose_mod.time.monotonic()

        pose = estimator.detect(_frame())

        assert pose is None, f"{label} không được bám lại"
        assert estimator._locked_id == 7, f"{label} không được cướp khoá"
        assert estimator.last_person_count == 1


def test_flat_box_is_rejected_by_size_helper():
    """``_box_is_big_enough``: hộp dẹt → ``False``, người ngồi → ``True``."""
    for box in ([100, 300, 500, 304], [70, 400, 570, 406], [150, 200, 500, 210]):
        assert (
            _box_is_big_enough(np.array(box, np.float32), FRAME_SHAPE) is False
        )

    # Người ngồi bị bàn che nửa dưới: 300x200 trên 640x480 = 47% x 42%.
    assert _box_is_big_enough(
        np.array([170, 120, 470, 320], np.float32), FRAME_SHAPE
    ) is True


def test_person_half_hidden_by_desk_is_still_accepted():
    """Người bị bàn che nửa dưới KHÔNG được chặn oan.

    Đây là ca biên quan trọng nhất của module (xem ``presence.py``): người ngồi
    thật thường có hộp thấp hơn nhiều so với hộp đứng. Đòi cả hai trục mà đặt
    ngưỡng quá cao sẽ chặn oan đúng ca phổ biến nhất.
    """
    estimator = _estimator([[170, 120, 470, 320]], ids=[9])
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()
    estimator._last_box = np.array([170.0, 120.0, 470.0, 320.0], np.float32)

    pose = estimator.detect(_frame())

    assert isinstance(pose, PoseResult)
    assert estimator._locked_id == 9


def test_box_just_above_threshold_is_accepted():
    """Mốc ngưỡng: hộp vượt ``REACQUIRE_MIN_FRAME_RATIO`` thì bám lại được.

    Bài này đọc hằng số thay vì chép lại con số, để đổi ngưỡng không phải sửa
    hai chỗ. Nó **không** khẳng định ngưỡng đã hiệu chuẩn — xem docstring của
    hằng số trong ``pose.py``.
    """
    width = int(np.ceil(REACQUIRE_MIN_FRAME_RATIO * FRAME_SHAPE[1]) * 1.5)
    height = int(np.ceil(REACQUIRE_MIN_FRAME_RATIO * FRAME_SHAPE[0]) * 1.5)
    estimator = _estimator([[100, 100, 100 + width, 100 + height]], ids=[9])
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic()

    assert isinstance(estimator.detect(_frame()), PoseResult)
    assert estimator._locked_id == 9


def test_lock_is_released_after_absent_reset_even_if_only_trash_left():
    """Đường cũ phải còn: vắng quá ``absent_reset_s`` thì nhả khoá.

    Ngưỡng bám lại chỉ chặn việc **cướp khoá**; nó không được biến thành khoá
    vĩnh viễn. Sau khi hết hạn vắng, hộp lớn nhất vẫn được chọn (dù nhỏ) đúng
    như ``test_pose.test_detect_releases_track_after_absent_reset`` yêu cầu.
    """
    estimator = _estimator([[100, 100, 103, 103]], ids=[9])
    estimator._locked_id = 7
    estimator._last_seen_ts = pose_mod.time.monotonic() - 10_000

    pose = estimator.detect(_frame())

    assert isinstance(pose, PoseResult)
    assert estimator._locked_id == 9


# --------------------------------------------------------------------------
# Hành vi cũ phải giữ nguyên: không có track id → hộp lớn nhất
# --------------------------------------------------------------------------


def test_without_ids_still_uses_largest_box():
    """Tracking tắt/backend không trả id: vẫn "khung bao lớn nhất" như cũ."""
    estimator = _estimator([[10, 10, 60, 90], [100, 100, 500, 470]], ids=None)
    estimator._locked_id = 7

    pose = estimator.detect(_frame())

    assert np.allclose(pose.bbox, [100, 100, 500, 470])
    assert estimator._locked_id is None
    assert estimator.last_person_count == 2
