"""Hai nửa thật gặp nhau: ``create_app`` thật + ``PeopleService`` thật.

Các test cũ dựng route với một bản giả ``PeopleService`` do chính lớp web khai
báo. Bản giả đó luôn ném đúng lớp lỗi mà lớp web bắt, nên nó **không thể** phát
hiện hai lỗi nối dây dưới đây — chúng chỉ hiện ra khi hai nửa thật chạm nhau:

1. ``web/people_service.py`` từng định nghĩa một ``PeopleServiceError`` riêng,
   trong khi dịch vụ thật ném lớp ở ``posture_monitor.people_service``. Không
   phải cùng một lớp thì ``except`` không khớp: lỗi nghiệp vụ rơi vào nhánh
   ``except Exception`` và trả **503** thay vì **400**.
2. ``_people_call(people.signals)`` truyền một **thuộc tính**, nên nó được
   đánh giá *trước* khi vào ``try``; dịch vụ thiếu phương thức thì
   ``AttributeError`` thoát ra ngoài view và Flask trả **500 HTML**.

Vì vậy file này cố ý dùng ``create_app`` thật với
:class:`posture_monitor.people_service.PeopleService` thật. Chỉ ``recognizer``
là bản giả — nó không tham gia vào đường nối dây đang kiểm và nạp YuNet/SFace
sẽ cần model không có trên PC. Kho là :class:`FaceStore` thật trong ``tmp_path``.

Hai test ``/api/schedule`` trước đây khẳng định 503 vì dịch vụ thật **chưa có**
``get_schedule``/``put_schedule``. Sau khi nối hai nửa, chúng khẳng định đúng
hợp đồng thật: 200 JSON cho GET, 200/400 cho PUT.
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

from posture_monitor.faces import FaceStore  # noqa: E402
from posture_monitor.people_service import (  # noqa: E402
    PeopleService,
    PeopleServiceError,
)
from posture_monitor.web import DashboardState, create_app  # noqa: E402
from posture_monitor.web import people_service as web_people_module  # noqa: E402

#: Vector đơn vị 128 chiều, đúng hình dạng embedding thật.
BASE_VECTOR = np.ones(128, dtype=np.float32) / np.sqrt(128.0)


class FakeRecognizer:
    """Bản giả tối thiểu: không nạp model, mỗi khung trả cùng một vector."""

    def __init__(self, vector: np.ndarray | None = BASE_VECTOR) -> None:
        self.vector = vector
        self.calls = 0

    def embed_largest(self, _frame: object) -> np.ndarray | None:
        self.calls += 1
        return None if self.vector is None else np.array(self.vector)


def _real_service(tmp_path: Path) -> PeopleService:
    """Trả ``PeopleService`` **thật** — không phải bản giả của lớp web."""
    store = FaceStore(tmp_path, clock=lambda: 100.0)
    return PeopleService(store, FakeRecognizer(), clock=lambda: 100.0)


@pytest.fixture()
def client(tmp_path: Path):
    """Flask app thật, nhận dịch vụ thật (không fake dịch vụ)."""
    app = create_app(state=DashboardState(), people=_real_service(tmp_path))
    app.config.update(TESTING=True)
    return app.test_client()


# ---------------------------------------------------------------------------
# Lỗ hổng A: lỗi nghiệp vụ của dịch vụ thật phải thành 400, không phải 503
# ---------------------------------------------------------------------------
def test_web_dung_lai_dung_lop_loi_cua_dich_vu():
    """Lớp web phải dùng đúng lớp lỗi của dịch vụ, không định nghĩa lớp thứ hai."""
    assert web_people_module.PeopleServiceError is PeopleServiceError


def test_enroll_status_khong_ton_tai_tra_400(client):
    """``enroll_status`` ném ``PeopleServiceError`` thật → route trả 400 JSON.

    Trước khi nối, đây là 503: hai lớp lỗi khác nhau nên ``except`` bên view
    không khớp và lỗi rơi xuống nhánh "sự cố hệ thống".
    """
    response = client.get("/api/enroll/khong-ton-tai")

    assert response.status_code == 400, response.data
    payload = response.get_json()
    assert payload is not None, "phải là JSON, không phải trang HTML của Flask"
    assert "khong-ton-tai" in payload["message"]


# ---------------------------------------------------------------------------
# Lỗ hổng B: mọi lời gọi dịch vụ phải nằm trong ``try``
# ---------------------------------------------------------------------------
def test_signals_tra_200_voi_dich_vu_that(client):
    """``/api/signals`` gọi được phương thức của dịch vụ thật → 200 JSON."""
    response = client.get("/api/signals")

    assert response.status_code == 200, response.data
    payload = response.get_json()
    assert payload is not None, "phải là JSON, không phải trang HTML của Flask"
    assert set(payload) == {"presence", "phone", "identity"}
    # Chưa xử lý khung nào: tín hiệu phải tự khai "chưa có dữ liệu".
    assert payload["presence"]["fresh"] is False
    assert payload["identity"]["state"] == "UNKNOWN"
    # Quyền riêng tư: không vector nào rời khỏi tầng lưu trữ.
    body = response.get_data(as_text=True)
    assert "embedding" not in body
    assert "vector" not in body


def test_schedule_get_tra_200_json_voi_dich_vu_that(client):
    """``GET /api/schedule`` dùng ``get_schedule`` **thật** → 200 JSON.

    Đây là bất biến mà lỗ hổng B + lỗ hổng "thiếu phương thức" cùng vi phạm:
    thiếu phương thức thì lời gọi thuộc tính trần ném ``AttributeError``
    *trước* ``try`` và Flask trả 500 HTML. Nối xong thì phải là 200 JSON.
    """
    response = client.get("/api/schedule")

    assert response.status_code == 200, response.data
    payload = response.get_json()
    assert payload is not None, "phải là JSON, không phải trang HTML của Flask"
    assert payload["ok"] is True
    assert payload["schedule"]["enabled"] is False
    assert payload["schedule"]["windows"] == []
    assert set(payload["schedule"]["kinds"]) == {
        "leave_frame",
        "phone",
        "stranger",
    }


def test_schedule_put_hop_le_tra_200(client):
    """``PUT /api/schedule`` payload hợp lệ → 200 và cấu hình đổi thật."""
    new_schedule = {
        "enabled": True,
        "windows": [{"days": ["sat", "sun"], "start": "08:00", "end": "11:00"}],
    }
    response = client.put("/api/schedule", json=new_schedule)

    assert response.status_code == 200, response.data
    saved = response.get_json()["schedule"]
    assert saved["enabled"] is True
    assert saved["windows"] == new_schedule["windows"]
    # Đọc lại qua route khác: giá trị đã thực sự nằm trong dịch vụ.
    assert client.get("/api/schedule").get_json()["schedule"] == saved


def test_schedule_put_sai_tra_400(client):
    """Payload sai (bật giờ học mà không có khung) → 400 JSON, không phải 503."""
    response = client.put("/api/schedule", json={"enabled": True, "windows": []})

    assert response.status_code == 400, response.data
    payload = response.get_json()
    assert payload is not None, "phải là JSON, không phải trang HTML của Flask"
    assert "windows" in payload["message"]


class _ServiceThieuSignals(PeopleService):
    """``PeopleService`` thật nhưng cố ý không có thuộc tính ``signals``.

    Đây là cách duy nhất chứng minh lỗ hổng B **mà không phụ thuộc phiên bản
    dịch vụ**: khi ``signals`` tồn tại, cả ``_people_call(people.signals)``
    lẫn ``_people_call(lambda: people.signals())`` đều thành công, nên một
    test 200 không phân biệt được hai cách viết. Chỉ khi thuộc tính vắng mặt
    thì vị trí tra cứu mới lộ ra: trước ``try`` → 500 HTML, trong ``try`` →
    503 JSON.
    """

    #: Tên thuộc tính bị làm cho vắng mặt (lớp con đổi được).
    _missing = "signals"

    def __getattribute__(self, name: str):
        if name == object.__getattribute__(self, "_missing"):
            raise AttributeError(
                f"'PeopleService' object has no attribute '{name}'"
            )
        return super().__getattribute__(name)


class _ServiceThieuGetSchedule(_ServiceThieuSignals):
    """Như trên, nhưng vắng ``get_schedule`` — ca của route ``/api/schedule``."""

    _missing = "get_schedule"


def test_signals_thieu_phuong_thuc_tra_503_json_khong_phai_500_html(tmp_path):
    """Thiếu ``signals`` → 503 JSON; đổi lại thành thuộc tính trần là 500 HTML."""
    service = _ServiceThieuSignals(
        FaceStore(tmp_path, clock=lambda: 100.0),
        FakeRecognizer(),
        clock=lambda: 100.0,
    )
    app = create_app(state=DashboardState(), people=service)
    # Cố ý **không** bật ``TESTING``: chế độ đó cho exception thoát ra test
    # client, còn trình chạy thật thì trả trang 500 HTML. Ta muốn thấy đúng
    # hình dạng lỗi mà người dùng nhận.
    app.config.update(TESTING=False)

    response = app.test_client().get("/api/signals")

    assert response.status_code == 503, response.data
    payload = response.get_json()
    assert payload is not None, (
        "thuộc tính bị đánh giá ngoài try sẽ ném AttributeError ra view và "
        "Flask trả trang 500 HTML — đây chính là lỗi cần chặn"
    )
    assert payload["ok"] is False


def test_get_schedule_thieu_phuong_thuc_tra_503_json_khong_phai_500_html(
    tmp_path,
):
    """Thiếu ``get_schedule`` → 503 JSON, không phải 500 HTML.

    Cùng bất biến với ``/api/signals`` nhưng ở một view khác: mỗi lời gọi phải
    tự bọc ``lambda``. Sửa ``signals`` mà quên ``get_schedule`` thì test này đỏ.
    """
    service = _ServiceThieuGetSchedule(
        FaceStore(tmp_path, clock=lambda: 100.0),
        FakeRecognizer(),
        clock=lambda: 100.0,
    )
    app = create_app(state=DashboardState(), people=service)
    app.config.update(TESTING=False)

    response = app.test_client().get("/api/schedule")

    assert response.status_code == 503, response.data
    payload = response.get_json()
    assert payload is not None, (
        "truyền ``people.get_schedule`` (thuộc tính trần) khiến AttributeError "
        "nổ trước try và Flask trả trang 500 HTML"
    )
    assert payload["ok"] is False



def test_people_liet_ke_bang_dich_vu_that(client):
    """Đường nối cơ bản: danh sách người + người đang chọn qua dịch vụ thật."""
    response = client.get("/api/people")

    assert response.status_code == 200, response.data
    payload = response.get_json()
    assert payload == {"people": [], "selected": None}


# ---------------------------------------------------------------------------
# Lỗ hổng E: ``_Dashboard`` thật truyền dịch vụ thật vào ``create_app``
# ---------------------------------------------------------------------------
class _RecordingLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []

    def _fmt(self, fmt, args):
        return fmt % args if args else str(fmt)

    def warning(self, fmt, *args) -> None:
        self.warnings.append(self._fmt(fmt, args))

    def info(self, fmt, *args) -> None:
        self.infos.append(self._fmt(fmt, args))

    def error(self, fmt, *args) -> None:
        self.errors.append(self._fmt(fmt, args))

    def exception(self, fmt, *args) -> None:
        self.errors.append(self._fmt(fmt, args))


def test_dashboard_that_truyen_dich_vu_nguoi_hoc_vao_create_app(
    monkeypatch, tmp_path
):
    """``_Dashboard`` **thật** phải tạo ``PeopleService`` và truyền ``people=``.

    Trước khi nối, ``create_app`` luôn nhận ``people=None`` nên cả chín route
    người học trả 503 trên ứng dụng thật, dù test route dùng bản giả vẫn xanh.
    """
    import posture_monitor.__main__ as cli
    import posture_monitor.web as web_mod

    config = cli.load_config("config.yaml")
    # ``face.enabled`` mặc định false (chưa đo ngưỡng); bật lên để dịch vụ
    # được dựng. Ngưỡng None là hợp lệ — mọi quan sát sẽ là UNKNOWN.
    config.face.enabled = True
    config.storage.db_path = str(tmp_path / "posture.db")
    config.face.store_path = str(tmp_path / "data" / "faces.json")

    captured: dict[str, object] = {}
    real_create_app = web_mod.create_app

    def spy_create_app(cfg, **kwargs):
        captured["kwargs"] = kwargs
        return real_create_app(cfg, **kwargs)

    monkeypatch.setattr(web_mod, "create_app", spy_create_app)

    dashboard = cli._Dashboard(config, _RecordingLogger())
    try:
        assert captured["kwargs"]["people"] is not None, (
            "create_app phải nhận dịch vụ người học thật, không phải None"
        )
        assert captured["kwargs"]["people"] is dashboard.people
        assert isinstance(dashboard.people, PeopleService)
        # Route người học trên app thật trả dữ liệu thật, không phải 503.
        response = dashboard.app.test_client().get("/api/schedule")
        assert response.status_code == 200, response.data
    finally:
        dashboard.storage.close()
        dashboard.people.close()


# ---------------------------------------------------------------------------
# Lỗ hổng F: lỗi của module mới không được giết vòng lặp giám sát
# ---------------------------------------------------------------------------
class _BoomPeople:
    """Dịch vụ giả: lời gọi ``observe`` nào cũng ném ``RuntimeError``."""

    def __init__(self) -> None:
        self.observe_calls = 0

    def update_signals(self, **_kwargs) -> None:
        pass

    def observe(self, _frame, _now) -> None:
        self.observe_calls += 1
        raise RuntimeError("module mới hỏng")


class _FakeSource:
    backend = "fake"

    def __init__(self, frames: int = 1) -> None:
        self.frames_left = frames
        self.closed = False

    def read(self):
        if self.frames_left <= 0:
            return None
        self.frames_left -= 1
        return np.zeros((48, 64, 3), dtype=np.uint8)

    def close(self) -> None:
        self.closed = True


class _FakeEstimator:
    backend = "fake"

    def detect(self, _frame):
        return None

    @property
    def last_person_count(self) -> int:
        return 0


def test_vong_loop_song_sot_khi_module_nguoi_hoc_nem_loi(
    monkeypatch, tmp_path
):
    """``observe`` ném ``RuntimeError`` → ``_monitor_loop`` vẫn kết thúc sạch.

    Yêu cầu cứng: tính năng mới không được làm chết camera. Lỗi phải được
    đếm/ghi log, không ném ra ngoài.
    """
    import posture_monitor.__main__ as cli
    import posture_monitor.calibration as calibration_mod
    from posture_monitor.calibration import Baseline
    from posture_monitor.config import Config, StorageConfig
    from posture_monitor.features import ALL_NAMES

    config = Config()
    config.storage = StorageConfig(db_path=str(tmp_path / "posture.db"))

    monkeypatch.setattr(
        calibration_mod,
        "load",
        lambda _path: Baseline(
            values={name: None for name in ALL_NAMES},
            view="front",
            width=640,
            height=480,
            created_at="",
            frames=0,
        ),
    )
    monkeypatch.setattr(cli.cv2, "namedWindow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "imshow", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "destroyAllWindows", lambda *a, **k: None)
    monkeypatch.setattr(cli.cv2, "getWindowProperty", lambda *a, **k: 1.0)
    monkeypatch.setattr(cli.cv2, "waitKey", lambda *a, **k: ord("q"))

    people = _BoomPeople()
    logger = _RecordingLogger()

    exit_code = cli._monitor_loop(
        _FakeEstimator(),
        _FakeSource(frames=1),
        config,
        logger,
        people=people,
    )

    assert exit_code == 0, "lỗi module mới không được đổi mã thoát"
    assert people.observe_calls == 1
    joined = " ".join(logger.warnings)
    assert "người học" in joined and "module mới hỏng" in joined, (
        "lỗi phải được ghi log, không bị nuốt im lặng"
    )
