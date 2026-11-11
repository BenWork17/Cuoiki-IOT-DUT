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
_CSS = _REPO_ROOT / "src" / "posture_monitor" / "web" / "static" / "style.css"


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


# ---------------------------------------------------------------------------
# Hộp quét khuôn mặt kiểu Face ID (yêu cầu: thêm người phải quét mặt, sai thì
# quét lại)
# ---------------------------------------------------------------------------
def test_trang_chu_co_hop_quet_khuon_mat_day_du(client):
    """Hộp quét phải có đủ mọi mẩu mà app.js bám vào để vẽ tiến độ."""
    html = client.get("/").get_data(as_text=True)
    for element_id in (
        "scan",
        "scan-viewport",
        "scan-progress",
        "scan-badge",
        "scan-steps",
        "scan-hint",
        "enroll-step",
        "enroll-samples",
        "enroll-name",
        "enroll-panel",
        "enroll-cancel-btn",
        "scan-retry-btn",
        "scan-close-btn",
    ):
        assert f'id="{element_id}"' in html, f"hộp quét thiếu #{element_id}"


def test_hop_quet_can_giua_bang_lop_phu_kin_man_hinh(client):
    """Hộp quét phải là lớp phủ toàn màn hình, không phải một thẻ trong trang.

    Một hộp nằm trong luồng tài liệu sẽ bị đẩy xuống dưới các thẻ khác, và
    người dùng phải cuộn mới thấy — trong khi nó đang chờ họ đưa mặt vào.
    """
    html = client.get("/").get_data(as_text=True)
    assert 'class="scan"' in html
    css = client.get("/static/style.css").get_data(as_text=True)
    rule = css.split(".sheet,\n.scan {", 1)
    assert len(rule) == 2, "không tìm thấy luật bố cục chung của hộp nổi"
    block = rule[1].split("}", 1)[0]
    assert "position: fixed" in block, "hộp nổi không cố định trên khung nhìn"
    assert "inset: 0" in block, "hộp nổi không phủ kín khung nhìn"


def test_nut_quet_lai_an_cho_toi_khi_quet_that_bai(client):
    """Nút "Quét lại" phải có sẵn trong HTML nhưng ẩn: nó là lối thoát khi
    quét sai, và không được hiện khi chưa có gì để quét lại."""
    html = client.get("/").get_data(as_text=True)
    start = html.index('id="scan-retry-btn"')
    tag = html[start : html.index(">", start)]
    assert "hidden" in tag, f"nút Quét lại phải ẩn sẵn; thẻ thật: {tag!r}"


def test_app_js_quet_lai_tao_phien_dang_ky_moi():
    """§5.13 + yêu cầu "quét sai thì quét lại": bấm Quét lại phải mở một phiên
    MỚI ở máy chủ.

    Chỉ gọi lại ``pollEnroll`` sẽ hỏi mãi một phiên đã ``failed``: máy chủ không
    bao giờ chuyển nó về ``running``, nên hộp quét đứng im ở "quét không đạt"
    dù người dùng đã làm đúng. Test soát đúng nhánh đó.
    """
    script = _APP_JS.read_text(encoding="utf-8")

    anchor = script.index('els.scanRetry.addEventListener("click"')
    # Cắt tới cuối khối đăng ký listener (dấu ``});`` đầu tiên ở cùng mức).
    body = script[anchor : anchor + 400]
    assert "startEnroll(" in body, (
        "Quét lại không mở phiên mới; phiên cũ đã failed nên sẽ không bao giờ "
        f"chạy lại. Thân thật: {body[:200]!r}"
    )


def test_app_js_bao_ket_qua_quet_xong_va_quet_khong_dat():
    """Ba trạng thái của hộp quét phải có chữ riêng, không dùng chung một câu.

    "Đã quét xong" và "Quét không đạt" là hai kết luận trái ngược; dùng một
    nhãn cho cả hai thì người dùng không biết đã đăng ký được chưa.
    """
    script = _APP_JS.read_text(encoding="utf-8")
    assert 'data-state' in script or "dataset.state" in script
    assert "Đã quét xong" in script
    assert "Quét không đạt" in script

    # Hàm đổi trạng thái phải đặt cả ``data-state`` cho CSS và nhãn chữ, để
    # màu và chữ luôn khớp nhau.
    start = script.index("function setScanState(")
    body = script[start : script.index("\n  }", start)]
    assert "dataset.state" in body, "setScanState không đặt data-state"
    assert "scanBadge" in body, "setScanState không đổi nhãn chữ"


