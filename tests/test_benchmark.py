"""Kiểm thử ``benchmark.py`` (spec v2 §8, §9, §11.6).

Nguyên tắc của bộ test này: **không cần model thật, không cần camera, không
cần ``vcgencmd``**. Mọi thứ tốn kém đều được thay bằng đối tượng giả:

- ``FakeEstimator`` thay ``PoseEstimator`` (không tải 6 MB trọng số);
- ``FrameListSource`` / danh sách khung ``numpy`` thay camera;
- ``_Command`` được thay bằng hàm giả để kiểm cả hai nhánh "có vcgencmd" và
  "máy PC không có vcgencmd".

Phần cuối file có một bài tích hợp thật, tự bỏ qua khi máy không có trọng số
``yolo11n-pose.pt``.

Điều quan trọng nhất được kiểm ở đây không phải "số đẹp" mà là **tính trung
thực của báo cáo**: thiếu nguồn số liệu thì phải là ``null`` kèm lý do, throttle
bật thì FPS phải bị đánh dấu không hợp lệ, nguồn ảnh tĩnh không được trình bày
như camera thật.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import benchmark as bench  # noqa: E402
from posture_monitor.capture import FrameSource  # noqa: E402
from posture_monitor.config import Config  # noqa: E402
from posture_monitor.pose import PoseResult  # noqa: E402

# --------------------------------------------------------------------------
# Đối tượng giả
# --------------------------------------------------------------------------


def _keypoints() -> PoseResult:
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


class FakeEstimator:
    """Thay ``PoseEstimator``: không tải model, trả pose tổng hợp."""

    backend = "giả-lập"

    def __init__(self, result: PoseResult | None = None, error=None) -> None:
        self._result = result
        self._error = error
        self.calls = 0
        self._model = None  # không có callback ultralytics

    def detect(self, frame):  # noqa: ANN001, ANN201 - khớp hợp đồng
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


def _patch_estimator(monkeypatch, estimator) -> None:
    """Thay ``PoseEstimator`` trong module benchmark bằng đối tượng giả."""
    monkeypatch.setattr(bench, "PoseEstimator", lambda config: estimator)


def _patch_commands(monkeypatch, temp=None, throttle=None) -> None:
    """Thay ``_Command`` để không phụ thuộc ``vcgencmd`` của máy chạy test.

    ``temp``/``throttle`` là chuỗi kết quả giả, hoặc ``None`` để mô phỏng máy
    không có lệnh (PC).
    """

    class _FakeCommand:
        def __init__(self, *argv: str) -> None:
            self._argv = argv

        def run(self, timeout: float = 2.0):  # noqa: ANN201
            if self._argv[0] != "vcgencmd":
                return None, f"Không có lệnh '{self._argv[0]}'."
            if self._argv[-1] == "measure_temp":
                if temp is None:
                    return None, "Không có lệnh 'vcgencmd' trên máy này."
                return temp, None
            if self._argv[-1] == "get_throttled":
                if throttle is None:
                    return None, "Không có lệnh 'vcgencmd' trên máy này."
                return throttle, None
            return None, "Tham số không hỗ trợ."

    monkeypatch.setattr(bench, "_Command", _FakeCommand)


def _frames(count: int = 2, size: int = 64) -> list[np.ndarray]:
    """Khung tổng hợp tối giản, đủ shape và dtype như ảnh BGR thật."""
    return [
        np.full((size, size, 3), fill_value=index * 10, dtype=np.uint8)
        for index in range(count)
    ]


def _run(config=None, seconds=0.15, source=None):  # noqa: ANN001, ANN201
    return bench.run_benchmark(
        config or Config(), seconds, source_override=source or _frames()
    )


# --------------------------------------------------------------------------
# Schema báo cáo
# --------------------------------------------------------------------------


class TestReportSchema:
    """Báo cáo phải có đủ khóa mà tầng CLI/người đọc cần."""

    def test_bao_cao_co_du_khoa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=55.0'C", throttle="throttled=0x0")

        report = _run()

        for key in (
            "report_version",
            "generated_at",
            "duration_s",
            "host",
            "source",
            "model",
            "baseline",
            "frames",
            "timing_ms",
            "fps",
            "temperature_c",
            "memory_mb",
            "throttle",
            "criteria",
            "notices",
            "warnings",
        ):
            assert key in report, f"thiếu khóa '{key}'"

        assert report["report_version"] == bench.REPORT_VERSION
        assert report["model"]["backend"] == "giả-lập"
        # Toàn bộ dict phải serialize được thành JSON máy đọc được.
        json.dumps(report, ensure_ascii=False)

    def test_thoi_gian_tung_khau_duoc_ghi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=50.0'C", throttle="throttled=0x0")

        report = _run(seconds=0.2)
        timing = report["timing_ms"]

        for key in (
            "pipeline_total",
            "capture",
            "pose_detect",
            "features",
            "classify",
            "state_update",
        ):
            stats = timing[key]
            assert stats is not None, f"thiếu thống kê '{key}'"
            assert stats["count"] > 0
            assert stats["min"] <= stats["median"] <= stats["max"]

        measured = report["frames"]["measured"]
        assert measured > 0
        assert timing["pipeline_total"]["count"] == measured

    def test_khong_lay_duoc_thoi_gian_ultralytics_thi_null(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Estimator giả không có callback → ba khâu UL phải là ``None``."""
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=50.0'C", throttle="throttled=0x0")

        report = _run()
        for key in ("pose_preprocess", "pose_inference", "pose_postprocess"):
            assert report["timing_ms"][key] is None, (
                f"'{key}' phải là None khi không lấy được số từ ultralytics, "
                "không được ước lượng"
            )

    def test_fps_suy_tu_median_toan_khung(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=50.0'C", throttle="throttled=0x0")

        report = _run(seconds=0.2)
        median = report["timing_ms"]["pipeline_total"]["median"]
        expected = 1000.0 / median

        assert report["fps"]["pipeline_median"] == pytest.approx(expected, rel=1e-3)
        # Ghi rõ đây là FPS pipeline, không phải FPS suy luận thuần.
        assert "pipeline" in report["fps"]["note"].lower()
        assert "không phải" in report["fps"]["note"].lower()


# --------------------------------------------------------------------------
# Trung thực khi thiếu nguồn số liệu (máy PC)
# --------------------------------------------------------------------------


class TestThieuNguonSoLieu:
    """PC không có ``vcgencmd``: phải ghi ``null`` + lý do, không bịa số."""

    def test_khong_co_vcgencmd_thi_nhiet_va_throttle_la_null(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp=None, throttle=None)

        report = _run()

        temperature = report["temperature_c"]
        assert temperature["available"] is False
        assert temperature["min"] is None
        assert temperature["median"] is None
        assert temperature["max"] is None
        assert "vcgencmd" in (temperature["reason"] or "")

        throttle = report["throttle"]
        assert throttle["available"] is False
        assert throttle["final"] is None
        assert throttle["any_set"] is False
        assert "vcgencmd" in (throttle["reason"] or "")

        # Phải nói rõ trong ghi chú để người đọc không tưởng là "0 °C".
        assert any("Nhiệt độ CPU" in notice for notice in report["notices"])

    def test_thieu_psutil_thi_ram_null(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=50.0'C", throttle="throttled=0x0")
        monkeypatch.setattr(bench, "psutil", None)

        report = _run()

        memory = report["memory_mb"]
        assert memory["available"] is False
        assert memory["start"] is None
        assert memory["peak"] is None
        assert "psutil" in (memory["reason"] or "")
        assert any("psutil" in warning for warning in report["warnings"])

    def test_tieu_chi_khong_ket_luan_khi_thieu_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Thiếu số thì ``pass=None`` — tuyệt đối không mặc định là đạt."""
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp=None, throttle=None)
        monkeypatch.setattr(bench, "psutil", None)

        report = _run()
        criteria = {item["key"]: item for item in report["criteria"]}

        assert criteria["temperature"]["pass"] is None
        assert criteria["temperature"]["measured"] is None
        assert criteria["memory"]["pass"] is None
        assert criteria["throttle"]["pass"] is None

        # FPS vẫn đo được, nhưng §8 chỉ cho phép kết luận khi đã loại trừ
        # throttle. Máy không có vcgencmd thì chưa loại trừ được → không kết
        # luận, không được mặc định "đạt".
        assert criteria["fps"]["measured"] is not None
        assert criteria["fps"]["pass"] is None
        assert report["fps"]["valid"] is False
        assert "throttle" in criteria["fps"]["note"].lower()

    def test_throttle_sach_thi_fps_moi_duoc_ket_luan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Có ``vcgencmd`` và ``0x0`` → FPS mới đủ căn cứ kết luận đạt/không."""
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=55.0'C", throttle="throttled=0x0")

        report = _run()
        criteria = {item["key"]: item for item in report["criteria"]}
        assert report["fps"]["valid"] is True
        assert criteria["fps"]["pass"] is not None


# --------------------------------------------------------------------------
# Throttle — tiêu chí §8 nghiêm ngặt nhất
# --------------------------------------------------------------------------


class TestThrottle:
    """Bit 0x4/0x40000 bật thì FPS **không hợp lệ**, dù số có đẹp."""

    def test_throttle_bat_thi_fps_khong_hop_le(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=60.0'C", throttle="throttled=0x40000")

        report = _run()

        assert report["throttle"]["invalidates_fps"] is True
        assert report["fps"]["valid"] is False
        criteria = {item["key"]: item for item in report["criteria"]}
        assert criteria["fps"]["pass"] is False
        assert "KHÔNG HỢP LỆ" in criteria["fps"]["note"]
        assert any("THROTTLE" in warning for warning in report["warnings"])

    def test_throttle_chi_bit_da_qua_van_lam_fps_khong_hop_le(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``0x10000`` (từng under-voltage) không làm FPS sai, nhưng ``0x4`` thì có."""
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))

        _patch_commands(monkeypatch, temp="temp=60.0'C", throttle="throttled=0x10000")
        report = _run()
        assert report["throttle"]["any_set"] is True
        assert report["throttle"]["invalidates_fps"] is False
        # Có bit bật nhưng không phải bit làm hỏng FPS → vẫn cảnh báo.
        assert any("THROTTLE" in warning for warning in report["warnings"])

        _patch_commands(monkeypatch, temp="temp=60.0'C", throttle="throttled=0x4")
        report = _run()
        assert report["throttle"]["invalidates_fps"] is True
        assert report["fps"]["valid"] is False

    def test_throttle_sach_thi_fps_hop_le(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=55.0'C", throttle="throttled=0x0")

        report = _run()

        assert report["throttle"]["final"] == "0x0"
        assert report["throttle"]["any_set"] is False
        assert report["throttle"]["invalidates_fps"] is False
        assert report["fps"]["valid"] is True
        assert report["throttle"]["flags"] == []

    def test_lay_mau_throttle_dinh_kem_nhiet_do(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=57.5'C", throttle="throttled=0x0")

        report = _run()

        assert report["throttle"]["samples"], "phải có mẫu throttle để đối chiếu"
        first = report["throttle"]["samples"][0]
        assert first["temp_c"] == pytest.approx(57.5)
        assert first["throttled"] == "0x0"


# --------------------------------------------------------------------------
# Nguồn dữ liệu — không được giả vờ là camera thật
# --------------------------------------------------------------------------


class TestNguonDuLieu:
    """Nguồn ảnh tĩnh/tổng hợp phải tự khai báo, không được nhận vơ."""

    def test_nguon_tong_hop_duoc_ghi_ro(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=50.0'C", throttle="throttled=0x0")

        report = _run(source=_frames(3))

        assert report["source"]["kind"] == "synthetic"
        assert report["source"]["is_static"] is False
        assert any("TỔNG HỢP" in notice for notice in report["notices"])

    def test_anh_tinh_duoc_ghi_ro_khong_phai_camera(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import cv2

        image_path = tmp_path / "mau.jpg"
        assert cv2.imwrite(str(image_path), np.full((48, 64, 3), 120, np.uint8))

        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=52.0'C", throttle="throttled=0x0")

        report = bench.run_benchmark(
            Config(), 0.15, source_override=f"file:{image_path}"
        )

        assert report["source"]["kind"] == "image"
        assert report["source"]["is_static"] is True
        assert "KHÔNG phải FPS camera thật" in report["source"]["note"]
        assert any("ẢNH TĨNH" in notice for notice in report["notices"])
        # Kết luận FPS phải nhắc lại đây là cận trên.
        criteria = {item["key"]: item for item in report["criteria"]}
        assert "cận trên" in criteria["fps"]["note"]

    def test_nguon_khong_ton_tai_thi_bao_loi_ro_rang(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp=None, throttle=None)

        missing = tmp_path / "khong_co.jpg"
        with pytest.raises(bench.BenchmarkError) as info:
            bench.run_benchmark(
                Config(), 0.1, source_override=f"file:{missing}"
            )
        assert "không tồn tại" in str(info.value)

    def test_nguon_do_ben_goi_truyen_vao_khong_bi_dong(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Benchmark không được đóng hộ nguồn mà nó không sở hữu."""

        class OwnedSource(FrameSource):
            def __init__(self) -> None:
                self.closed = False
                self._frames = _frames()

            def read(self):  # noqa: ANN201
                return self._frames[0]

            def close(self) -> None:
                self.closed = True

            @property
            def backend(self) -> str:
                return "gia"

        source = OwnedSource()
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp=None, throttle=None)

        bench.run_benchmark(Config(), 0.1, source_override=source)
        assert source.closed is False

    def test_nguon_tu_mo_thi_duoc_dong(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import cv2

        image_path = tmp_path / "mau.png"
        assert cv2.imwrite(str(image_path), np.full((32, 32, 3), 90, np.uint8))

        closed: list[bool] = []
        original_close = bench.StaticImageSource.close

        def spy_close(self):  # noqa: ANN001, ANN202
            closed.append(True)
            original_close(self)

        monkeypatch.setattr(bench.StaticImageSource, "close", spy_close)
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp=None, throttle=None)

        bench.run_benchmark(Config(), 0.1, source_override=f"file:{image_path}")
        assert closed == [True]


# --------------------------------------------------------------------------
# Đường lỗi — không crash, mã thoát rõ ràng
# --------------------------------------------------------------------------


class TestDuongLoi:
    def test_seconds_khong_hop_le_bi_tu_choi(self) -> None:
        for value in (0, -1, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                bench.run_benchmark(Config(), value, source_override=_frames())

    def test_khong_doc_duoc_khung_nao_thi_bao_loi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class DeadSource(FrameSource):
            def read(self):  # noqa: ANN201
                return None

            def close(self) -> None:
                pass

            @property
            def backend(self) -> str:
                return "chet"

        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp=None, throttle=None)

        with pytest.raises(bench.BenchmarkError) as info:
            bench.run_benchmark(Config(), 0.1, source_override=DeadSource())
        assert "không đọc được khung nào" in str(info.value).lower() or (
            "Không đọc được khung nào" in str(info.value)
        )

    def test_suy_luan_loi_lien_tuc_thi_bao_loi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(error=RuntimeError("model hỏng")))
        _patch_commands(monkeypatch, temp=None, throttle=None)

        with pytest.raises(bench.BenchmarkError) as info:
            bench.run_benchmark(Config(), 0.2, source_override=_frames())
        assert "pose" in str(info.value).lower()

    def test_main_tra_ma_khac_0_khi_khong_do_duoc(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")

        # Không có model và nguồn không mở được → phải trả mã lỗi, không crash.
        monkeypatch.setattr(
            bench,
            "run_benchmark",
            lambda *a, **k: (_ for _ in ()).throw(bench.BenchmarkError("hỏng")),
        )
        code = bench.main(["--config", str(config_path), "--seconds", "1"])
        assert code != 0

    def test_main_thieu_file_config(self, tmp_path: Path) -> None:
        code = bench.main(
            ["--config", str(tmp_path / "khong_co.yaml"), "--seconds", "1"]
        )
        assert code == 2

    def test_main_seconds_khong_hop_le(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("camera:\n  source: usb:0\n", encoding="utf-8")
        assert bench.main(["--config", str(config_path), "--seconds", "0"]) == 2


# --------------------------------------------------------------------------
# Nguồn ảnh phụ trợ
# --------------------------------------------------------------------------


class TestNguonPhuTro:
    def test_frame_list_source_lap_vong(self) -> None:
        frames = _frames(2)
        source = bench.FrameListSource(frames)
        seen = [source.read() for _ in range(3)]
        assert seen[0] is frames[0]
        assert seen[1] is frames[1]
        assert seen[2] is frames[0]
        assert source.backend == "synthetic"

    def test_frame_list_source_tu_choi_danh_sach_rong(self) -> None:
        from posture_monitor.capture import CameraError

        with pytest.raises(CameraError):
            bench.FrameListSource([])

    def test_static_image_source_doc_anh(
        self, tmp_path: Path
    ) -> None:
        import cv2

        image_path = tmp_path / "a.png"
        assert cv2.imwrite(str(image_path), np.full((20, 30, 3), 7, np.uint8))

        source = bench.StaticImageSource(image_path)
        frame = source.read()
        assert frame is not None
        assert frame.shape == (20, 30, 3)
        assert source.backend == "image"
        source.close()
        assert source.read() is None  # sau khi đóng thì không trả khung nữa

    def test_static_image_source_tu_choi_file_rac(self, tmp_path: Path) -> None:
        from posture_monitor.capture import CameraError

        junk = tmp_path / "rac.jpg"
        junk.write_bytes(b"khong phai anh")
        with pytest.raises(CameraError):
            bench.StaticImageSource(junk)


# --------------------------------------------------------------------------
# Bộ phân tích vcgencmd
# --------------------------------------------------------------------------


class TestPhanTichVcgencmd:
    def test_doc_nhiet_do(self) -> None:
        assert bench._parse_temp("temp=55.0'C") == pytest.approx(55.0)
        assert bench._parse_temp("temp=72.3'C\n") == pytest.approx(72.3)
        assert bench._parse_temp("") is None
        assert bench._parse_temp("rac") is None

    def test_doc_throttled(self) -> None:
        assert bench._parse_throttled("throttled=0x0") == 0
        assert bench._parse_throttled("throttled=0x40000") == 0x40000
        assert bench._parse_throttled("throttled=0x4") == 0x4
        assert bench._parse_throttled("rac") is None

    def test_mo_ta_bitmask(self) -> None:
        described = bench._describe_throttle(0x50000)
        assert described["any_set"] is True
        assert described["invalidates_fps"] is True
        bits = {flag["bit"] for flag in described["flags"]}
        assert bits == {"0x10000", "0x40000"}

        clean = bench._describe_throttle(0)
        assert clean["any_set"] is False
        assert clean["invalidates_fps"] is False
        assert clean["flags"] == []


# --------------------------------------------------------------------------
# Định dạng báo cáo cho người đọc
# --------------------------------------------------------------------------


class TestDinhDang:
    def test_bao_cao_co_bang_tieng_viet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp="temp=58.0'C", throttle="throttled=0x0")

        text = bench.format_report(_run())

        assert "BÁO CÁO BENCHMARK" in text
        assert "THỜI GIAN TỪNG KHÂU" in text
        assert "TIÊU CHÍ NGHIỆM THU" in text
        assert "FPS pipeline" in text
        assert "58.00" in text

    def test_bao_cao_ghi_ro_khi_khong_do_duoc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_estimator(monkeypatch, FakeEstimator(_keypoints()))
        _patch_commands(monkeypatch, temp=None, throttle=None)
        monkeypatch.setattr(bench, "psutil", None)

        text = bench.format_report(_run())

        assert "không đo được" in text
        assert "KHÔNG KẾT LUẬN" in text


# --------------------------------------------------------------------------
# Tích hợp thật — tự bỏ qua khi máy không có trọng số
# --------------------------------------------------------------------------


_WEIGHTS = _REPO_ROOT / "yolo11n-pose.pt"


@pytest.mark.skipif(
    not _WEIGHTS.is_file(),
    reason="Máy không có yolo11n-pose.pt; bỏ qua bài tích hợp model thật.",
)
def test_tich_hop_model_that_tren_anh_tinh(tmp_path: Path) -> None:
    """Chạy thật với model và ảnh tĩnh, kiểm báo cáo tự nhất quán.

    Bài này không đặt chỉ tiêu §8 (máy PC không phải máy đích) — nó chỉ kiểm
    rằng đường code thật chạy được và báo cáo không tự mâu thuẫn.
    """
    import cv2

    image_path = tmp_path / "mau.jpg"
    assert cv2.imwrite(str(image_path), np.full((480, 640, 3), 100, np.uint8))

    report = bench.run_benchmark(
        Config(), 0.5, source_override=f"file:{image_path}"
    )

    assert report["model"]["backend"] in ("ncnn", "onnx", "pt")
    assert report["source"]["kind"] == "image"
    assert report["frames"]["measured"] > 0
    assert report["timing_ms"]["pose_detect"] is not None
    assert report["fps"]["pipeline_median"] > 0
    json.dumps(report, ensure_ascii=False)
