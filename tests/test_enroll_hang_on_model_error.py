"""Phiên đăng ký khuôn mặt không được treo khi model lỗi ở **mọi** khung.

Lỗi đã đo (``PeopleService`` thật + ``_build_face_processor`` thật, đồng hồ
tiêm, 5 FPS, ``recognizer`` ném lỗi mỗi khung)::

    t=+120 s  state (đọc thẳng)  = running          <-- cổng interval_s TẮT mãi
              is_enrolling()     = True
              detect calls       = 601              (có cổng đúng phải ~60)
              warnings           = 601              (5,0/s ~ 18.000 dòng/giờ)
    sau khi gọi enroll_status   → failed, is_enrolling() False

Cơ chế: đang đăng ký thì ``skip_gate`` bỏ cổng nên processor chạy mỗi khung;
lỗi model bị nuốt **bên trong** processor và trả ``OBSERVATION_SKIPPED``;
``process_frame`` gặp sentinel thì ``return`` ngay, nên ``_collect_sample`` và
do đó ``_expire`` không bao giờ chạy. ``_expire`` còn một đường gọi nữa là
``enroll_status``, nhưng nó chỉ chạy khi có HTTP GET — tab dashboard đóng thì
không ai gọi. Phiên ``running`` vĩnh viễn ⇒ ``is_enrolling()`` vĩnh viễn True
⇒ cổng vĩnh viễn tắt, và detect + cảnh báo chạy mỗi khung không dừng.

Hướng sửa (A): nhánh sentinel vẫn tick đồng hồ phiên bằng
``_collect_sample(None, moment)`` — ``vector is None`` nên không thêm mẫu,
chỉ cập nhật ``step_index`` và chạy ``_expire``.

Đột biến để kiểm chứng: trả ``return`` ngay khi gặp
``raw is OBSERVATION_SKIPPED`` (bỏ lời gọi ``_collect_sample(None, moment)``)
— ``test_phien_dang_ky_het_han_du_khong_ai_poll`` và
``test_cong_bat_lai_sau_khi_phien_het_han`` phải đỏ.
"""

from __future__ import annotations

import logging
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

#: 5 FPS — cùng nhịp với kịch bản đã tái hiện lỗi.
_FRAME_DT = 0.2
#: 5 bước mặc định (``DEFAULT_STEPS``) x 1,5 s = 7,5 s cửa sổ đăng ký.
_STEP_S = 1.5
_SAMPLES_NEEDED = 3
_STEPS = 5
_WINDOW_S = _STEP_S * _STEPS

_FRAME = np.zeros((48, 64, 3), dtype=np.uint8)


