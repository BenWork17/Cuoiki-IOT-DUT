"""Kiểm thử lệnh CLI ``calibrate`` (spec v2 §5.4, §7).

Nguyên tắc: **không cần camera, model, GPIO hay mạng**. Mọi thứ tốn kém được
thay bằng đối tượng giả theo đúng kiểu ``tests/test_benchmark.py``:

- ``FakeSource`` thay :class:`~posture_monitor.capture.FrameSource`;
- ``PoseEstimator`` trong :mod:`posture_monitor.pose` được thay bằng factory
  trả ``FakeEstimator`` (không tải trọng số);
- ``time`` trong :mod:`posture_monitor.__main__` được thay bằng đồng hồ giả,
  nên đếm ngược 3 giây và thu 5 giây chạy tức thì mà vẫn kiểm được **nhịp**
  lấy mẫu theo ``model.target_fps``.

Điều quan trọng nhất ở đây là **hợp đồng mã thoát**: 0 thành công, 1 lỗi
phần cứng/ghi file, 2 lỗi cấu hình/model/không đủ khung — cùng với việc
không bao giờ để lộ mật khẩu camera ra log.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import __main__ as cli  # noqa: E402
from posture_monitor import pose as pose_module  # noqa: E402
from posture_monitor.benchmark import WARMUP_FRAMES  # noqa: E402
from posture_monitor.calibration import (  # noqa: E402
    CAPTURE_S,
    COUNTDOWN_S,
    DEFAULT_PATH,
)
from posture_monitor.capture import FrameSource  # noqa: E402
from posture_monitor.config import CAMERA_SOURCE_ENV  # noqa: E402
from posture_monitor.pose import PoseError  # noqa: E402

#: Mật khẩu giả dùng để kiểm rò rỉ log. Cố ý **không** phải mật khẩu thật
#: của dự án, và phải không trùng chuỗi nào đang có trong repo.
SECRET = "mat-khau-gia-999"

# --------------------------------------------------------------------------
# Đối tượng giả
# --------------------------------------------------------------------------


class FakeClock:
    """Đồng hồ giả: ``sleep`` trôi thời gian ngay, ``monotonic`` đọc số đó.

    Nhờ vậy kiểm được đếm ngược/thời lượng thu mà test vẫn chạy trong vài
    mili giây. Vòng thu mới **không** ngủ theo ``target_fps`` nữa, nên thời
    gian trong cửa sổ thu do chính chi phí suy luận của ``FakeEstimator``
    đẩy tới — đúng như trên máy thật.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.now += max(0.0, float(seconds))

    def advance(self, seconds: float) -> None:
        """Trôi thời gian như một phép tính tốn kém (suy luận, đọc khung)."""
        self.now += max(0.0, float(seconds))

    def monotonic(self) -> float:
        return self.now

    def as_module(self) -> SimpleNamespace:
        """Đối tượng thay được cho tên ``time`` trong ``__main__``."""
        return SimpleNamespace(sleep=self.sleep, monotonic=self.monotonic)


class FakeSource(FrameSource):
    """Nguồn ảnh giả, đếm số lần ``read``/``close``."""

    def __init__(
        self,
        frames: int | None = 1,
        size: int = 32,
        clock: FakeClock | None = None,
        read_cost_s: float = 0.0,
    ) -> None:
        #: ``None`` nghĩa là nguồn chết: luôn trả ``None``.
        self._remaining = frames
        self._size = size
        self._clock = clock
        self._read_cost = read_cost_s
        self.reads = 0
        self.closed = 0
        #: Thời điểm (theo đồng hồ giả) của từng lần đọc thành công.
        self.read_log: list[float] = []

    def read(self):  # noqa: ANN201 - khớp hợp đồng FrameSource
        self.reads += 1
        if self._clock is not None:
            self._clock.advance(self._read_cost)
        if self._remaining is None:
            return None
        if self._remaining <= 0:
            return None
        self._remaining -= 1
        if self._clock is not None:
            self.read_log.append(self._clock.monotonic())
        return np.full(
            (self._size, self._size, 3), fill_value=90, dtype=np.uint8
        )

    def close(self) -> None:
        self.closed += 1

    @property
    def backend(self) -> str:
        return "gia"


