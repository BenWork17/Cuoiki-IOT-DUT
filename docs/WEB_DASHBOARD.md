# Dashboard web và lưu trữ số liệu (M4)

Tài liệu cho người dùng và cho Peer nối dây vào CLI. Phạm vi: `storage.py` (SQLite)
và `web/` (Flask + giao diện tiếng Việt cho điện thoại) — spec v2 §5.9, §5.10.

> **Cảnh báo:** dashboard chỉ dùng trong **mạng LAN**. Không NAT, không forward
> cổng ra Internet, không đặt sau proxy công khai. Giao diện không có đăng nhập
> (spec §5.10).

---

## 1. Chạy thử trên PC (không cần camera)

```bash
python -m pytest tests/test_storage.py tests/test_web.py -q
```

Chạy server thật để xem giao diện:

```python
from posture_monitor.config import Config
from posture_monitor.storage import Storage
from posture_monitor.web import DashboardState, create_app, run_server

config = Config()
state = DashboardState()
storage = Storage(config.storage)
storage.open()

app = create_app(config, state=state, storage=storage)
run_server(app, config)
```

Mở `http://<ip-của-Pi>:8000/` trên điện thoại cùng mạng Wi-Fi.

Trên Pi, `data/` nằm cạnh mã nguồn; thư mục cha của `storage.db_path` được tạo
tự động nếu chưa có.

---

## 2. Nối vào vòng lặp chính (API cho Peer làm CLI)

`DashboardState` là **cầu nối duy nhất** giữa vòng lặp camera và web. Web không
bao giờ mở camera; vòng lặp không bao giờ chạm Flask. Cả hai chỉ nói chuyện qua
đối tượng này, nên test được mà không cần phần cứng.

### 2.1 Đẩy trạng thái lên web

```python
state.update(
    state=update.state,                 # "GOOD" | "WARN" | "BAD" | "ABSENT"
    labels=[str(l) for l in update.labels],
    score=update.score,
    sitting_s=update.sitting_s,
    distance_cm=distance_cm,            # None nếu không có cảm biến
    alert=alert_text,                   # hoặc None
)
```

Có thể truyền một dict: `state.update({...})`. Khóa lạ bị bỏ qua kèm log DEBUG
để không âm thầm đẩy sai tên trường. Nếu vòng lặp không cập nhật quá
`STALE_AFTER_S` (10 giây), dashboard tự hiện băng "Không nhận được dữ liệu mới".

### 2.2 Lệnh từ web xuống vòng lặp

Hai lệnh, đọc **mỗi khung** ở đầu vòng lặp:

```python
# Tắt/bật tiếng cảnh báo: chỉ đọc, không xoá.
if state.muted:
    ...  # bỏ qua buzzer/rung, vẫn ghi sự kiện và vẫn hiện cảnh báo trên web

# Hiệu chỉnh lại: đọc MỘT lần rồi tự xoá cờ.
if state.consume_calibration_request():
    calibration = Calibrator(...)   # chạy lại quy trình hiệu chỉnh
```

`consume_calibration_request()` trả `True` đúng một lần cho mỗi lần người dùng
bấm nút; gọi lần hai trả `False`, nên vòng lặp không hiệu chỉnh mãi.

### 2.3 Stream (tùy chọn, mặc định tắt)

```python
if web_cfg.stream_enabled:
    state.set_frame(jpeg_bytes)   # sau mỗi khung đã mã hoá JPEG
```

Không bật stream thì **không cần** gọi `set_frame` (không tốn CPU mã hoá JPEG
chỉ để vứt đi). `/stream` khi tắt trả 403 kèm thông báo tiếng Việt, không treo.

### 2.4 Ghi số liệu

```python
storage = Storage(config.storage)   # bật lên một lần lúc khởi động
storage.open()
storage.record(update, distance_cm=distance_cm)   # mỗi khung (hoặc mỗi giây)
storage.close()                                   # trong finally
```

`record()` tự gộp theo lô 10 giây, `close()` ghi nốt phần còn lại. **Không** cần
gọi `flush()` thủ công trong vòng lặp.

Nên gọi `storage.cleanup_retention()` một lần lúc khởi động (hoặc mỗi ngày) để
xoá dữ liệu cũ hơn `retention_days`.

Mọi lỗi DB (không mở được, ổ đầy, khoá) đều được nuốt và ghi log: chương trình
giám sát **không được dừng vì lưu trữ** (spec §11.4). Kiểm tra `storage.is_open`
nếu cần hiện trạng thái đó lên UI.

---

