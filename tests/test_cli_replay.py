"""Kiểm thử lệnh ``replay`` của CLI (spec v2 §7, §9).

Nguyên tắc: **không cần camera, GPIO, mạng hay tải trọng số**. Video đầu vào
là file MJPG nhỏ do ``cv2.VideoWriter`` sinh ra trong ``tmp_path`` (cùng cách
``test_capture.py`` làm); ``PoseEstimator`` được thay bằng đối tượng giả trả
pose tổng hợp. Metadata FPS được thay bằng probe giả để trục thời gian của
báo cáo tất định, không phụ thuộc codec của máy chạy test.

Trọng tâm kiểm thử:

- báo cáo JSON đúng schema, tất định, không lộ đường dẫn tuyệt đối/tên máy;
- thời gian của máy trạng thái bám **trục thời gian video**, không phải đồng
  hồ thực (nếu sai, hold ``bad_hold_s`` không bao giờ đủ trong test nhanh);
- thiếu ``calibration.json`` thì chạy tiếp không baseline, không được fail;
- video không mở được thì mã thoát 2, thông điệp tiếng Việt, không traceback.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import __main__ as cli  # noqa: E402
from posture_monitor import calibration  # noqa: E402
from posture_monitor.calibration import Baseline  # noqa: E402
from posture_monitor.config import (  # noqa: E402
    CAMERA_SOURCE_ENV,
    Config,
    load_config,
    redact_camera_source,
)
from posture_monitor.features import ALL_NAMES  # noqa: E402
from posture_monitor.pose import PoseResult  # noqa: E402

# --------------------------------------------------------------------------
# Đối tượng giả
# --------------------------------------------------------------------------


def _good_pose() -> PoseResult:
    """Pose tổng hợp: hai vai ngang nhau, đủ để ``features`` tính được."""
    xy = np.zeros((17, 2), dtype=np.float32)
    xy[5] = (200.0, 200.0)  # vai trái
    xy[6] = (400.0, 200.0)  # vai phải
    xy[0] = (300.0, 120.0)  # mũi
    xy[3] = (260.0, 110.0)  # tai trái
    xy[4] = (340.0, 110.0)  # tai phải
    xy[11] = (220.0, 330.0)
    xy[12] = (380.0, 330.0)
    conf = np.full((17,), 0.9, dtype=np.float32)
    bbox = np.array([200.0, 100.0, 400.0, 400.0], dtype=np.float32)
    return PoseResult(xy=xy, conf=conf, bbox=bbox)


def _tilted_pose() -> PoseResult:
    """Vai nghiêng ~26,6°: vượt ngưỡng ``shoulder_tilt_deg`` mặc định (8°)."""
    pose = _good_pose()
    xy = pose.xy.copy()
    xy[6] = (400.0, 300.0)
    return PoseResult(xy=xy, conf=pose.conf, bbox=pose.bbox)


class FakeEstimator:
    """Thay ``PoseEstimator``: không tải model, trả pose cố định."""

    backend = "giả-lập"

    def __init__(self, result: PoseResult | None) -> None:
        self._result = result
        self.calls = 0
        self.last_person_count = 0

    def detect(self, frame):  # noqa: ANN001, ANN201 - khớp hợp đồng
        self.calls += 1
        self.last_person_count = 0 if self._result is None else 1
        return self._result


class FakeCap:
    """``cv2.VideoCapture`` giả chỉ để đọc metadata FPS."""

    def __init__(self, fps: float, opened: bool = True) -> None:
        self._fps = fps
        self._opened = opened
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802 - theo API OpenCV
        return self._opened

    def get(self, prop: int) -> float:  # noqa: ANN001
        return self._fps

    def release(self) -> None:
        self.released = True


class FakeCV2:
    """Proxy cho ``cv2`` trong ``__main__``: chỉ phục vụ probe FPS.

    ``__main__`` chỉ dùng ``cv2.VideoCapture`` trong ``cmd_replay``, nên thay
    cả tên module ở đó là đủ và **không** ảnh hưởng ``FileSource`` (dùng tham
    chiếu ``cv2`` của module ``capture``).
    """

    #: Giá trị thật của OpenCV là 5; giá trị ở đây chỉ cần duy nhất.
    CAP_PROP_FPS = 5

    def __init__(self, cap: FakeCap) -> None:
        self._cap = cap

    def VideoCapture(self, path):  # noqa: ANN001, N802
        return self._cap


# --------------------------------------------------------------------------
# Tiện ích
# --------------------------------------------------------------------------


def _make_video(
    path: Path, frames: int = 20, size: tuple[int, int] = (64, 48)
) -> Path:
    """Ghi video MJPG nhỏ; bỏ qua test nếu máy không ghi được codec."""
    width, height = size
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10.0,
        (width, height),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV không ghi được MJPG trên máy này.")
    try:
        for index in range(frames):
            frame = np.full((height, width, 3), index % 255, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()
    return path


def _patch_estimator(monkeypatch, result) -> FakeEstimator:  # noqa: ANN001
    """Thay ``PoseEstimator`` trong module ``pose`` bằng đối tượng giả."""
    from posture_monitor import pose as pose_mod

    estimator = FakeEstimator(result)
    monkeypatch.setattr(pose_mod, "PoseEstimator", lambda config: estimator)
    return estimator


def _patch_probe(monkeypatch, fps: float = 10.0, opened: bool = True) -> None:
    cap = FakeCap(fps=fps, opened=opened)
    monkeypatch.setattr(cli, "cv2", FakeCV2(cap))


def _isolate_cwd(monkeypatch, tmp_path: Path) -> None:
    """Chạy trong thư mục trống: không có ``calibration.json`` lẫn config."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)