def test_app_js_khong_dong_hop_quet_khi_bam_ra_ngoai():
    """Bấm trượt ra ngoài không được huỷ phiên đang quét.

    Trên điện thoại, một cú chạm trượt là chuyện thường; nếu nó đóng hộp thì
    người dùng mất luôn lần đăng ký đang chạy giữa chừng. Hai hộp kia (nhập
    tên, chọn người) thì đóng được vì không giữ trạng thái gì.
    """
    script = _APP_JS.read_text(encoding="utf-8")
    start = script.index("[els.addSheet, els.pickSheet].forEach")
    body = script[start : script.index("});", start)]
    assert "els.scan" not in body, (
        "hộp quét bị đưa vào danh sách đóng-khi-bấm-ra-ngoài"
    )


def test_app_js_khong_con_cham_dang_quet_khi_phien_dung():
    """Xong hoặc hỏng thì không chấm nào còn là "bước đang làm".

    Chấm xanh của bước hiện tại chỉ có nghĩa khi hệ thống còn quét. Để nó lại
    trên màn hình "Quét không đạt" là câu trả lời sai: mắt đọc thành "vẫn đang
    chạy" trong khi máy chủ đã dừng phiên.
    """
    script = _APP_JS.read_text(encoding="utf-8")
    assert "function markStepsStopped()" in script, (
        "thiếu hàm bỏ dấu bước-đang-làm khi phiên dừng"
    )
    start = script.index("function markStepsStopped()")
    body = script[start : script.index("\n  }", start)]
    assert 'dataset.current = "0"' in body, (
        "markStepsStopped không xoá dấu bước đang làm"
    )

    # Nhánh thất bại phải gọi nó, nếu không hàm này chỉ là mã chết.
    fail_start = script.index('if (state === "failed") {')
    fail_body = script[fail_start : fail_start + 700]
    assert "markStepsStopped()" in fail_body, (
        "nhánh quét không đạt không bỏ dấu bước đang làm"
    )


def test_app_js_khong_cho_man_hinh_khung_dau_tien():
    """Luồng MJPEG không bao giờ kết thúc nên ``load`` có thể không bắn.

    Đã gặp thật khi chạy trên laptop: server trả khung 704x576 đúng, ảnh đã
    tải xong (``naturalWidth = 704``), nhưng trang vẫn đứng ở "Đang kết nối
    tới camera…" vì ``hidden`` chỉ được bỏ trong handler ``load`` — mà Chromium
    không bắn ``load`` cho một response không bao giờ đóng. Phải có đường kiểm
    tra theo nhịp dựa trên ``naturalWidth``.
    """
    script = _APP_JS.read_text(encoding="utf-8")

    start = script.index("function setupCamera()")
    body = script[start : script.index("\n  }\n", start)]

    # Phải có một bộ đếm thật sự chạy (không bị vô hiệu hoá) và nó phải được
    # gán cho một biến để còn xoá được khi khung tới.
    assert "window.setInterval(" in body, (
        "setupCamera không có đường chờ khung đầu tiên; trang sẽ đứng ở "
        "'Đang kết nối tới camera…' khi MJPEG không bắn load"
    )
    assert "0 &&" not in body, "bộ đếm chờ khung bị vô hiệu hoá"
    assert "clearInterval(" in body, (
        "bộ đếm chờ khung không được xoá sau khi khung tới; nó sẽ chạy suốt "
        "thời gian trang mở"
    )
    assert "naturalWidth" in body, (
        "đường chờ không dựa trên naturalWidth nên không biết khung đã tới"
    )


def test_app_js_dat_ti_le_khung_theo_nguon_that():
    """Khung hình không được ép cứng 4:3.

    Camera thật đang chạy là 704x576 (11:9). Ép khung 4:3 rồi đặt ảnh 11:9
    vào trong (``object-fit: contain``) sinh ra hai dải đen hai bên — đã thấy
    đúng như vậy trên ảnh chụp màn hình thật. Tỉ lệ khung phải lấy từ
    ``naturalWidth/naturalHeight`` của khung đầu tiên.
    """
    script = _APP_JS.read_text(encoding="utf-8")
    assert "function matchFrameRatio()" in script, "thiếu hàm đặt tỉ lệ khung"
    body = script[script.index("function matchFrameRatio()") :][:500]
    assert "naturalWidth" in body and "naturalHeight" in body
    assert "--frame-ratio" in body, "không đặt biến CSS tỉ lệ khung"

    css = _CSS.read_text(encoding="utf-8")
    start = css.index(".live__frame {")
    block = css[start : css.index("}", start)]
    assert "var(--frame-ratio" in block, (
        ".live__frame vẫn ép một tỉ lệ cứng thay vì đọc --frame-ratio"
    )