## 3. Dữ liệu được lưu

Ba bảng (spec §5.9):

| Bảng | Cột | Ý nghĩa |
|---|---|---|
| `sessions` | `id, start_ts, end_ts` | Một lần chạy; `end_ts` NULL khi đang chạy |
| `events` | `id, session_id, ts, type, label, duration_s, extra_json` | Cảnh báo, nhắc nghỉ, phát hiện vắng mặt… |
| `minute_stats` | `session_id, minute_ts, good_pct, avg_score, absent_s, distance_cm_avg` | Tổng hợp mỗi phút |

Quy ước:

- `good_pct` = **phần trăm thời gian** có người ngồi ở tư thế GOOD trên tổng
  thời gian có người (không tính lúc vắng).
- `avg_score` **loại các khung ABSENT**: lúc vắng mặt điểm là 0 nhưng đó không
  phải tư thế xấu nhất (spec §5.5). Thời gian vắng nằm riêng ở `absent_s`.
- Khoảng nghỉ dài hơn 5 giây giữa hai khung không được cộng vào thống kê —
  không thì một lần tắt máy 10 phút sẽ thành 10 phút "tư thế đúng".
- Phiên còn `end_ts IS NULL` do lần chạy trước bị kill sẽ được đóng lại lúc
  khởi động, nên không có hai phiên chồng lấn.

**Chỉ lưu số liệu. Không lưu ảnh, không lưu video, không lưu khung hình**
(spec §11.5). Không có trường nào chứa dữ liệu hình ảnh, kể cả khi bật stream.

Dữ liệu cũ hơn `retention_days` bị xoá bởi `cleanup_retention()`.

---

## 4. HTTP API

| Route | Kiểu | Mô tả |
|---|---|---|
| `GET /` | HTML | Dashboard tiếng Việt, tối ưu cho điện thoại |
| `GET /api/status` | JSON | Trạng thái hiện tại + `stream_enabled`, `min_distance_cm` |
| `GET /api/history?range=today` | JSON | Tỉ lệ đúng tư thế theo **giờ** của hôm nay |
| `GET /api/history?range=7d` | JSON | Tỉ lệ đúng tư thế theo **ngày**, 7 ngày gần nhất |
| `POST /api/calibrate` | JSON | Đặt cờ hiệu chỉnh cho vòng lặp chính |
| `POST /api/mute` | JSON | Đảo tiếng; hoặc `{"muted": true\|false}` để đặt thẳng |
| `GET /stream` | MJPEG | Chỉ khi `web.stream_enabled: true`, ngược lại 403 |

`/api/history` trả `has_data` và `message` tiếng Việt khi chưa có số liệu, nên
UI không phải tự đoán.

Lỗi trả về đều có dạng `{"ok": false, "message": "..."}` với thông báo tiếng
Việt hiển thị được cho người dùng.

---

## 5. Cấu hình

```yaml
storage:
  db_path: data/posture.db     # tương đối so với thư mục chạy
  retention_days: 30           # 0 = giữ tất cả

web:
  host: 0.0.0.0                # LAN; đổi 127.0.0.1 nếu chỉ xem trên máy
  port: 8000
  stream_enabled: false        # bật thật sự cần thiết
```

Đổi cổng thì chỉ cần sửa `web.port`; log lúc khởi động in đúng địa chỉ.

---

## 6. Giao diện

- Bố cục một cột, `viewport` cho điện thoại, nút cao ≥ 52 px để bấm bằng ngón
  tay, chữ lớn đọc được khi ngồi cách máy.
- Trạng thái truyền đạt bằng **màu + biểu tượng + chữ**, không chỉ bằng màu.
- Biểu đồ cột tỉ lệ tư thế đúng; có tab "Hôm nay" / "7 ngày", bảng số liệu thay
  thế (`<details>`) cho trình đọc màn hình và khi cần số chính xác.
- Sáng/tối theo `prefers-color-scheme`, mỗi chế độ có bảng màu riêng.
- **Chart.js 4.4.7 nằm cục bộ** trong `web/static/chart.umd.min.js` (spec
  §5.10): Pi có thể không có Internet. Không có tham chiếu CDN nào trong HTML.
  Nếu vì lý do nào đó `window.Chart` không có, `app.js` tự vẽ biểu đồ bằng SVG
  thuần để trang vẫn dùng được.
- Favicon là `data:` URI nhúng trong HTML nên không phát sinh request mạng.

Cập nhật: trạng thái mỗi 1 giây, số liệu biểu đồ mỗi 30 giây.