def _run_replay(video: Path, report: Path | None = None) -> int:
    # ``config.yaml`` của repo, truyền tường minh: test chạy trong thư mục tạm
    # trống để không vô tình nhặt ``calibration.json`` của người dùng.
    argv = ["replay", str(video), "--config", str(_REPO_ROOT / "config.yaml")]
    if report is not None:
        argv += ["--save-report", str(report)]
    return cli.main(argv)


def _write_baseline(path: Path, *, tilt: float = 0.0) -> None:
    values: dict[str, float | None] = {name: None for name in ALL_NAMES}
    values["shoulder_width"] = 200.0
    values["shoulder_mid_x"] = 300.0
    values["shoulder_tilt_deg"] = tilt
    values["head_height"] = 0.4
    calibration.save(
        Baseline(
            values=values,
            view="front",
            width=640,
            height=480,
            created_at="2026-01-01T00:00:00+00:00",
            frames=30,
        ),
        path,
    )


def _report_keys() -> set[str]:
    return {
        "version",
        "command",
        "video",
        "view",
        "backend",
        "video_fps",
        "fps_source",
        "calibration",
        "summary",
        "frames",
    }


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


class TestParser:
    def test_replay_nhan_video_va_co(self) -> None:
        args = cli.build_parser().parse_args(
            ["replay", "a.mp4", "--no-gpio", "--save-report", "out.json"]
        )
        assert args.command == "replay"
        assert args.video == "a.mp4"
        assert args.no_gpio is True
        assert args.save_report == "out.json"

    def test_mac_dinh_khong_luu_bao_cao(self) -> None:
        args = cli.build_parser().parse_args(["replay", "a.mp4"])
        assert args.save_report is None
        assert args.no_gpio is False


# --------------------------------------------------------------------------
# Đường thành công — schema và tính tất định
# --------------------------------------------------------------------------