def _fake_pose(shoulders: bool = True, conf: float = 0.9):
    """Pose tổng hợp: hai vai ngang nhau, đủ cho ``features.extract``."""
    xy = np.zeros((17, 2), dtype=np.float32)
    xy[0] = (300.0, 120.0)   # mũi
    xy[3] = (260.0, 110.0)   # tai trái
    xy[4] = (340.0, 110.0)   # tai phải
    xy[5] = (200.0, 200.0)   # vai trái
    xy[6] = (400.0, 200.0)   # vai phải
    xy[11] = (220.0, 330.0)
    xy[12] = (380.0, 330.0)
    xy[13] = (225.0, 420.0)
    xy[14] = (375.0, 420.0)
    conf_array = np.full((17,), conf, dtype=np.float32)
    if not shoulders:
        conf_array[5] = 0.0
        conf_array[6] = 0.0
    return SimpleNamespace(xy=xy, conf=conf_array)


class FakeEstimator:
    """Thay ``PoseEstimator``: không tải model, trả pose tổng hợp.

    ``first_cost_s`` mô phỏng lần suy luận nguội của ultralytics (đo trên Pi
    thật: ~3,7 s so với ~143 ms). ``cost_s`` là chi phí mỗi khung sau đó.
    """

    backend = "giả-lập"

    def __init__(
        self,
        pose=None,
        error=None,
        clock: FakeClock | None = None,
        cost_s: float = 0.0,
        first_cost_s: float = 0.0,
    ) -> None:
        self._pose = pose
        self._error = error
        self._clock = clock
        self._cost = cost_s
        self._first_cost = first_cost_s
        self.calls = 0
        self.last_person_count = 1
        #: Thời điểm (theo đồng hồ giả) bắt đầu từng lần ``detect``.
        self.call_log: list[float] = []

    def detect(self, frame):  # noqa: ANN001, ANN201 - khớp hợp đồng
        self.calls += 1
        if self._clock is not None:
            self.call_log.append(self._clock.monotonic())
            self._clock.advance(
                self._first_cost if self.calls == 1 else self._cost
            )
        if self._error is not None:
            raise self._error
        return self._pose


def _patch_estimator(monkeypatch, estimator) -> None:
    """Thay ``PoseEstimator`` **trong module pose** (cli import muộn)."""
    monkeypatch.setattr(
        pose_module, "PoseEstimator", lambda config: estimator
    )


def _patch_clock(monkeypatch) -> FakeClock:
    clock = FakeClock()
    monkeypatch.setattr(cli, "time", clock.as_module())
    return clock


def _write_config(
    tmp_path: Path,
    *,
    source: str = "usb:0",
    view: str = "front",
    fps: int = 5,
    width: int = 640,
    height: int = 480,
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "config.yaml"
    path.write_text(
        "camera:\n"
        f"  source: {source}\n"
        f"  width: {width}\n"
        f"  height: {height}\n"
        f"  view: {view}\n"
        "model:\n"
        f"  target_fps: {fps}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _khong_co_bien_moi_truong_camera(monkeypatch):
    """``POSTURE_CAMERA_SOURCE`` thắng ``camera.source``; gỡ ra cho ổn định."""
    monkeypatch.delenv(CAMERA_SOURCE_ENV, raising=False)


def _run_calibrate(config_path: Path, *extra: str) -> int:
    return cli.main(["calibrate", "--config", str(config_path), *extra])


#: Chi phí suy luận mỗi khung sau khi model đã nóng, tính bằng giây. Lấy từ
#: số đo trên Pi thật (~143 ms) để bài test mô phỏng đúng tỉ lệ với cửa sổ
#: CAPTURE_S = 5 s.
DETECT_COST_S = 0.143

#: Chi phí lần suy luận **đầu tiên** (nguội) — đo trên Pi thật là ~3,7 s.
COLD_COST_S = 3.7


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    frames: int = 10_000,
    pose=None,
    cost_s: float = DETECT_COST_S,
    first_cost_s: float = DETECT_COST_S,
) -> tuple[FakeClock, FakeEstimator, FakeSource]:
    """Gắn đồng hồ giả cho cả ``time``, ``PoseEstimator`` và nguồn ảnh.

    Vòng thu hiện chạy theo nhịp tự nhiên nên thời gian trôi chính là chi phí
    suy luận/đọc khung. Thiếu bước này thì đồng hồ đứng yên và vòng lặp không
    bao giờ kết thúc.
    """
    clock = FakeClock()
    monkeypatch.setattr(cli, "time", clock.as_module())
    estimator = FakeEstimator(
        pose if pose is not None else _fake_pose(),
        clock=clock,
        cost_s=cost_s,
        first_cost_s=first_cost_s,
    )
    _patch_estimator(monkeypatch, estimator)
    source = FakeSource(frames=frames, clock=clock)
    monkeypatch.setattr(cli, "capture_from_config", lambda config, s=source: s)
    return clock, estimator, source


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


class TestParser:
    def test_co_du_co_mau_va_mac_dinh_output(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["calibrate"])
        assert args.command == "calibrate"
        assert args.config == "config.yaml"
        assert args.output == DEFAULT_PATH
        assert args.no_gpio is False
        assert args.log_level == "INFO"

    def test_nhan_output_no_gpio_va_log_level(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "calibrate",
                "--config",
                "khac.yaml",
                "--output",
                "out.json",
                "--no-gpio",
                "--log-level",
                "DEBUG",
            ]
        )
        assert args.config == "khac.yaml"
        assert args.output == "out.json"
        assert args.no_gpio is True
        assert args.log_level == "DEBUG"


