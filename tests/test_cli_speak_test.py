"""Kiểm thử lệnh ``speak-test`` của CLI.

Vì sao có lệnh này: ``POST /api/speak`` phát được nhưng phải mở web, phải tự
dựng JSON cho từng câu, và không nói được câu nào đang thiếu bản thu.
``speak-test`` chạy độc lập — không mở luồng hình, không đụng GPIO/DB — nên
người triển khai nghe thử đúng giọng đang cấu hình trước khi trình diễn.

Nguyên tắc kiểm thử: **không cần camera, loa, ffmpeg hay ``espeak-ng``**.
``SpeakerAlerter`` được thay bằng bản giả ghi lại lời gọi; phần cần kiểm ở đây
là **hợp đồng dòng lệnh** — cờ nào có, mặc định là gì, mã thoát nào, và
``--voice``/``--volume``/``--speed`` có thật sự chỉ ảnh hưởng lần chạy này
(``voice.json`` không bị ghi) hay không.

Ranh giới với ``test_speaker_alert.py``: file kia kiểm *quyết định phát gì*;
file này kiểm *lệnh có chuyển đúng tham số xuống quyết định đó*.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor import __main__ as cli  # noqa: E402
from posture_monitor.speaker_alert import (  # noqa: E402
    MODE_SKIPPED,
    MODE_SPEECH,
    AlertOutcome,
)

#: Ba câu mà ``speak-test`` biết phát, đúng thứ tự.
_KINDS = ("leave_frame", "phone", "stranger")


# --------------------------------------------------------------------------
# Bản giả
# --------------------------------------------------------------------------
class FakeAlerter:
    """Thay ``SpeakerAlerter``: ghi lại lời gọi, không chạm loa.

    Ghi lại ``from_config`` nhận những kwarg nào — đó là cách duy nhất chứng
    minh ``--voice``/``--volume``/``--speed`` thật sự đi xuống dưới, thay vì
    chỉ được parser nhận rồi bỏ.
    """

    #: Lời gọi ``from_config`` gần nhất: ``(config, kwargs)``.
    last_from_config: tuple[object, dict] | None = None
    #: Danh sách đối tượng đã dựng, để test đọc ``calls``.
    instances: list[FakeAlerter] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.available = True
        self.volume = float(kwargs.get("volume", 0.7))
        self.speed = float(kwargs.get("speed", 0.9))
        self.voice = str(kwargs.get("voice", "nu"))
        self.audio_dir = Path("data/audio")
        #: Mỗi lần ``alert``/``speak_tone_now`` thành công, thêm loại vào đây.
        self.calls: list[str] = []
        #: Kịch bản: tên loại cần trả trạng thái lỗi/bận.
        self.fail_kinds: set[str] = set()
        self.tone_kinds: list[str] = []
        FakeAlerter.instances.append(self)

    @classmethod
    def from_config(cls, config, **kwargs):
        FakeAlerter.last_from_config = (config, dict(kwargs))
        return cls(**kwargs)

    def prepare(self) -> None:
        pass

    def wav_path(self, kind: str):
        return self.audio_dir / f"{kind}.nu.s90.wav"

    def voice_report(self) -> dict:
        return {
            "voice": self.voice,
            "volume": self.volume,
            "speed": self.speed,
            "voices": {
                "nu": {"label": "Nữ", "clips": {}, "missing": []},
                "nam": {"label": "Nam", "clips": {}, "missing": []},
            },
            "fallbacks": {},
            "error": None,
        }

    def _outcome(
        self, kind: str, *, spoken: bool, error=None, record: bool = True
    ) -> AlertOutcome:
        if spoken and record and kind not in self.fail_kinds:
            self.calls.append(kind)
        return AlertOutcome(
            kind=kind,
            text=None,
            spoken=spoken and kind not in self.fail_kinds,
            mode=MODE_SPEECH if kind not in self.fail_kinds else MODE_SKIPPED,
            reason="kịch bản test",
            error=error,
            at=0.0,
        )

    def alert(self, kind: str) -> AlertOutcome:
        return self._outcome(kind, spoken=True)

    def speak_tone_now(self, kind: str) -> AlertOutcome:
        self.tone_kinds.append(kind)
        # ``calls`` chỉ đếm **câu nói**; đường bíp có danh sách riêng để test
        # phân biệt được hai đường, thay vì cả hai cùng đổ vào một chỗ.
        return self._outcome(kind, spoken=True, record=False)


class ExplodingAlerter(FakeAlerter):
    """``from_config`` ném lỗi: lệnh phải trả mã 2, không traceback."""

    @classmethod
    def from_config(cls, config, **kwargs):
        raise RuntimeError("cấu hình loa hỏng")


class UnavailableAlerter(FakeAlerter):
    """``available`` False: chưa bật loa thì không phát được gì."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.available = False