def _stream_config():
    from posture_monitor.config import Config, WebConfig

    config = Config()
    config.web = WebConfig(host="127.0.0.1", port=8000, stream_enabled=True)
    return config


# ---------------------------------------------------------------------------
# Thanh trên cùng: tự ẩn khi cuộn, và nút ẩn hẳn
# ---------------------------------------------------------------------------
#
# Hai cơ chế khác nhau nên có hai nhóm khẳng định khác nhau. Như trên, đây là
# kiểm tra TĨNH: bộ test này không chạy JS. Hành vi thật (thanh trượt khỏi màn
# hình khi cuộn xuống, hiện lại khi cuộn lên, ẩn hẳn khi bấm nút và KHÔNG hiện
# lại khi cuộn) đã được kiểm bằng trình duyệt thật, ảnh chụp ghi trong báo cáo.


def test_template_co_nut_an_thanh_va_cach_mo_lai(client):
    html = client.get("/").get_data(as_text=True)

    # Nút ẩn nằm trên chính thanh, và khai báo quan hệ với thanh để trình đọc
    # màn hình hiểu nó điều khiển cái gì.
    assert 'id="bar-hide-btn"' in html, "thiếu nút ẩn thanh trên"
    assert 'aria-controls="topbar"' in html

    # Thanh phải có id để `aria-controls` trỏ tới một phần tử CÓ THẬT.
    assert 'id="topbar"' in html, "thanh trên cùng thiếu id để aria-controls trỏ tới"

    # Đường mở lại: mất nó là ẩn thanh xong không có cách quay về.
    assert 'id="bar-peek"' in html, "thiếu đường mở lại thanh đã ẩn"
    assert "Hiện thanh trên" in html


def test_thanh_an_ban_dau_de_trang_van_dung_duoc_khi_khong_co_js(client):
    """Tab mở lại phải `hidden` lúc tải trang.

    Nếu template để nó hiện sẵn, người chưa ẩn thanh sẽ thấy một dải "Hiện
    thanh trên" vô nghĩa ở đầu trang. Và khi JS hỏng, trang vẫn phải giữ thanh
    hiện — không được để trạng thái ẩn là mặc định trong HTML.
    """
    import re

    html = client.get("/").get_data(as_text=True)
    tag = re.search(r"<button[^>]*id=\"bar-peek\"[^>]*>", html)
    assert tag is not None, "không tìm thấy thẻ của tab mở lại"
    assert "hidden" in tag.group(0), "tab mở lại phải ẩn sẵn trong HTML"

    # Thanh thì ngược lại: không được mang sẵn dấu hiệu ẩn.
    assert 'data-bar="hidden"' not in html
    assert 'data-bar="scrolled"' not in html


def test_app_js_phan_biet_an_vi_cuon_va_an_vi_bam_nut():
    """Hai lý do ẩn thanh phải là hai trạng thái riêng.

    Gộp chúng vào một cờ là lỗi quen thuộc: người dùng bấm ẩn thanh, rồi cuộn
    lên một chút là thanh hiện lại — trái đúng điều họ vừa yêu cầu. Test soát
    rằng mã có hai trường riêng và rằng đường cuộn KHÔNG ghi đè khi đã ẩn.
    """
    script = _APP_JS.read_text(encoding="utf-8")

    state = script[script.index("var barState = {") :][:400]
    assert "hidden:" in state, "thiếu trạng thái 'đã bấm ẩn'"
    assert "scrolled:" in state, "thiếu trạng thái 'đang cuộn xuống'"

    # Đường cuộn phải thoát sớm khi thanh đã bị ẩn hẳn.
    apply_start = script.index("function applyScrollBar()")
    apply_body = script[apply_start : script.index("\n  }", apply_start)]
    guard = apply_body.index("if (barState.hidden) return;")
    write = apply_body.index("dataset.bar")
    assert guard < write, "cuộn còn ghi đè trạng thái ẩn do người dùng đặt"


def test_app_js_co_nguong_cuon_va_chi_phan_ung_theo_huong():
    """Thanh không được nhấp nháy vì dao động vài pixel.

    Có ngưỡng tối thiểu (ở đầu trang thì luôn hiện) và dung sai riêng cho
    chiều cuộn lên, nếu không một cú lăn ngược vài pixel cũng đủ bật thanh ra
    rồi tắt lại liên tục.
    """
    script = _APP_JS.read_text(encoding="utf-8")
    assert "BAR_SCROLL_MIN" in script, "thiếu ngưỡng cuộn tối thiểu"
    assert "BAR_UP_TOLERANCE" in script, "thiếu dung sai cho chiều cuộn lên"

    body = script[script.index("function onScrollFrame()") :][:1200]
    assert "atTop" in body, "không xét trường hợp đã về đầu trang"


