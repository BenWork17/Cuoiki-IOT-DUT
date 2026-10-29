"""Cổng nhịp ``face.interval_s`` phải nhường cho phiên đăng ký khuôn mặt.

Lỗi đã đo: ``_build_face_processor`` chặn detect 2 s/lượt, trong khi cửa sổ
đăng ký chỉ dài ``len(steps) * step_s`` = 7,5 s và mỗi bước chỉ nhận **một**
mẫu. Hai lần trượt detect rơi đúng nhịp cổng là đủ làm phiên thất bại:

    kịch bản                          có cổng 2 s        bỏ cổng
    không rơi khung nào              ('done', 3, 4.0)    ('done', 3, 3.0)
    miss 1 khung @2.0                ('done', 3, 6.0)    ('done', 3, 3.0)
    miss 2 khung @2.0,4.0            ('failed', 0, 7.6)  ('done', 3, 3.0)
    miss 2 khung @4.0,6.0            ('failed', 0, 7.6)  ('done', 3, 3.0)
    miss 2 khung ngoài nhịp @2.2,4.2 ('done', 3, 4.0)    ('done', 3, 3.0)

Vì vậy file này khoá **quan sát trực tiếp**: đang đăng ký thì ``detect`` chạy
ở **mọi** khung; ngoài phiên đăng ký thì bị chặn đúng ``interval_s``. Cả hai
test dùng ``PeopleService`` và ``FaceStore`` thật, chỉ ``recognizer`` là giả
(không cần model trên PC).

Đột biến để kiểm chứng test: bỏ ``skip_gate`` khỏi ``_build_face_processor``
(ví dụ đổi ``if skip_gate is not None and skip_gate():`` thành nhánh không
bao giờ chạy) — ``test_dang_dang_ky_thi_detect_moi_khung`` phải đỏ.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import posture_monitor.__main__ as cli  # noqa: E402
from posture_monitor.faces import DetectedFace, FaceStore  # noqa: E402
from posture_monitor.people_service import OBSERVATION_SKIPPED  # noqa: E402
from posture_monitor.people_service import PeopleService  # noqa: E402


class _Clock:
    """Đồng hồ điều khiển được; cùng một giá trị cho service và processor."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _TimeShim:
    """Thay ``__main__.time`` để ``time.monotonic()`` dùng đồng hồ giả.

    ``_build_face_processor`` đọc ``time.monotonic`` từ chính module
    ``__main__``, nên tiêm ở đây không đụng gì tới ``time`` thật của pytest.
    """

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock

    def monotonic(self) -> float:
        return self._clock.now


class _CountingRecognizer:
    """Đếm lượt detect; mỗi lượt trả đúng một khuôn mặt để phiên thu được mẫu."""

    def __init__(self) -> None:
        self.detect_calls = 0
        self.embedding_calls = 0
        self.vector = np.ones(128, dtype=np.float32) / np.sqrt(128.0)

    def detect(self, _image):
        self.detect_calls += 1
        return [
            DetectedFace(
                x=10.0,
                y=10.0,
                width=40.0,
                height=40.0,
                score=0.95,
                box=np.zeros(8, dtype=np.float32),
            )
        ]

    def embedding(self, _image, _face):
        self.embedding_calls += 1
        return np.array(self.vector)


class _QuietLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, fmt, *args) -> None:
        self.warnings.append(fmt % args if args else str(fmt))

    def info(self, *_a, **_k) -> None:
        pass

    def error(self, *_a, **_k) -> None:
        pass

    def exception(self, *_a, **_k) -> None:
        pass


_FRAME = np.zeros((48, 64, 3), dtype=np.uint8)


def _build(tmp_path: Path, *, interval_s: float, clock: _Clock, monkeypatch):
    """Dựng cặp thật: ``PeopleService`` + processor của ``__main__``.

    Processor được nối đúng như ``_create_people_service`` nối
    (``skip_gate=service.is_enrolling``), nên test bắt được cả lỗi nối dây.
    """
    monkeypatch.setattr(
        "posture_monitor.__main__.time", _TimeShim(clock)
    )
    logger = _QuietLogger()
    recognizer = _CountingRecognizer()
    service = PeopleService(
        FaceStore(tmp_path, clock=clock),
        recognizer,
        clock=clock,
        step_s=1.5,
        samples_needed=3,
        threshold=None,
        logger=logger,
    )
    face = SimpleNamespace(interval_s=interval_s)
    service.set_processor(
        cli._build_face_processor(
            recognizer, face, logger, skip_gate=service.is_enrolling
        )
    )
    return service, recognizer, logger


def _run_frames(service, clock: _Clock, times) -> None:
    for moment in times:
        clock.now = moment
        service.process_frame(_FRAME, now=clock.now)


def test_dang_dang_ky_thi_detect_moi_khung(tmp_path, monkeypatch):
    """``is_enrolling()`` True → ``detect`` chạy ở **mọi** khung, cổng bị bỏ.

    Đếm lời gọi thật thay vì suy từ trạng thái phiên: với cổng 2 s và 5 khung
    cách nhau 0,2 s, bản chưa sửa chỉ detect 1 lần; bản đã sửa phải là 5.
    Đây chính là điều kiện làm phiên đăng ký sống sót qua hai lần trượt
    detect rơi đúng nhịp cổng.
    """
    clock = _Clock()
    service, recognizer, _logger = _build(
        tmp_path, interval_s=2.0, clock=clock, monkeypatch=monkeypatch
    )
    try:
        service.start_enroll("A")
        assert service.is_enrolling() is True

        # 5 khung trong 0,8 s — dưới nhịp cổng 2,0 s rất xa.
        _run_frames(service, clock, [0.0, 0.2, 0.4, 0.6, 0.8])

        assert recognizer.detect_calls == 5, (
            f"Chỉ detect {recognizer.detect_calls}/5 khung trong lúc đăng ký; "
            "cổng interval_s vẫn đang chặn phiên đăng ký."
        )
    finally:
        service.close()