@pytest.fixture(autouse=True)
def _reset_fakes():
    FakeAlerter.last_from_config = None
    FakeAlerter.instances = []
    yield
    FakeAlerter.last_from_config = None
    FakeAlerter.instances = []


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Config tối thiểu, đọc được bởi ``load_config``, không chạm ``data/`` thật."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "speaker_alert:\n"
        "  say: true\n"
        "  volume: 0.55\n"
        "  speed: 0.85\n"
        "  audio_dir: "
        f"{(tmp_path / 'audio').as_posix()}\n",
        encoding="utf-8",
    )
    return path


def _patch_alerter(monkeypatch, cls=FakeAlerter) -> None:
    """Thay ``SpeakerAlerter`` ở đúng chỗ ``cmd_speak_test`` import nó."""
    import posture_monitor.speaker_alert as speaker_mod

    monkeypatch.setattr(speaker_mod, "SpeakerAlerter", cls)


def _run(monkeypatch, config_path: Path, *argv: str, cls=FakeAlerter) -> int:
    _patch_alerter(monkeypatch, cls)
    return cli.main(["speak-test", "--config", str(config_path), *argv])


# --------------------------------------------------------------------------
# Parser — cờ phải tồn tại và mặc định đúng
# --------------------------------------------------------------------------
class TestParser:
    def test_lenh_speak_test_co_that(self) -> None:
        """``speak-test`` là lệnh con thật, không còn là lời hứa trong spec."""
        args = cli.build_parser().parse_args(["speak-test"])
        assert args.command == "speak-test"

    def test_mac_dinh_phat_ca_ba_cau(self) -> None:
        """Mặc định ``--kind all``: phát lần lượt cả ba để nghe câu nào thiếu."""
        args = cli.build_parser().parse_args(["speak-test"])
        assert args.kind == "all"
        assert cli.SPEAK_TEST_KINDS == _KINDS

    def test_mac_dinh_khong_doi_giong_hay_am_luong(self) -> None:
        args = cli.build_parser().parse_args(["speak-test"])
        assert args.voice is None, "không ghi đè thì phải để from_config tự quyết"
        assert args.volume is None
        assert args.speed is None
        assert args.tone is False
        assert args.list is False

    @pytest.mark.parametrize("kind", _KINDS)
    def test_nhan_tung_kind(self, kind: str) -> None:
        args = cli.build_parser().parse_args(["speak-test", "--kind", kind])
        assert args.kind == kind

    def test_kind_la_bi_tu_choi(self) -> None:
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["speak-test", "--kind", "khong_co"])

    @pytest.mark.parametrize("voice", ("nam", "nu", "espeak"))
    def test_nhan_tung_giong(self, voice: str) -> None:
        args = cli.build_parser().parse_args(["speak-test", "--voice", voice])
        assert args.voice == voice

    def test_cac_co_thu_nghiem_deu_parse_duoc(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "speak-test",
                "--kind",
                "phone",
                "--voice",
                "nam",
                "--volume",
                "0.6",
                "--speed",
                "0.8",
                "--tone",
                "--list",
                "--log-level",
                "DEBUG",
            ]
        )
        assert args.kind == "phone"
        assert args.voice == "nam"
        assert args.volume == pytest.approx(0.6)
        assert args.speed == pytest.approx(0.8)
        assert args.tone is True
        assert args.list is True


# --------------------------------------------------------------------------
# Truyền tham số xuống alerter
# --------------------------------------------------------------------------
class TestTruyenThamSo:
    def test_mac_dinh_lay_tu_config(self, monkeypatch, config_file, capsys) -> None:
        """Không có cờ thì ``from_config`` **không** nhận kwarg ghi đè nào."""
        assert _run(monkeypatch, config_file) == 0
        _config, kwargs = FakeAlerter.last_from_config
        assert kwargs == {}, (
            "không được truyền cả giá trị mặc định: from_config phải đọc "
            f"config.yaml; nhận {kwargs!r}"
        )

    def test_ghi_de_ba_co_thi_truyen_xuong(self, monkeypatch, config_file) -> None:
        """``--voice``/``--volume``/``--speed`` phải có mặt trong kwarg."""
        assert (
            _run(
                monkeypatch,
                config_file,
                "--voice",
                "nam",
                "--volume",
                "0.6",
                "--speed",
                "0.8",
            )
            == 0
        )
        _config, kwargs = FakeAlerter.last_from_config
        assert kwargs["voice"] == "nam"
        assert kwargs["volume"] == pytest.approx(0.6)
        assert kwargs["speed"] == pytest.approx(0.8)

    def test_ghi_de_giong_khong_ghi_voice_json(
        self, monkeypatch, config_file, tmp_path: Path
    ) -> None:
        """``--voice`` chỉ có hiệu lực lần này: ``voice.json`` phải giữ nguyên.

        Lựa chọn trên dashboard thắng ``config.yaml`` vì nó được lưu xuống
        ``voice.json``. Nếu ``speak-test --voice`` cũng ghi file đó thì một
        lần nghe thử giọng nam sẽ **âm thầm đổi giọng thật** của cả hệ thống.
        """
        audio = tmp_path / "audio"
        audio.mkdir()
        voice_file = audio / "voice.json"
        voice_file.write_text('{"version": 1, "voice": "nu"}', encoding="utf-8")
        before = voice_file.read_text(encoding="utf-8")

        assert _run(monkeypatch, config_file, "--voice", "nam") == 0

        assert voice_file.read_text(encoding="utf-8") == before, (
            "speak-test --voice đã ghi đè lựa chọn giọng của người dùng"
        )
        assert json.loads(before)["voice"] == "nu"

    def test_ghi_de_toc_do_khong_ghi_voice_json(
        self, monkeypatch, config_file, tmp_path: Path
    ) -> None:
        """``--speed`` cũng chỉ có hiệu lực lần này (spec: ``voice.json`` chỉ giữ giọng)."""
        audio = tmp_path / "audio"
        audio.mkdir()
        voice_file = audio / "voice.json"
        voice_file.write_text('{"version": 1, "voice": "nu"}', encoding="utf-8")
        before = voice_file.read_text(encoding="utf-8")

        assert _run(monkeypatch, config_file, "--speed", "0.8") == 0

        assert voice_file.read_text(encoding="utf-8") == before