def test_css_an_thanh_theo_hai_trang_thai():
    """CSS phải có cả hai trạng thái, và mỗi trạng thái một cách ẩn.

    Trượt đi (`transform`) khi cuộn, bỏ khỏi luồng (`display: none`) khi người
    dùng bấm ẩn — bỏ khỏi luồng là thứ duy nhất thật sự trả lại chỗ cho nội
    dung; chỉ trượt thì thanh vẫn chiếm chỗ như cũ.
    """
    css = _CSS.read_text(encoding="utf-8")

    scrolled = css[css.index('body[data-bar="scrolled"] .bar {') :]
    scrolled = scrolled[: scrolled.index("}")]
    assert "translateY(-100%)" in scrolled, (
        "trạng thái cuộn không trượt thanh khỏi màn hình"
    )

    hidden = css[css.index('body[data-bar="hidden"] .bar {') :]
    hidden = hidden[: hidden.index("}")]
    assert "display: none" in hidden, (
        "ẩn hẳn theo yêu cầu phải bỏ thanh khỏi luồng, không chỉ trượt đi"
    )

    # Và không được chừa thêm padding cho `.dash`: dải mở lại đã tự chiếm chỗ
    # trong luồng, chừa thêm là cộng hai lần và để lại một mảng trống dưới dải.
    assert 'body[data-bar="hidden"] .dash' not in css, (
        "chừa thêm padding cho .dash ở trạng thái ẩn: dải mở lại đã chiếm chỗ rồi"
    )


def test_dai_mo_lai_khong_phai_phan_tu_noi():
    """Dải mở lại thanh không được `position: fixed/sticky`.

    Bản đầu dùng `fixed` canh giữa đỉnh: cuộn sâu là nó đè lên chữ của thẻ bên
    dưới (ảnh chụp cho thấy nó che cả nhãn tín hiệu trên điện thoại). Đã thử
    `sticky` và cũng vậy — nó vẫn là khối nằm trên nội dung. Cách đúng là để
    nó ở đầu luồng như một dải mỏng.
    """
    css = _CSS.read_text(encoding="utf-8")
    start = css.index(".bar-peek {")
    block = css[start : css.index("}", start)]

    assert "position: fixed" not in block, (
        "dải mở lại dùng position:fixed → đè lên nội dung khi cuộn"
    )
    assert "position: sticky" not in block, (
        "dải mở lại dùng position:sticky → vẫn nằm trên nội dung khi cuộn"
    )
    assert "width: 100%" in block, "dải mở lại phải là dải ngang, không phải nút nổi"


def test_an_thanh_giu_duong_thoat_cho_ban_phim():
    """Ẩn thanh không được nhốt người dùng bàn phím.

    Nút ���n biến mất khỏi luồng, nên focus phải được chuyển sang dải mở lại;
    và Esc phải mở thanh — đó là lối thoát quen thuộc của mọi lớp phủ.
    """
    script = _APP_JS.read_text(encoding="utf-8")

    setter = script[script.index("function setBarHidden(") :][:900]
    assert ".focus()" in setter, "ẩn thanh không chuyển focus khỏi nút đã biến mất"

    keydown = script[script.index('document.addEventListener("keydown"') :][:1200]
    assert "barState.hidden" in keydown and "setBarHidden(false)" in keydown, (
        "Esc không mở lại được thanh đã ẩn"
    )


def test_thanh_hien_lai_khi_ban_phim_tab_vao_no():
    """Tab tới một nút trên thanh đang trượt đi thì thanh phải hiện lại.

    Không có nhánh này, focus đặt vào một nút không nhìn thấy và Enter kích
    hoạt một lệnh mà người dùng không biết mình vừa chọn. Chỉ áp dụng cho
    trạng thái ``scrolled``: thanh ẩn hẳn đã `display: none` nên các nút không
    nằm trong luồng tab nữa.
    """
    script = _APP_JS.read_text(encoding="utf-8")
    assert '"focusin"' in script, "không bắt sự kiện focus để hiện lại thanh"

    start = script.index('els.topbar.addEventListener("focusin"')
    body = script[start : start + 260]
    assert "barState.scrolled" in body, (
        "nhánh focusin không kiểm tra trạng thái cuộn"
    )
    assert "applyScrollBar()" in body, "nhánh focusin không vẽ lại thanh"