def test_ngoai_phien_dang_ky_van_bi_chan_dung_interval_s(tmp_path, monkeypatch):
    """Ngoài phiên đăng ký, cổng 2 s vẫn nguyên: khung thứ 5 mới lại được detect.

    Khung ở 0,0 / 0,5 / 1,0 / 1,5 bị chặn; khung 2,0 đúng nhịp thì được chạy.
    Nếu ai "sửa" bằng cách bỏ hẳn cổng thì test này đỏ.
    """
    clock = _Clock()
    service, recognizer, _logger = _build(
        tmp_path, interval_s=2.0, clock=clock, monkeypatch=monkeypatch
    )
    try:
        assert service.is_enrolling() is False
        _run_frames(service, clock, [0.0, 0.5, 1.0, 1.5, 2.0])

        assert recognizer.detect_calls == 2, (
            f"detect {recognizer.detect_calls} lần cho các mốc 0,0/0,5/1,0/"
            "1,5/2,0 với interval_s=2.0; phải là 2 (mốc 0,0 và 2,0)."
        )
    finally:
        service.close()


def test_sau_khi_dang_ky_xong_cong_khong_bi_no_mot_luot(tmp_path, monkeypatch):
    """Nhánh bỏ cổng vẫn cập nhật nhịp: hết phiên thì cổng tính từ khung cuối.

    Không cập nhật ``state["last_at"]`` trong nhánh đăng ký thì cổng coi như
    vừa "được phép" từ rất lâu trước và cho chạy thêm một lượt ngay sau khi
    đăng ký kết thúc.
    """
    clock = _Clock()
    service, recognizer, _logger = _build(
        tmp_path, interval_s=2.0, clock=clock, monkeypatch=monkeypatch
    )
    try:
        # Bắt đầu phiên ở mốc 10,0 s: ``_expire`` tính từ ``started_at``, nên
        # nhảy từ 0 lên 10 sẽ làm phiên hết hạn trước khung đầu.
        clock.now = 10.0
        enroll_id = service.start_enroll("A")["enroll_id"]
        _run_frames(service, clock, [10.0, 10.2, 10.4])
        detect_during_enroll = recognizer.detect_calls
        assert detect_during_enroll == 3

        # Huỷ phiên: hết ``is_enrolling``. Khung kế tiếp cách khung cuối 0,2 s
        # (< 2,0 s) nên phải bị chặn, không được "trả nợ" lượt.
        assert service.cancel_enroll(enroll_id) is True
        assert service.is_enrolling() is False
        _run_frames(service, clock, [10.6])

        assert recognizer.detect_calls == detect_during_enroll, (
            "Cổng cho chạy thêm ngay sau khi đăng ký xong: nhánh bỏ cổng "
            "không cập nhật state['last_at']."
        )
    finally:
        service.close()


def test_processor_van_tra_sentinel_khi_bi_chan(monkeypatch):
    """Nhánh cổng trả ``OBSERVATION_SKIPPED``, không trả ``None``.

    ``None`` nghĩa là "đã nhìn, không thấy mặt" và sẽ xoá danh tính vừa nhận
    ra; sentinel mới là "bỏ qua lượt". Giữ hợp đồng này khi thêm ``skip_gate``.
    """
    clock = _Clock()
    monkeypatch.setattr("posture_monitor.__main__.time", _TimeShim(clock))
    recognizer = _CountingRecognizer()
    logger = _QuietLogger()
    processor = cli._build_face_processor(
        recognizer, SimpleNamespace(interval_s=2.0), logger,
        skip_gate=lambda: False,
    )

    clock.now = 0.0
    assert processor(_FRAME) is not OBSERVATION_SKIPPED  # lượt đầu luôn chạy
    clock.now = 0.5
    assert processor(_FRAME) is OBSERVATION_SKIPPED
    assert recognizer.detect_calls == 1


def test_create_people_service_noi_dung_skip_gate(monkeypatch, tmp_path):
    """``_create_people_service`` phải truyền ``skip_gate=service.is_enrolling``.

    Sửa ``_build_face_processor`` mà quên chỗ gọi thì mọi test trên vẫn xanh
    (chúng tự truyền ``skip_gate``), trong khi chương trình thật vẫn dính lỗi.
    """
    captured: dict[str, object] = {}
    real_build = cli._build_face_processor

    def spy(recognizer, face, logger, **kwargs):
        captured["processor"] = real_build(
            recognizer, face, logger, **kwargs
        )
        captured["skip_gate"] = kwargs.get("skip_gate")
        return captured["processor"]

    monkeypatch.setattr(cli, "_build_face_processor", spy)

    config = cli.load_config(_REPO_ROOT / "config.yaml")
    config.face.enabled = True
    config.face.store_path = str(tmp_path / "data" / "faces.json")

    service = cli._create_people_service(config, _QuietLogger())
    assert service is not None
    try:
        assert captured["skip_gate"] is not None, (
            "chỗ gọi không truyền skip_gate: cổng vẫn chặn phiên đăng ký"
        )
        assert captured["skip_gate"] == service.is_enrolling
        assert captured["skip_gate"]() is False
        service.start_enroll("A")
        assert captured["skip_gate"]() is True
    finally:
        service.close()