# --------------------------------------------------------------------------
# Đường thành công
# --------------------------------------------------------------------------


class TestThanhCong:
    def test_luu_baseline_va_tra_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        _, _, source = _setup(monkeypatch)

        config_path = _write_config(tmp_path)
        output = tmp_path / "calibration.json"
        code = _run_calibrate(config_path, "--output", str(output))

        assert code == 0
        assert output.is_file()
        # finally phải đóng nguồn đúng một lần.
        assert source.closed == 1

        raw = json.loads(output.read_text(encoding="utf-8"))
        assert raw["camera"] == {"view": "front", "width": 640, "height": 480}
        assert raw["frames"] > 0
        assert raw["baseline"]["shoulder_width"] == pytest.approx(200.0)

        out = capsys.readouterr().out
        assert "HIỆU CHỈNH XONG" in out
        assert f"Số khung dùng : {raw['frames']}" in out
        assert "shoulder_width" in out

    def test_dem_nguoc_3s_roi_thu_5s(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        clock, _, source = _setup(monkeypatch)

        assert _run_calibrate(_write_config(tmp_path)) == 0

        # WARMUP_FRAMES khung đầu là khung khởi động (không vào baseline);
        # khung thu đầu tiên đánh dấu cửa sổ CAPTURE_S mở ra.
        capture_start = source.read_log[WARMUP_FRAMES]
        # Cửa sổ thu phải dài đúng CAPTURE_S (sai số một lần suy luận).
        assert clock.now - capture_start == pytest.approx(
            CAPTURE_S, abs=0.3
        )
        # Đếm ngược chia thành từng bước <= 1 giây để log kịp cho người dùng.
        countdown_steps = clock.sleeps[: int(COUNTDOWN_S)]
        assert countdown_steps == [1.0, 1.0, 1.0]

    def test_nhip_lay_mau_khong_bi_gioi_han_boi_target_fps(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Thu ở nhịp tự nhiên: 5 s / 143 ms ⇒ ~35 khung, không phải ~25.

        Đây là điểm sửa của lỗi trên Pi: chờ ``1/target_fps`` biến 5 s thu
        thành ~25 mẫu, sát ngưỡng MIN_VALID_FRAMES=20 và dễ trượt. Thu theo
        nhịp tự nhiên cho nhiều mẫu hơn hẳn trong cùng 5 s.
        """
        _clock, _estimator, source = _setup(monkeypatch)
        assert _run_calibrate(_write_config(tmp_path, fps=5)) == 0

        natural = int(CAPTURE_S / DETECT_COST_S)  # ~34
        assert source.reads >= 20  # phải vượt ngưỡng spec
        # Không bị kẹp xuống mức 1 khung mỗi 1/target_fps = 0,2 s (25 khung).
        assert source.reads >= natural - 2

    def test_nhieu_mau_hon_khi_moi_khung_cham_hon(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Kể cả khi mỗi khung chậm 180 ms, 5 s vẫn gom đủ >= 20 khung."""
        _clock, _estimator, source = _setup(monkeypatch, cost_s=0.18)
        assert _run_calibrate(_write_config(tmp_path)) == 0
        assert source.reads >= 24

    def test_nap_truoc_model_truoc_cua_so_thu(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Lần suy luận nguội ~3,7 s **không** được ăn vào cửa sổ 5 s thu.

        Đây là bài test chống tái phát đúng lỗi trên Pi: nếu bỏ bước nạp
        trước, lần gọi đầu rơi vào cửa sổ và chỉ còn vài khung; có nạp trước
        thì mọi lần ``detect`` bên trong cửa sổ đều đã nóng.
        """
        clock, estimator, source = _setup(
            monkeypatch, cost_s=DETECT_COST_S, first_cost_s=COLD_COST_S
        )

        assert _run_calibrate(_write_config(tmp_path)) == 0

        # Lần gọi nguội phải xảy ra TRƯỚC khi cửa sổ thu mở.
        assert estimator.calls > WARMUP_FRAMES
        capture_start = source.read_log[WARMUP_FRAMES]
        warmup_calls = [
            call_time
            for call_time in estimator.call_log
            if call_time < capture_start
        ]
        assert len(warmup_calls) >= WARMUP_FRAMES
        # Cửa sổ vẫn gom đủ khung hợp lệ cho baseline.
        assert source.reads >= 20

    def test_output_mac_dinh_la_calibration_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _setup(monkeypatch)

        monkeypatch.chdir(tmp_path)
        assert _run_calibrate(_write_config(tmp_path)) == 0
        assert (tmp_path / DEFAULT_PATH).is_file()

    def test_tao_thu_muc_cha_cho_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _setup(monkeypatch)
        output = tmp_path / "sau" / "con" / "calibration.json"
        assert _run_calibrate(_write_config(tmp_path), "--output", str(output)) == 0
        assert output.is_file()

    def test_no_gpio_la_noop_va_khong_dung_phan_cung(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        _setup(monkeypatch)

        import posture_monitor.hardware as hardware_pkg

        called: list[object] = []
        monkeypatch.setattr(
            hardware_pkg, "create_hardware", lambda *a, **k: called.append(True)
        )

        code = _run_calibrate(_write_config(tmp_path), "--no-gpio")

        assert code == 0
        assert called == []  # calibrate không dựng phần cứng
        err = capsys.readouterr().err
        assert "no-op" in err


# --------------------------------------------------------------------------
# Đường lỗi — mã thoát rõ ràng, không crash
# --------------------------------------------------------------------------


class TestLoi:
    def test_khong_mo_duoc_camera_tra_1_va_goi_y(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        _patch_clock(monkeypatch)
        monkeypatch.setattr(cli, "capture_from_config", lambda config: None)

        code = _run_calibrate(_write_config(tmp_path))

        assert code == 1
        err = capsys.readouterr().err
        assert "camera_probe.py" in err
        assert "posture_monitor run" in err

    def test_nguon_mo_duoc_nhung_khong_tra_khung_nao_tra_1(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        clock, _estimator, source = _setup(monkeypatch, frames=0)
        assert source.reads == 0  # mở được nhưng read() luôn None

        code = _run_calibrate(_write_config(tmp_path))

        assert code == 1
        assert source.closed == 1
        err = capsys.readouterr().err
        assert "camera_probe.py" in err

    def test_khong_du_khung_hop_le_tra_2_va_in_nguyen_van_thong_diep(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        # Không thấy vai ở mọi khung ⇒ calibration lọc sạch ⇒ CalibrationError.
        _setup(monkeypatch, pose=_fake_pose(shoulders=False))

        code = _run_calibrate(_write_config(tmp_path))

        assert code == 2
        err = capsys.readouterr().err
        # Thông điệp của calibration phải được giữ nguyên (đã có hướng dẫn).
        assert "khung hợp lệ" in err
        assert "hai vai" in err
        assert "calibrate" in err

    def test_pose_error_tra_2_va_dong_nguon(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        def _raise(config):  # noqa: ANN001, ANN202
            raise PoseError("Không nạp được model pose 'x'.")

        monkeypatch.setattr(pose_module, "PoseEstimator", _raise)
        clock = _patch_clock(monkeypatch)
        source = FakeSource(frames=10_000, clock=clock)
        monkeypatch.setattr(cli, "capture_from_config", lambda config: source)

        assert _run_calibrate(_write_config(tmp_path)) == 2
        assert source.closed == 1
        assert "Không nạp được model pose" in capsys.readouterr().err

    def test_thieu_file_config_tra_2(self, tmp_path: Path) -> None:
        assert _run_calibrate(tmp_path / "khong_co.yaml") == 2

    def test_config_sai_kiem_tra_tra_2(
        self, tmp_path: Path, capsys
    ) -> None:
        path = tmp_path / "config.yaml"
        path.write_text(
            "camera:\n  source: khong_hop_le\n", encoding="utf-8"
        )
        assert _run_calibrate(path) == 2
        assert "cấu hình" in capsys.readouterr().err.lower()

    def test_ghi_file_loi_tra_1(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        _clock, _estimator, source = _setup(monkeypatch)

        from posture_monitor import calibration

        def _loi(baseline, path):  # noqa: ANN001, ANN202
            raise OSError("hết chỗ")

        monkeypatch.setattr(calibration, "save", _loi)

        assert _run_calibrate(_write_config(tmp_path)) == 1
        assert source.closed == 1
        assert "Không ghi được file baseline" in capsys.readouterr().err

    def test_khong_lap_lai_thong_diep_not_implemented(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        _patch_clock(monkeypatch)
        monkeypatch.setattr(cli, "capture_from_config", lambda config: None)

        _run_calibrate(_write_config(tmp_path))
        out = capsys.readouterr().out
        assert "chưa triển khai" not in out


# --------------------------------------------------------------------------
# Bảo mật — mật khẩu camera không bao giờ lọt ra log/output
# --------------------------------------------------------------------------


class TestBaoMat:
    def test_khong_lo_mat_khau_khi_khong_mo_duoc_camera(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        _patch_clock(monkeypatch)
        monkeypatch.setattr(cli, "capture_from_config", lambda config: None)

        config_path = _write_config(
            tmp_path,
            source=f"rtsp:rtsp://admin:{SECRET}@192.168.1.50:554/1/2",
        )
        assert _run_calibrate(config_path) == 1

        captured = capsys.readouterr()
        assert SECRET not in captured.err
        assert SECRET not in captured.out
        assert "***" in captured.err

    def test_khong_lo_mat_khau_khi_thu_khung_that_bai(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ) -> None:
        clock, _estimator, source = _setup(monkeypatch, frames=0)
        assert source.reads == 0  # mở được nhưng read() luôn None

        config_path = _write_config(
            tmp_path,
            source=f"rtsp:rtsp://admin:{SECRET}@192.168.1.50:554/1/2",
        )
        assert _run_calibrate(config_path) == 1

        captured = capsys.readouterr()
        assert SECRET not in captured.err
        assert SECRET not in captured.out


# --------------------------------------------------------------------------
# Dispatch của main()
# --------------------------------------------------------------------------


def test_main_dispatch_calibrate_khong_roi_vao_not_implemented(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    _setup(monkeypatch)
    config_path = _write_config(tmp_path)

    assert cli.main(["calibrate", "--config", str(config_path)]) == 0
    captured = capsys.readouterr()
    assert "chưa triển khai" not in captured.out
    assert "chưa triển khai" not in captured.err


def test_keyboard_interrupt_tra_130(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    def _raise(args):  # noqa: ANN001, ANN202
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_calibrate", _raise)
    assert cli.main(["calibrate", "--config", "x.yaml"]) == 130


def test_loi_khong_mong_doi_khong_crash(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def _raise(args):  # noqa: ANN001, ANN202
        raise RuntimeError("bùm")

    monkeypatch.setattr(cli, "cmd_calibrate", _raise)
    assert cli.main(["calibrate", "--config", "x.yaml"]) == 1
    assert "bùm" in capsys.readouterr().err