class _Clock:
    """Đồng hồ điều khiển được; dùng chung cho service và processor."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _TimeShim:
    """Thay ``__main__.time`` để ``time.monotonic()`` dùng đồng hồ giả."""

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock

    def monotonic(self) -> float:
        return self._clock.now


class _RecordingLogger:
    """Logger đếm số bản ghi theo mức; ``info`` không làm nhiễu đếm."""

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


class _BrokenRecognizer:
    """Model hỏng: ``detect`` ném lỗi ở **mọi** khung, đếm số lượt bị gọi."""

    def __init__(self, message: str = "không mở được yunet.onnx") -> None:
        self.detect_calls = 0
        self.message = message

    def detect(self, _image):
        self.detect_calls += 1
        raise RuntimeError(self.message)

    def embedding(self, _image, _face):  # pragma: no cover - không tới được
        raise AssertionError("embedding không được gọi khi detect đã lỗi")


class _WorkingRecognizer:
    """Model bình thường: mỗi lượt trả đúng một khuôn mặt."""

    def __init__(self) -> None:
        self.detect_calls = 0

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
        return np.ones(128, dtype=np.float32) / np.sqrt(128.0)


def _build(tmp_path: Path, recognizer, *, interval_s: float, clock: _Clock,
           monkeypatch, logger=None):
    """Dựng cặp thật, nối đúng như ``_create_people_service`` nối."""
    monkeypatch.setattr("posture_monitor.__main__.time", _TimeShim(clock))
    logger = logger if logger is not None else _RecordingLogger()
    service = PeopleService(
        FaceStore(tmp_path, clock=clock),
        recognizer,
        clock=clock,
        step_s=_STEP_S,
        samples_needed=_SAMPLES_NEEDED,
        threshold=None,
        logger=logger,
    )
    service.set_processor(
        cli._build_face_processor(
            recognizer,
            SimpleNamespace(interval_s=interval_s),
            logger,
            skip_gate=service.is_enrolling,
        )
    )
    return service, logger


def _run_for(service, clock: _Clock, start: float, duration: float) -> None:
    """Chạy khung 5 FPS trong ``[start, start + duration]``."""
    moment = start
    end = start + duration
    while moment <= end + 1e-9:
        clock.now = moment
        service.process_frame(_FRAME, now=moment)
        moment = round(moment + _FRAME_DT, 6)


# ----------------------------------------------------------------------
# 1. Then chốt: không ai gọi enroll_status thì phiên vẫn phải hết hạn
# ----------------------------------------------------------------------
def test_phien_dang_ky_het_han_du_khong_ai_poll(tmp_path, monkeypatch):
    """Model lỗi mọi khung, **không** gọi ``enroll_status`` → vẫn ``failed``.

    Đọc thẳng ``_enrollments[eid]["state"]`` để chứng minh trạng thái thật
    sự đổi, không phải ``enroll_status`` tự tính lúc được hỏi.
    """
    clock = _Clock()
    recognizer = _BrokenRecognizer()
    service, _logger = _build(
        tmp_path, recognizer, interval_s=2.0, clock=clock,
        monkeypatch=monkeypatch,
    )
    try:
        enroll_id = service.start_enroll("A")["enroll_id"]
        assert service._enrollments[enroll_id]["state"] == "running"

        # Chạy quá cửa sổ 7,5 s một quãng rõ ràng.
        _run_for(service, clock, start=0.0, duration=_WINDOW_S + 1.0)

        assert service._enrollments[enroll_id]["state"] == "failed", (
            "Phiên đăng ký vẫn "
            f"{service._enrollments[enroll_id]['state']!r} ở t=+{clock.now:.1f}s "
            "dù model lỗi mọi khung: đồng hồ phiên không được tick ở nhánh "
            "OBSERVATION_SKIPPED."
        )
        assert service.is_enrolling() is False
    finally:
        service.close()


# ----------------------------------------------------------------------
# 2. Hết hạn xong thì cổng interval_s phải bật lại
# ----------------------------------------------------------------------
def test_cong_bat_lai_sau_khi_phien_het_han(tmp_path, monkeypatch):
    """10 s sau khi hết hạn, ``detect`` chỉ chạy ~5 lần (cổng 2 s), không 50."""
    clock = _Clock()
    recognizer = _BrokenRecognizer()
    service, _logger = _build(
        tmp_path, recognizer, interval_s=2.0, clock=clock,
        monkeypatch=monkeypatch,
    )
    try:
        service.start_enroll("A")
        _run_for(service, clock, start=0.0, duration=_WINDOW_S + 1.0)

        calls_before = recognizer.detect_calls
        _run_for(service, clock, start=clock.now + _FRAME_DT, duration=10.0)
        calls_after = recognizer.detect_calls - calls_before

        assert calls_after <= 8, (
            f"{calls_after} lượt detect trong 10 s (cổng 2 s ⇒ phải ~5): "
            "cổng interval_s vẫn bị tắt vì phiên chưa hết hạn."
        )
        assert calls_after >= 3, (
            f"Chỉ {calls_after} lượt detect trong 10 s: cổng bị chặn quá tay."
        )
    finally:
        service.close()


# ----------------------------------------------------------------------
# 3. Log không ngập
# ----------------------------------------------------------------------
def test_log_khong_ngap_khi_model_loi_moi_khung(tmp_path, monkeypatch):
    """60 s model lỗi liên tục, không poll: WARNING ≤ 5, không hàng trăm."""
    clock = _Clock()
    recognizer = _BrokenRecognizer()
    logger = _RecordingLogger()
    service, _logger = _build(
        tmp_path, recognizer, interval_s=2.0, clock=clock,
        monkeypatch=monkeypatch, logger=logger,
    )
    try:
        service.start_enroll("A")
        _run_for(service, clock, start=0.0, duration=60.0)

        # 60 s ở 5 FPS = 301 khung bị xử lý; trước khi sửa là 301 dòng.
        assert len(logger.warnings) <= 5, (
            f"{len(logger.warnings)} bản ghi WARNING trong 60 s "
            f"(~{recognizer.detect_calls} lượt detect): log đã ngập."
        )
        # Vẫn phải có ít nhất một dòng báo lỗi — im lặng mới là lỗi khác.
        assert any("Không nhận diện được khuôn mặt" in w for w in logger.warnings)
    finally:
        service.close()


# ----------------------------------------------------------------------
# 4. Hồi quy: sentinel KHÔNG xoá danh tính cũ
# ----------------------------------------------------------------------
def test_sentinel_khong_xoa_danh_tinh_cu(tmp_path, monkeypatch):
    """Một khung bị skip không được biến identity thành UNKNOWN."""
    clock = _Clock()
    recognizer = _BrokenRecognizer()
    service, _logger = _build(
        tmp_path, recognizer, interval_s=2.0, clock=clock,
        monkeypatch=monkeypatch,
    )
    try:
        # Gieo một danh tính "MATCH" bằng tay, đúng thứ mà sentinel phải giữ.
        with service._lock:
            service._identity = {
                "state": "MATCH",
                "name": "A",
                "reason": "giống A",
                "updated_at": clock.now,
            }

        clock.now = 0.0
        service.process_frame(_FRAME, now=0.0)

        assert service.signals()["identity"]["state"] == "MATCH", (
            "OBSERVATION_SKIPPED bị hiểu thành 'không có mặt' và ghi đè "
            "danh tính cũ thành UNKNOWN."
        )
        assert service.signals()["identity"]["name"] == "A"
    finally:
        service.close()


# ----------------------------------------------------------------------
# 5. Ngoài phiên đăng ký, lỗi vẫn bị cổng chặn
# ----------------------------------------------------------------------
def test_loi_ngoai_phien_van_bi_cong_chan(tmp_path, monkeypatch):
    """Không đăng ký: 5 khung trong 0,8 s với cổng 2 s ⇒ đúng 1 lượt detect."""
    clock = _Clock()
    recognizer = _BrokenRecognizer()
    service, _logger = _build(
        tmp_path, recognizer, interval_s=2.0, clock=clock,
        monkeypatch=monkeypatch,
    )
    try:
        assert service.is_enrolling() is False
        _run_for(service, clock, start=0.0, duration=0.8)

        assert recognizer.detect_calls == 1, (
            f"{recognizer.detect_calls} lượt detect cho 0,0–0,8 s với "
            "interval_s=2,0; phải là 1."
        )
    finally:
        service.close()


# ----------------------------------------------------------------------
# 6. Đăng ký bình thường vẫn ``done``
# ----------------------------------------------------------------------
def test_dang_ky_binh_thuong_van_done(tmp_path, monkeypatch):
    """Model tốt: phiên vẫn thu đủ 3 mẫu và ``done`` như trước khi sửa."""
    clock = _Clock()
    recognizer = _WorkingRecognizer()
    service, _logger = _build(
        tmp_path, recognizer, interval_s=2.0, clock=clock,
        monkeypatch=monkeypatch,
    )
    try:
        enroll_id = service.start_enroll("A")["enroll_id"]
        _run_for(service, clock, start=0.0, duration=_WINDOW_S - 0.5)

        record = service._enrollments[enroll_id]
        assert record["state"] == "done", (
            f"Phiên bình thường kết thúc ở {record['state']!r} thay vì 'done'."
        )
        assert len(record["samples"]) == _SAMPLES_NEEDED
        assert service.is_enrolling() is False
    finally:
        service.close()


# ----------------------------------------------------------------------
# 7. ``_collect_sample(None, ...)`` không ghi mẫu (kiểm tra trực tiếp)
# ----------------------------------------------------------------------
def test_collect_sample_none_khong_them_mau(tmp_path):
    """Đường chỉ-kiểm-hạn không được vô tình đếm ``None`` thành một mẫu."""
    clock = _Clock()
    service = PeopleService(
        FaceStore(tmp_path, clock=clock),
        _WorkingRecognizer(),
        clock=clock,
        step_s=_STEP_S,
        samples_needed=_SAMPLES_NEEDED,
        threshold=None,
        logger=_RecordingLogger(),
    )
    try:
        enroll_id = service.start_enroll("A")["enroll_id"]
        record = service._enrollments[enroll_id]
        for moment in (0.0, 0.2, 1.6):
            clock.now = moment
            with service._lock:
                service._collect_sample(None, moment)

        assert record["samples"] == []
        assert record["state"] == "running"
        assert record["step_index"] == 1
    finally:
        service.close()


# ----------------------------------------------------------------------
# 8. Processor: cảnh báo chỉ ghi khi thông điệp lỗi đổi
# ----------------------------------------------------------------------
def test_processor_chi_log_khi_loi_doi(monkeypatch):
    """3 lượt lỗi cùng thông điệp → 1 warning; đổi thông điệp → thêm 1."""
    clock = _Clock()
    monkeypatch.setattr("posture_monitor.__main__.time", _TimeShim(clock))
    logger = _RecordingLogger()
    recognizer = _BrokenRecognizer("lỗi A")
    processor = cli._build_face_processor(
        recognizer, SimpleNamespace(interval_s=1.0), logger, skip_gate=None
    )

    # Cổng 1 s: mỗi lượt lùi đồng hồ đúng 1 s để lượt nào cũng chạy detect.
    clock.now = 0.0
    for _ in range(3):
        assert processor(_FRAME) is OBSERVATION_SKIPPED
        clock.now += 1.0
    assert recognizer.detect_calls == 3
    assert len(logger.warnings) == 1

    recognizer.message = "lỗi B"
    assert processor(_FRAME) is OBSERVATION_SKIPPED
    assert len(logger.warnings) == 2
    assert "lỗi B" in logger.warnings[-1]