class TestBaoCao:
    def test_ghi_json_dung_schema_va_dem_dung(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        estimator = _patch_estimator(monkeypatch, _good_pose())
        video = _make_video(tmp_path / "v.avi", frames=12)
        report_path = tmp_path / "out.json"

        code = _run_replay(video, report_path)

        assert code == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert set(report) == _report_keys()
        assert report["version"] == 1
        assert report["command"] == "replay"
        assert report["backend"] == "giả-lập"
        assert report["view"] == "front"
        assert report["video_fps"] == 10.0
        assert report["fps_source"] == "container"

        summary = report["summary"]
        frames = report["frames"]
        assert summary["frames"] == len(frames) == estimator.calls
        assert summary["frames_with_person"] == len(frames)
        assert summary["frames_errored"] == 0
        assert isinstance(summary["duration_s"], float)
        assert summary["duration_s"] >= 0.0
        assert sum(summary["states"].values()) == len(frames)
        assert summary["states"]["ABSENT"] == 0
        assert summary["labels"]["GOOD"] == len(frames)
        assert summary["labels"]["ABSENT"] == 0

        for index, row in enumerate(frames):
            assert set(row) == {
                "frame",
                "timestamp_s",
                "person",
                "labels",
                "score",
                "state",
            }
            assert row["frame"] == index
            assert row["person"] is True
            assert row["score"] == 100.0
            assert row["state"] == "GOOD"

    def test_timestamp_bam_truc_thoi_gian_video(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _good_pose())
        video = _make_video(tmp_path / "v.avi", frames=12)
        report_path = tmp_path / "out.json"

        assert _run_replay(video, report_path) == 0
        frames = json.loads(report_path.read_text(encoding="utf-8"))["frames"]

        # fps=10 → mỗi khung cách nhau 0,1 giây, bất kể máy chạy nhanh cỡ nào.
        for row in frames:
            assert row["timestamp_s"] == pytest.approx(row["frame"] / 10.0)

    def test_bao_cao_tat_dinh_giua_hai_lan_chay(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _good_pose())
        video = _make_video(tmp_path / "v.avi", frames=10)
        first = tmp_path / "a.json"
        second = tmp_path / "b.json"

        assert _run_replay(video, first) == 0
        assert _run_replay(video, second) == 0

        one = json.loads(first.read_text(encoding="utf-8"))
        two = json.loads(second.read_text(encoding="utf-8"))
        # Chỉ thời lượng chạy thật được phép khác; mọi thứ khác phải trùng.
        one["summary"].pop("duration_s")
        two["summary"].pop("duration_s")
        assert one == two

    def test_khong_lo_duong_dan_tuyet_doi_hay_ten_may(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _good_pose())
        video = _make_video(tmp_path / "v.avi", frames=6)
        report_path = tmp_path / "out.json"

        assert _run_replay(video, report_path) == 0
        text = report_path.read_text(encoding="utf-8")

        assert str(tmp_path) not in text
        assert str(video.resolve()) not in text
        assert socket.gethostname() not in text
        report = json.loads(text)
        assert report["video"] == "v.avi"

    def test_khong_co_nguoi_thi_la_absent_khong_phai_loi(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, None)
        video = _make_video(tmp_path / "v.avi", frames=5)
        report_path = tmp_path / "out.json"

        assert _run_replay(video, report_path) == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert report["summary"]["frames_with_person"] == 0
        assert report["summary"]["states"]["ABSENT"] == report["summary"]["frames"]
        assert report["summary"]["labels"]["ABSENT"] == report["summary"]["frames"]
        assert all(row["person"] is False for row in report["frames"])

    def test_khong_co_save_report_thi_in_tom_tat(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _good_pose())
        video = _make_video(tmp_path / "v.avi", frames=5)

        assert _run_replay(video) == 0

        out = capsys.readouterr().out
        assert "REPLAY" in out
        assert "Khung đã xử lý" in out
        assert "GOOD=" in out
        # Không được nhắc tới file báo cáo khi không được yêu cầu.
        assert "Báo cáo" not in out


# --------------------------------------------------------------------------
# Hiệu chỉnh
# --------------------------------------------------------------------------


class TestHieuChinh:
    def test_thieu_calibration_thi_chay_tiep_va_ghi_ro(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _good_pose())
        video = _make_video(tmp_path / "v.avi", frames=5)
        report_path = tmp_path / "out.json"

        assert _run_replay(video, report_path) == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert report["calibration"]["loaded"] is False
        assert "baseline" in report["calibration"]["note"]
        # Không baseline thì không thể kết luận TOO_CLOSE/LEAN...
        assert report["summary"]["labels"]["TOO_CLOSE"] == 0

    def test_co_calibration_thi_nap_baseline_va_danh_gia_nhan(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _tilted_pose())
        _write_baseline(Path("calibration.json"), tilt=0.0)
        video = _make_video(tmp_path / "v.avi", frames=5)
        report_path = tmp_path / "out.json"

        assert _run_replay(video, report_path) == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert report["calibration"]["loaded"] is True
        assert report["summary"]["labels"]["SHOULDER_TILT"] == report["summary"]["frames"]

    def test_calibration_hong_thi_chay_tiep_khong_baseline(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _good_pose())
        Path("calibration.json").write_text("{ hỏng", encoding="utf-8")
        video = _make_video(tmp_path / "v.avi", frames=4)
        report_path = tmp_path / "out.json"

        assert _run_replay(video, report_path) == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["calibration"]["loaded"] is False
        assert "hỏng" in report["calibration"]["note"]


# --------------------------------------------------------------------------
# Máy trạng thái dùng thời gian video, không phải đồng hồ thực
# --------------------------------------------------------------------------


class TestTrucThoiGian:
    def test_bad_hold_duoc_tinh_theo_giay_video(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """100 khung @10 fps = 10 giây video, chạy thật chỉ vài mili giây.

        Nếu máy trạng thái nhận ``time.monotonic()`` thì ``bad_hold_s=5``
        không bao giờ đủ và không khung nào lên BAD — test này bắt lỗi đó.
        """
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _tilted_pose())
        _write_baseline(Path("calibration.json"), tilt=0.0)
        video = _make_video(tmp_path / "v.avi", frames=100)
        report_path = tmp_path / "out.json"

        assert _run_replay(video, report_path) == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        frames = report["frames"]
        hold = Config().timing.bad_hold_s

        assert report["summary"]["states"]["BAD"] > 0
        first_bad = next(row for row in frames if row["state"] == "BAD")
        assert first_bad["timestamp_s"] >= hold
        assert first_bad["timestamp_s"] == pytest.approx(hold)
        # Trước khi đủ hold chỉ được ở WARN, chưa được BAD.
        assert all(row["state"] == "WARN" for row in frames[: first_bad["frame"]])


# --------------------------------------------------------------------------
# Đường lỗi và phần cứng
# --------------------------------------------------------------------------


class TestDuongLoi:
    def test_video_khong_mo_duoc_thi_ma_2_va_bao_tieng_viet(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_estimator(monkeypatch, _good_pose())

        code = _run_replay(tmp_path / "khong_ton_tai.mp4")

        assert code == 2
        err = capsys.readouterr().err
        assert "Không mở được video" in err
        assert "Traceback" not in err

    def test_video_rong_thi_ma_1_va_bao_ro(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _good_pose())

        class EmptySource:
            backend = "file"

            def read(self):  # noqa: ANN201
                return None

            def close(self) -> None:
                pass

        from posture_monitor import capture as capture_mod

        monkeypatch.setattr(
            capture_mod, "FileSource", lambda path, loop: EmptySource()
        )

        code = _run_replay(tmp_path / "v.avi")

        assert code == 1
        err = capsys.readouterr().err
        assert "Không đọc được khung nào" in err
        assert "Traceback" not in err

    def test_khong_tao_phan_cung_du_truyen_no_gpio(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _good_pose())
        video = _make_video(tmp_path / "v.avi", frames=4)

        def _boom(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("replay không được tạo phần cứng")

        from posture_monitor import hardware as hardware_pkg

        monkeypatch.setattr(hardware_pkg, "create_hardware", _boom)
        monkeypatch.setattr(
            cli, "cmd_run", lambda args: (_ for _ in ()).throw(
                AssertionError("replay không được gọi cmd_run")
            )
        )

        assert (
            cli.main(
                [
                    "replay",
                    str(video),
                    "--config",
                    str(_REPO_ROOT / "config.yaml"),
                    "--no-gpio",
                ]
            )
            == 0
        )

    def test_fps_khong_doc_duoc_thi_roi_ve_config_va_ghi_ro(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=0.0)
        _patch_estimator(monkeypatch, _good_pose())
        video = _make_video(tmp_path / "v.avi", frames=4)
        report_path = tmp_path / "out.json"

        assert _run_replay(video, report_path) == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert report["fps_source"] == "config.model.target_fps"
        assert report["video_fps"] == float(Config().model.target_fps)

    def test_loi_suy_luan_mot_khung_khong_lam_sap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _good_pose())

        from posture_monitor import pose as pose_mod

        class FlakyEstimator(FakeEstimator):
            def detect(self, frame):  # noqa: ANN001, ANN201
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("model hỏng tạm thời")
                return self._result

        flaky = FlakyEstimator(_good_pose())
        monkeypatch.setattr(pose_mod, "PoseEstimator", lambda config: flaky)
        video = _make_video(tmp_path / "v.avi", frames=6)
        report_path = tmp_path / "out.json"

        assert _run_replay(video, report_path) == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert report["summary"]["frames_errored"] >= 1
        assert report["summary"]["frames"] == 6
        assert report["frames"][1]["person"] is False
        assert report["frames"][1]["labels"] == ["ABSENT"]

    def test_thu_muc_bao_cao_duoc_tao(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _isolate_cwd(monkeypatch, tmp_path)
        _patch_probe(monkeypatch, fps=10.0)
        _patch_estimator(monkeypatch, _good_pose())
        video = _make_video(tmp_path / "v.avi", frames=3)
        report_path = tmp_path / "sau" / "out.json"

        assert _run_replay(video, report_path) == 0
        assert report_path.is_file()


#: Thông tin đăng nhập **bịa hoàn toàn**, không liên quan camera thật nào.
#: Viết thẳng dạng literal là chủ ý: nếu ai đó dán mật khẩu thật vào đây lần
#: nữa thì ``git grep`` phải tìm ra ngay.
_FAKE_USER = "nguoidung-gia"
_FAKE_PASSWORD = "matkhau-gia-123"
_FAKE_RTSP_URL = (
    f"rtsp://{_FAKE_USER}:{_FAKE_PASSWORD}@192.0.2.10:554/Streaming/Channels/101"
)


def test_redact_camera_source_che_thong_tin_dang_nhap() -> None:
    """URL có thông tin đăng nhập giả: che cả user lẫn mật khẩu, có ``***``."""
    redacted = redact_camera_source(_FAKE_RTSP_URL)

    assert redacted == "rtsp://***:***@192.0.2.10:554/Streaming/Channels/101"
    assert _FAKE_PASSWORD not in redacted
    assert _FAKE_USER not in redacted
    assert "***:***@" in redacted


def test_redact_camera_source_giu_nguyen_url_khong_dang_nhap() -> None:
    """URL không có thông tin đăng nhập: giữ nguyên từng ký tự."""
    plain = "rtsp://192.0.2.10:554/Streaming/Channels/101"

    assert redact_camera_source(plain) == plain
    assert "***" not in redact_camera_source(plain)


def test_bao_cao_replay_khong_mang_nguon_camera(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Báo cáo replay không được chứa nguồn camera, dù cấu hình có mật khẩu.

    Nguồn mang thông tin đăng nhập giả được đẩy vào qua
    ``POSTURE_CAMERA_SOURCE`` — đúng đường mà người dùng thật dùng để đặt URL
    RTSP kèm mật khẩu. Trước hết phải chứng minh biến môi trường **thật sự**
    đã đi vào cấu hình (nếu không, phần sau chỉ đúng vì báo cáo chưa bao giờ
    nhìn tới nguồn). Báo cáo replay chỉ mô tả đường dẫn video, nên nó phải
    sạch: không mật khẩu, không user, không cả dấu ``***`` (không có trường
    nguồn camera nào để mà che).
    """
    monkeypatch.setenv(CAMERA_SOURCE_ENV, _FAKE_RTSP_URL)
    config = load_config(_REPO_ROOT / "config.yaml")
    assert _FAKE_PASSWORD in config.camera.source, (
        "tiền đề hỏng: biến môi trường chưa đi vào cấu hình, phép thử vô nghĩa"
    )

    _isolate_cwd(monkeypatch, tmp_path)
    _patch_probe(monkeypatch, fps=10.0)
    _patch_estimator(monkeypatch, _good_pose())
    video = _make_video(tmp_path / "v.avi", frames=3)
    report_path = tmp_path / "out.json"

    assert _run_replay(video, report_path) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    text = report_path.read_text(encoding="utf-8")

    assert _FAKE_PASSWORD not in text
    assert _FAKE_USER not in text
    assert "***" not in text
    assert "camera" not in report
    assert "source" not in report