# --------------------------------------------------------------------------
# Mã thoát
# --------------------------------------------------------------------------
class TestMaThoat:
    def test_phat_du_ba_cau_tra_0(self, monkeypatch, config_file) -> None:
        assert _run(monkeypatch, config_file) == 0
        assert FakeAlerter.instances[-1].calls == list(_KINDS)

    def test_chi_phat_dung_kind_duoc_chon(self, monkeypatch, config_file) -> None:
        assert _run(monkeypatch, config_file, "--kind", "phone") == 0
        assert FakeAlerter.instances[-1].calls == ["phone"]

    def test_list_khong_phat_gi_va_tra_0(
        self, monkeypatch, config_file, capsys
    ) -> None:
        assert _run(monkeypatch, config_file, "--list") == 0
        assert FakeAlerter.instances[-1].calls == [], "--list không được phát"
        out = capsys.readouterr().out
        assert "GIỌNG ĐỌC ĐANG CÓ" in out
        # Phải hiện cả âm lượng lẫn tốc độ: người dùng cần biết đang nghe bản nào.
        assert "Âm lượng" in out
        assert "Tốc độ" in out

    def test_tone_dung_duong_bip_khong_dung_cau_noi(
        self, monkeypatch, config_file
    ) -> None:
        """``--tone`` phải gọi ``speak_tone_now``: đường này không cần ffmpeg."""
        assert _run(monkeypatch, config_file, "--tone") == 0
        alerter = FakeAlerter.instances[-1]
        assert alerter.calls == [], "không được phát câu nói ở chế độ bíp"
        assert alerter.tone_kinds == list(_KINDS)

    def test_thieu_loa_thi_ma_2_va_bao_ro(
        self, monkeypatch, config_file, capsys
    ) -> None:
        assert _run(monkeypatch, config_file, cls=UnavailableAlerter) == 2
        err = capsys.readouterr().err
        assert "camera.speaker" in err
        assert "Traceback" not in err

    def test_dung_loa_loi_thi_ma_2_va_bao_ro(
        self, monkeypatch, config_file, capsys
    ) -> None:
        assert _run(monkeypatch, config_file, cls=ExplodingAlerter) == 2
        err = capsys.readouterr().err
        assert "Không dựng được loa" in err
        assert "Traceback" not in err

    def test_config_khong_ton_tai_thi_ma_2(self, monkeypatch, tmp_path, capsys) -> None:
        _patch_alerter(monkeypatch)
        code = cli.main(["speak-test", "--config", str(tmp_path / "khong_co.yaml")])
        assert code == 2
        assert "Traceback" not in capsys.readouterr().err


# --------------------------------------------------------------------------
# Không đụng phần cứng khác
# --------------------------------------------------------------------------
def test_speak_test_khong_tao_phan_cung(monkeypatch, config_file) -> None:
    """Lệnh này không mở camera, không tạo GPIO, không gọi ``cmd_run``.

    Đó là điều kiện để nó chạy được **song song** với ``run`` — cách dùng
    chính: vòng lặp đang giám sát, người dùng mở terminal thứ hai để nghe thử.
    """
    import posture_monitor.hardware as hardware_pkg

    def _boom(*_args, **_kwargs):
        raise AssertionError("speak-test không được tạo phần cứng")

    monkeypatch.setattr(hardware_pkg, "create_hardware", _boom)
    monkeypatch.setattr(
        cli,
        "cmd_run",
        lambda _args: (_ for _ in ()).throw(
            AssertionError("speak-test không được gọi cmd_run")
        ),
    )

    assert _run(monkeypatch, config_file) == 0
