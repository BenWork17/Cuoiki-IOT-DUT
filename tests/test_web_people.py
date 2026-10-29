"""Route + giao diện "người học" của dashboard (spec v3 §5.13, §5.16, §8.3).

Không cần camera, không cần mạng và **không** cần model nhận diện: mọi thứ đi
qua một bản giả :class:`PeopleService` tiêm vào ``create_app(people=...)``.
Đây cũng chính là ranh giới hợp đồng — lớp web chỉ biết đúng các phương thức
trong ``protocol``, không tự đọc khuôn mặt.

Ba nhóm kiểm tra:

1. **Hợp đồng route** — 8 route mới: thành công, lỗi nghiệp vụ → 400, lỗi hệ
   thống → 503, và ``people=None`` → 503 với thông điệp tiếng Việt.
2. **Quyền riêng tư** — không phản hồi nào chứa ``embedding``/``vector``
   (§8.3 "không route nào trả vector"), kể cả khi dịch vụ lỡ trả kèm.
3. **Giao diện** — trang chủ có nút/khung cần thiết, không còn thẻ "Tư thế",
   và app.js có nhánh xử lý ``fresh=false`` (chống hiểu nhầm theo §5.16).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from posture_monitor.web import (  # noqa: E402
    ENROLL_STEPS,
    DashboardState,
    PeopleServiceError,
    create_app,
)

_TEMPLATE = (
    _REPO_ROOT / "src" / "posture_monitor" / "web" / "templates" / "index.html"
)
_APP_JS = _REPO_ROOT / "src" / "posture_monitor" / "web" / "static" / "app.js"


# ---------------------------------------------------------------------------
# Bản giả dịch vụ người học
# ---------------------------------------------------------------------------
class FakePeople:
    """Bản giả tối thiểu của :class:`PeopleService`, thuần trong bộ nhớ.

    Cố ý **có** trường ``embedding`` trong dữ liệu người và trong tín hiệu
    danh tính: đó là cách chứng minh lớp web lọc dữ liệu sinh trắc học chứ
    không phụ thuộc vào lời hứa của dịch vụ. Bản thật cũng không được trả
    trường này, nhưng test phải bắt được một lần nối dây lơ đãng.
    """

    def __init__(self) -> None:
        self.people = [
            {
                "id": "p1",
                "name": "Minh",
                "created_ts": 1700000000.0,
                "embedding": [0.1] * 4,
            }
        ]
        self.selected = None
        self.enrolls: dict[str, dict] = {}
        self.cancelled: list[str] = []
        self.deleted: list[str] = []
        self.schedule = {
            "enabled": True,
            "windows": [{"days": ["mon", "tue"], "start": "19:00", "end": "21:30"}],
        }
        self.signal_state = {
            "presence": {
                "state": "present",
                "age_s": 0.4,
                "age_limit_s": 2.0,
                "fresh": True,
            },
            "phone": {
                "state": "none",
                "age_s": 1.1,
                "age_limit_s": 2.0,
                "fresh": True,
            },
            "identity": {
                "state": "MATCH",
                "name": "Minh",
                "age_s": 3.2,
                "age_limit_s": 2.5,
                "fresh": False,
                "embedding": [0.9, 0.8],
            },
        }
        self.fail_with: Exception | None = None

    def _maybe_fail(self):
        if self.fail_with is not None:
            raise self.fail_with

    def list_people(self) -> list[dict]:
        self._maybe_fail()
        return [dict(item) for item in self.people]

    def start_enroll(self, name: str) -> dict:
        self._maybe_fail()
        if not name:
            raise PeopleServiceError("Tên người học không được để trống.")
        enroll_id = f"e{len(self.enrolls) + 1}"
        self.enrolls[enroll_id] = {
            "state": "running",
            "step_index": 0,
            "step_name": ENROLL_STEPS[0],
            "samples": 0,
            "samples_needed": 3,
            "error": None,
        }
        return {"enroll_id": enroll_id, "steps": list(ENROLL_STEPS)}

    def enroll_status(self, enroll_id: str) -> dict:
        self._maybe_fail()
        if enroll_id not in self.enrolls:
            raise PeopleServiceError(f"Không có phiên đăng ký {enroll_id!r}.")
        return dict(self.enrolls[enroll_id])

    def cancel_enroll(self, enroll_id: str) -> bool:
        self._maybe_fail()
        if enroll_id not in self.enrolls:
            return False
        self.enrolls[enroll_id]["state"] = "cancelled"
        self.cancelled.append(enroll_id)
        return True

    def delete_person(self, person_id: str) -> bool:
        self._maybe_fail()
        for index, person in enumerate(self.people):
            if person["id"] == person_id:
                del self.people[index]
                self.deleted.append(person_id)
                return True
        return False

    def select_person(self, person_id):
        self._maybe_fail()
        if person_id is None:
            self.selected = None
            return True
        if not any(person["id"] == person_id for person in self.people):
            return False
        self.selected = person_id
        return True

    def selected_person(self):
        return self.selected

    def signals(self) -> dict:
        self._maybe_fail()
        return json.loads(json.dumps(self.signal_state))

    def get_schedule(self) -> dict:
        self._maybe_fail()
        return dict(self.schedule)

    def put_schedule(self, payload: dict) -> dict:
        self._maybe_fail()
        if not isinstance(payload.get("windows"), list):
            raise PeopleServiceError("'windows' phải là danh sách khung giờ.")
        self.schedule = dict(payload)
        return dict(self.schedule)


@pytest.fixture()
def people() -> FakePeople:
    return FakePeople()


@pytest.fixture()
def client(people):
    app = create_app(state=DashboardState(), people=people)
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture()
def disabled_client():
    app = create_app(state=DashboardState())
    app.config.update(TESTING=True)
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /api/people
# ---------------------------------------------------------------------------
def test_api_people_liet_ke_va_nguoi_dang_chon(client):
    response = client.get("/api/people")
    assert response.status_code == 200
    payload = response.get_json()
    assert [person["name"] for person in payload["people"]] == ["Minh"]
    assert payload["selected"] is None


def test_api_people_khong_tra_embedding(client):
    """§8.3: không route nào trả vector, kể cả khi dịch vụ lỡ trả kèm."""
    payload = client.get("/api/people").get_json()
    person = payload["people"][0]
    assert set(person) == {"id", "name", "created_ts"}
    assert "embedding" not in json.dumps(payload)


# ---------------------------------------------------------------------------
# POST /api/people
# ---------------------------------------------------------------------------
def test_api_people_them_nguoi_tra_201_va_nam_buoc(client, people):
    response = client.post("/api/people", json={"name": "Lan"})
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["enroll_id"] == "e1"
    assert payload["steps"] == list(ENROLL_STEPS)
    assert payload["steps"] == [
        "Nhìn thẳng",
        "Quay sang phải",
        "Quay sang trái",
        "Ngẩng lên",
        "Cúi xuống",
    ]
    assert people.enrolls["e1"]["state"] == "running"


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}, {"name": 5},
                                  {"ten": "Minh"}])
def test_api_people_thieu_hoac_rong_ten_tra_400(client, body):
    response = client.post("/api/people", json=body)
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "tên" in payload["message"].lower()


class PermissivePeople(FakePeople):
    """Dịch vụ chấp nhận *mọi* tên, kể cả rỗng.

    Dùng để chứng minh route **tự** chặn tên rỗng, chứ không phải may nhờ bản
    giả cũng chặn: nếu chỉ dựa vào dịch vụ thì bỏ kiểm tra ở route vẫn xanh.
    """

    def start_enroll(self, name: str) -> dict:
        return {"enroll_id": "e-x", "steps": list(ENROLL_STEPS)}


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}])
def test_api_people_tu_chan_ten_rong_du_dich_vu_de_dai(body):
    app = create_app(state=DashboardState(), people=PermissivePeople())
    app.config.update(TESTING=True)
    response = app.test_client().post("/api/people", json=body)
    assert response.status_code == 400, (
        "route phải tự từ chối tên rỗng, không phó mặc cho dịch vụ"
    )
    assert "tên" in response.get_json()["message"].lower()


def test_api_people_than_khong_phai_json_tra_400(client):
    response = client.post(
        "/api/people", data="khong-phai-json", content_type="text/plain"
    )
    assert response.status_code == 400


def test_api_people_loi_nghiep_vu_tra_400(client, people):
    people.fail_with = PeopleServiceError("Tên này đã có người dùng.")
    response = client.post("/api/people", json={"name": "Minh"})
    assert response.status_code == 400
    assert response.get_json()["message"] == "Tên này đã có người dùng."


def test_api_people_loi_he_thong_tra_503_khong_lo_traceback(client, people):
    people.fail_with = RuntimeError("mất kết nối CSDL bí mật")
    response = client.post("/api/people", json={"name": "Minh"})
    assert response.status_code == 503
    payload = response.get_json()
    assert payload["ok"] is False
    assert "Traceback" not in payload["message"]
    assert "bí mật" not in payload["message"]


# ---------------------------------------------------------------------------
# DELETE /api/people/<id>
# ---------------------------------------------------------------------------
def test_api_people_xoa_thanh_cong(client, people):
    response = client.delete("/api/people/p1")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert people.deleted == ["p1"]
    assert client.get("/api/people").get_json()["people"] == []


def test_api_people_xoa_id_khong_ton_tai_tra_404(client):
    response = client.delete("/api/people/khong-co")
    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# Đăng ký: trạng thái + huỷ
# ---------------------------------------------------------------------------
def test_api_enroll_trang_thai_va_huy(client, people):
    enroll_id = client.post("/api/people", json={"name": "Lan"}).get_json()[
        "enroll_id"
    ]
    progress = client.get(f"/api/enroll/{enroll_id}").get_json()
    assert progress["state"] == "running"
    assert progress["step_name"] == "Nhìn thẳng"
    assert progress["samples_needed"] == 3

    people.enrolls[enroll_id].update(
        state="done", step_index=4, step_name="Cúi xuống", samples=3
    )
    done = client.get(f"/api/enroll/{enroll_id}").get_json()
    assert done["state"] == "done"
    assert done["samples"] == 3

    cancel = client.post(f"/api/enroll/{enroll_id}/cancel")
    assert cancel.status_code == 200
    assert people.cancelled == [enroll_id]


def test_api_enroll_id_la_tra_400(client):
    response = client.get("/api/enroll/khong-co")
    assert response.status_code == 400
    assert "không có phiên" in response.get_json()["message"].lower()


def test_api_enroll_huy_id_la_tra_404(client):
    response = client.post("/api/enroll/khong-co/cancel")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/select
# ---------------------------------------------------------------------------
def test_api_select_chon_va_bo_chon(client):
    chosen = client.post("/api/select", json={"person_id": "p1"})
    assert chosen.status_code == 200
    assert chosen.get_json()["selected"] == "p1"
    assert client.get("/api/people").get_json()["selected"] == "p1"

    cleared = client.post("/api/select", json={"person_id": None})
    assert cleared.status_code == 200
    assert cleared.get_json()["selected"] is None
    assert client.get("/api/people").get_json()["selected"] is None


def test_api_select_id_khong_ton_tai_tra_404(client):
    response = client.post("/api/select", json={"person_id": "khong-co"})
    assert response.status_code == 404


def test_api_select_thieu_khoa_tra_400(client):
    response = client.post("/api/select", json={})
    assert response.status_code == 400
    assert "person_id" in response.get_json()["message"]


# ---------------------------------------------------------------------------
# GET /api/signals
# ---------------------------------------------------------------------------
def test_api_signals_tra_ba_tin_hieu_kem_tuoi(client):
    payload = client.get("/api/signals").get_json()
    assert set(payload) == {"presence", "phone", "identity"}
    for kind in ("presence", "phone", "identity"):
        signal = payload[kind]
        assert set(signal) >= {"state", "age_s", "age_limit_s", "fresh"}
    assert payload["identity"]["state"] == "MATCH"
    assert payload["identity"]["name"] == "Minh"


def test_api_signals_khong_ro_embedding(client):
    payload = client.get("/api/signals").get_json()
    assert "embedding" not in json.dumps(payload)


def test_api_signals_phan_biet_moi_va_cu(client, people):
    """``fresh`` là dữ liệu thật sự khác nhau, không phải hằng số."""
    payload = client.get("/api/signals").get_json()
    assert payload["presence"]["fresh"] is True
    assert payload["identity"]["fresh"] is False

    people.signal_state["presence"]["fresh"] = False
    payload = client.get("/api/signals").get_json()
    assert payload["presence"]["fresh"] is False


def test_api_signals_loi_he_thong_tra_503(client, people):
    people.fail_with = RuntimeError("worker chết")
    response = client.get("/api/signals")
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET/PUT /api/schedule
# ---------------------------------------------------------------------------
def test_api_schedule_doc_va_ghi(client, people):
    before = client.get("/api/schedule").get_json()
    assert before["ok"] is True
    assert before["schedule"]["windows"][0]["start"] == "19:00"

    new_schedule = {
        "enabled": True,
        "windows": [{"days": ["sat"], "start": "08:00", "end": "11:00"}],
    }
    written = client.put("/api/schedule", json=new_schedule)
    assert written.status_code == 200
    assert written.get_json()["schedule"] == new_schedule
    assert people.schedule == new_schedule


def test_api_schedule_put_sai_tra_400(client):
    response = client.put("/api/schedule", json={"enabled": True})
    assert response.status_code == 400
    assert "windows" in response.get_json()["message"]


def test_api_schedule_put_than_sai_kieu_tra_400(client):
    response = client.put(
        "/api/schedule", data="[]", content_type="application/json"
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# people=None: 503 với thông điệp tiếng Việt, trang chủ vẫn render
# ---------------------------------------------------------------------------
ROUTES_NEEDING_PEOPLE = [
    ("get", "/api/people"),
    ("post", "/api/people"),
    ("delete", "/api/people/p1"),
    ("get", "/api/enroll/e1"),
    ("post", "/api/enroll/e1/cancel"),
    ("post", "/api/select"),
    ("get", "/api/schedule"),
    ("put", "/api/schedule"),
    ("get", "/api/signals"),
]


@pytest.mark.parametrize("method,path", ROUTES_NEEDING_PEOPLE)
def test_route_nguoi_hoc_khi_chua_noi_day_tra_503(disabled_client, method, path):
    response = getattr(disabled_client, method)(path)
    assert response.status_code == 503, f"{method.upper()} {path}"
    payload = response.get_json()
    assert payload["ok"] is False
    assert "chưa được bật" in payload["message"]
    assert "Tính năng người học" in payload["message"]


def test_trang_chu_van_render_khi_chua_noi_day(disabled_client):
    response = disabled_client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Trạng thái học" in html
    assert "Tính năng người học chưa được bật" in html
    # Khối điều khiển không hiện ra như bấm được khi tính năng đang tắt.
    assert 'id="add-person-btn"' not in html


# ---------------------------------------------------------------------------
# Giao diện
# ---------------------------------------------------------------------------
def test_trang_chu_co_nut_nguoi_hoc(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="add-person-btn"' in html
    assert 'id="pick-person-btn"' in html
    assert "Thêm người" in html
    assert "Chọn người đang học" in html
    assert 'id="new-person-name"' in html
    assert 'id="enroll-panel"' in html
    assert 'id="enroll-cancel-btn"' in html
    assert 'id="schedule-summary"' in html


def test_trang_chu_giu_bon_nut_ptz_va_camera(client):
    html = client.get("/").get_data(as_text=True)
    found = set(re.findall(r'data-ptz-direction="([^"]+)"', html))
    assert found == {"left", "right", "up", "down"}

    stream_client = create_app(
        config=_stream_config(), state=DashboardState(), people=None
    ).test_client()
    stream_html = stream_client.get("/").get_data(as_text=True)
    assert 'id="camera-stream"' in stream_html


def test_trang_chu_khong_con_the_tu_the_va_bieu_do(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="chart"' not in html
    assert "<canvas" not in html
    assert "Tỉ lệ tư thế đúng" not in html
    assert 'id="status-text"' not in html


def test_trang_chu_khong_co_anh_tro_toi_api_ngoai_stream(client):
    html = client.get("/").get_data(as_text=True)
    sources = re.findall(r'<img[^>]*\ssrc="([^"]+)"', html)
    for src in sources:
        assert src.startswith("/stream"), f"<img> trỏ ra ngoài /stream: {src}"


def test_app_js_khong_luu_du_lieu_nguoi_vao_localstorage():
    script = _APP_JS.read_text(encoding="utf-8")
    # Soát lời gọi đọc/ghi cụ thể, không soát chữ trong chú thích: chú thích
    # nhắc tên localStorage để giải thích vì sao không dùng.
    for api in ("localStorage", "sessionStorage"):
        for method in ("getItem", "setItem", "removeItem", "clear"):
            assert f"{api}.{method}" not in script, f"app.js gọi {api}.{method}"


def test_app_js_co_nhanh_du_lieu_cu_cho_tin_hieu():
    """§5.16: tín hiệu cũ phải nói "chưa có dữ liệu mới", không lặp kết luận cũ.

    Test tĩnh: app.js là file thuần, không có bộ chạy JS trong bộ test này,
    nên khẳng định *nhánh mã tồn tại* ở đúng chỗ cùng với câu chữ đó. Không
    chạy được thì ghi rõ đây là kiểm tra tĩnh trong báo cáo.
    """
    script = _APP_JS.read_text(encoding="utf-8")

    # Câu chữ bắt buộc phải có, và phải là hằng số dùng lại được.
    assert 'NO_FRESH_TEXT = "Chưa có dữ liệu mới"' in script

    # Trong hàm quyết định chữ của một dòng tín hiệu, nhánh ``fresh`` phải
    # đứng TRƯỚC mọi lần tra bảng kết luận.
    func_start = script.index("function signalPresentation")
    func_end = script.index("\n  }", func_start)
    body = script[func_start:func_end]

    fresh_guard = body.index("if (data.fresh !== true)")
    first_lookup = body.index("PRESENCE_TEXT")
    assert fresh_guard < first_lookup, (
        "nhánh dữ liệu cũ phải đứng trước mọi lần tra kết luận"
    )

    branch = body[fresh_guard : body.index("}", fresh_guard)]
    assert "NO_FRESH_TEXT" in branch, (
        f"nhánh fresh !== true không dùng NO_FRESH_TEXT; thực tế: {branch!r}"
    )


def test_app_js_tra_bang_theo_dung_gia_tri_server_gui():
    """Khoá tra bảng phải là giá trị server thật, không phải tên CSS.

    Server gửi ``co_mat``/``vang_mat`` (``presence.STATE_PRESENT``/
    ``STATE_ABSENT`` qua ``_presence_state``) và phone là ``dung``/
    ``khong_dung``. Bản cũ tra ``present``/``absent`` nên ``grep -c co_mat
    app.js`` = 0 và dòng "Có mặt" không bao giờ hiện đúng — một lỗi im lặng
    vì nó chỉ hiện "Chưa rõ" chứ không ném lỗi.

    Test tĩnh (không có bộ chạy JS trong bộ test này): đọc file và soát các
    khoá của bảng nhãn. Ghi rõ đây là kiểm tra tĩnh trong báo cáo.
    """
    from posture_monitor import presence as presence_mod

    script = _APP_JS.read_text(encoding="utf-8")

    # Mọi giá trị server-lived phải xuất hiện làm khoá bảng nhãn.
    for state in (presence_mod.STATE_PRESENT, presence_mod.STATE_ABSENT):
        assert f'"{state}"' in script, (
            f"app.js không có khoá {state!r} trong bảng nhãn presence; "
            "server gửi giá trị này nên dòng sẽ luôn hiện sai"
        )
    for state in ("dung", "khong_dung"):
        assert f'"{state}"' in script, f"app.js không có khoá phone {state!r}"

    # Khoá CSS cũ chỉ được là *giá trị* của bảng trạng thái, không được là
    # khoá tra bảng nhãn.
    for stale in ("present", "absent"):
        assert f"{stale}:" not in script.split("PRESENCE_STATE")[0], (
            f"app.js vẫn tra bảng presence bằng khoá cũ {stale!r}"
        )


def test_app_js_hop_dong_khoa_voi_hang_so_that_cua_people_service():
    """Khoá phone trong ``app.js`` phải khớp hằng số trong ``people_service``.

    Ràng buộc chéo hai file: đổi tên hằng ở server mà quên ``app.js`` thì
    dashboard im lặng hiện "Chưa rõ" thay vì "Đang dùng" — đúng loại lỗi mà
    brief này sửa. So trực tiếp hai nguồn.
    """
    from posture_monitor import people_service as people_mod

    script = _APP_JS.read_text(encoding="utf-8")
    for name in ("PHONE_STATE_NONE", "PHONE_STATE_USE"):
        value = getattr(people_mod, name)
        assert f'"{value}"' in script, (
            f"app.js thiếu khoá {value!r} ({name} của people_service) — "
            "hai nguồn đã lệch nhau"
        )


def test_app_js_gia_tri_la_thi_hien_gia_tri_tho_khong_im_lang():
    """Giá trị lạ phải hiện nguyên văn, không bị nuốt thành "Chưa rõ" trần.

    Im lặng thay bằng "Chưa rõ" làm một giá trị mới của server (hoặc lỗi đánh
    máy) trông y hệt "chưa đo được", nên không ai biết để sửa. Hàm dự phòng
    phải nhận chính giá trị đó làm tham số và chèn nó vào câu chữ.
    """
    script = _APP_JS.read_text(encoding="utf-8")

    assert "function unknownText(rawState)" in script, (
        "thiếu hàm dự phòng unknownText"
    )
    body_start = script.index("function unknownText(rawState)")
    body = script[body_start : body_start + 700]
    assert "String(rawState)" in body, (
        "hàm dự phòng không đọc giá trị thô, nên không thể hiện nó"
    )

    # Các nhánh tra bảng phải gọi hàm này thay vì trả nhãn cố định.
    func_start = script.index("function signalPresentation")
    func_body = script[func_start : script.index("\n  }", func_start)]
    assert "unknownText(" in func_body, (
        "signalPresentation không dùng nhãn dự phòng cho giá trị lạ"
    )
    assert func_body.count('"Chưa rõ"') == 0, (
        "còn nhánh trả thẳng \"Chưa rõ\", nuốt mất giá trị thật"
    )


def test_template_co_cho_hien_tuoi_tin_hieu(client):
    html = client.get("/").get_data(as_text=True)
    for kind in ("presence", "phone", "identity"):
        assert f'data-sign="{kind}"' in html
        assert f'id="sign-{kind}-age"' in html


def _stream_config():
    from posture_monitor.config import Config, WebConfig

    config = Config()
    config.web = WebConfig(host="127.0.0.1", port=8000, stream_enabled=True)
    return config
