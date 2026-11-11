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

Người học và phiên học (spec v3 §5.16). Mọi route người học trả **503** kèm câu
tiếng Việt khi phiên chạy không được tiêm dịch vụ người học:

| Route | Kiểu | Mô tả |
|---|---|---|
| `GET /api/people` | JSON | Danh sách `{id, name, created_ts}` + người đang chọn. **Không có vector** |
| `POST /api/people` | JSON | `{"name": "..."}` → 201 + `enroll_id` + năm bước hướng dẫn |
| `DELETE /api/people/<id>` | JSON | Xoá người học (bản ghi + vector); 404 nếu không có |
| `GET /api/enroll/<id>` | JSON | Tiến độ quét: `state`, `step_index`, `step_name`, `samples`, `samples_needed`, `error` |
| `POST /api/enroll/<id>/cancel` | JSON | Huỷ phiên quét; không ghi gì thêm |
| `POST /api/select` | JSON | `{"person_id": "..."}` hoặc `null` để bỏ chọn |
| `GET /api/signals` | JSON | Ba tín hiệu presence/phone/identity kèm `age_s` và `fresh` |
| `GET /api/schedule` | JSON | Khung giờ học hiện tại |
| `PUT /api/schedule` | JSON | Ghi khung giờ học; payload sai → 400 kèm câu tiếng Việt |
| `GET /api/session` | JSON | Trạng thái phiên học + thời lượng mặc định |
| `POST /api/session/start` | JSON | Bắt đầu phiên; thân tuỳ chọn `{"minutes": 60}` |
| `POST /api/session/stop` | JSON | Dừng phiên và tắt model AI |

`state` của một phiên quét là `running` / `done` / `cancelled` / `failed` — chỉ
máy chủ quyết định, giao diện không tự suy. **Không route nào trả embedding hay
vector** (spec §5.13.1, §8.3), kể cả khi dịch vụ lỡ trả kèm.

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

Hướng thiết kế: **bảng tin sáng** — nền xám lạnh rất nhạt (`#f0f2f5`), thẻ trắng
bo góc lớn, một sắc xanh duy nhất (`#1877f2`) làm nhấn. Phân cấp bằng khoảng
trắng và bóng đổ nhẹ, không bằng đường kẻ dày.

- **Khung camera nằm chính giữa màn hình đầu tiên** và là phần tử lớn nhất của
  trang. Một cột nội dung hẹp (tối đa 808 px) canh giữa, nên camera, ba tín
  hiệu và mọi thẻ phụ nằm trên cùng một trục dọc. Khung giữ tỉ lệ 4:3 và có
  `object-fit: contain`, nên nguồn ảnh tỉ lệ khác không bị cắt mất người.
  Trên màn hình thấp, bề rộng khung còn bị chặn theo chiều cao để camera vẫn
  nằm trong khung nhìn thay vì cao hơn màn hình.
- Bốn nút xoay camera đè lên góc dưới khung hình; trên điện thoại chúng rời
  xuống dưới hình để không che người ngồi trong khung.
- Ba tín hiệu "Trạng thái học" là ba tấm thẻ ngang hàng trên màn rộng, xếp dọc
  trên điện thoại.
- Trạng thái truyền đạt bằng **màu + biểu tượng + chữ**, không chỉ bằng màu.
  Tín hiệu cũ luôn nói "chưa có dữ liệu mới" thay vì lặp lại kết luận cũ.
- Chỉ có **chế độ sáng** (`color-scheme: light`): trình duyệt điện thoại không
  tự đảo nền trắng thành đen sau lưng bảng màu này.
- Nút cao ≥ 44 px trên điện thoại; `prefers-reduced-motion` được tôn trọng
  (vệt quét và mọi chuyển động bị tắt).
- **Thanh trên cùng tự ẩn khi cuộn xuống** và hiện lại khi cuộn lên, như thanh
  địa chỉ của trình duyệt di động: cuộn xuống quá 64 px thì thanh trượt lên
  khỏi màn hình, cuộn ngược lên (dung sai 8 px) hoặc về đầu trang thì hiện lại.
  Hai ngưỡng khác nhau là cố ý — nếu bằng nhau, một cú lăn ngược vài pixel cũng
  đủ làm thanh nhấp nháy.
- **Nút "Ẩn thanh trên"** (biểu tượng hai mũi tên, cuối dải nút) ẩn hẳn thanh:
  nó rời khỏi luồng (`display: none`) nên nội dung lên sát đỉnh. Trạng thái này
  **không** bị cuộn lên ghi đè — chỉ dải "Hiện thanh trên" (30 px, ở đầu trang)
  hoặc phím `Esc` mới mở lại. Trên điện thoại việc này tiết kiệm ~80 px chiều
  cao vì thanh ở đó cao ~110 px (hai nút đã xuống dòng).
- **Chart.js 4.4.7 nằm cục bộ** trong `web/static/chart.umd.min.js` (spec
  §5.10): Pi có thể không có Internet. Trang hiện không dùng biểu đồ (đề tài đã
  bỏ nhận diện tư thế) nhưng tệp vẫn để nguyên, không có tham chiếu CDN nào.
- Favicon là `data:` URI nhúng trong HTML nên không phát sinh request mạng.

Cập nhật: trạng thái mỗi 1 giây, phiên học mỗi 1 giây.

### 6.1 Thêm người bằng quét khuôn mặt (kiểu Face ID)

Bấm **Thêm người** → nhập tên → bấm **Tiếp tục: quét khuôn mặt**. Hệ thống mở
một hộp quét phủ kín màn hình với vòng tròn ở giữa; năm bước hướng dẫn
(nhìn thẳng → quay phải → quay trái → ngẩng → cúi) hiện lần lượt, mỗi bước một
chấm dưới vòng tròn.

Hộp quét có đúng ba trạng thái, mỗi trạng thái một màu và một câu chữ riêng:

| Trạng thái | Vòng quét | Nhãn | Làm được gì |
|---|---|---|---|
| Đang quét | xanh dương, có vệt quét | "Đang quét" | Huỷ |
| Xong | xanh lá, đầy vòng | "Đã quét xong" | Đóng (tự đóng sau ~2 giây) |
| Không đạt | đỏ | "Quét không đạt" | **Quét lại** hoặc Đóng |

Khi camera đang bật stream, khung hình thật được cắt tròn bên trong vòng quét
để người dùng thấy đúng chỗ đặt mặt. Kết nối MJPEG đó chỉ mở trong lúc hộp quét
hiện, và đóng lại khi hộp đóng — không giữ một luồng sống thường trực.

**Quét không đạt thì quét lại.** Bấm "Quét lại" mở **một phiên đăng ký mới** ở
máy chủ (không hỏi lại phiên đã `failed`, vì máy chủ không bao giờ chuyển một
phiên đã hỏng về `running`). Câu lỗi của máy chủ được hiện nguyên văn và nói rõ
đã thu được bao nhiêu mẫu trên bao nhiêu.

Máy chủ là bên duy nhất quyết định phiên đã xong hay hỏng; giao diện chỉ đọc
`GET /api/enroll/<id>` rồi vẽ lại. Nhờ vậy không có chuyện giao diện báo "đã
đăng ký" trong khi kho khuôn mặt chưa ghi gì.

Kho khuôn mặt chỉ giữ **vector đặc trưng**, tên và thời điểm — không lưu ảnh
khuôn mặt, và khung hình trong hộp quét không bao giờ được ghi ra đĩa
(spec §5.13.1, §11.5).

---

## 7. Điều khiển xoay camera (PTZ)

Dashboard có bốn nút mũi tên (lên/xuống/trái/phải) gọi `POST /api/ptz`, route
này nói chuyện với camera IP qua ONVIF. Bấm giữ thì camera xoay liên tục; nhả
tay thì dừng. Bàn phím (Tab + Enter) cũng bấm được, mỗi lần một bước ngắn.

### 7.1 Cài đặt

```bash
pip install rtsp-backchannel==0.5.2
```

Đã có trong `requirements.txt`. Thiếu thư viện thì chương trình vẫn chạy; chỉ
nút xoay báo lỗi tiếng Việt kèm đúng câu lệnh cần chạy.

### 7.2 Cấu hình — một địa chỉ camera, một nơi khai

Camera IP đã được khai ở `camera.source`, nên **không lặp lại IP** ở mục ONVIF:

```bash
export POSTURE_CAMERA_SOURCE="rtsp://admin:matkhau@192.0.2.50:554/1/2"
```

`192.0.2.50` là địa chỉ **ví dụ** thuộc dải TEST-NET; thay bằng IP thật của
camera lúc chạy. Đừng chép một IP cụ thể từ tài liệu: địa chỉ camera đổi theo
mạng, và IP cũ sẽ thành hướng dẫn sai. Tài liệu này chỉ dùng `192.0.2.x`.

| Khóa | Mặc định | Ý nghĩa |
|---|---|---|
| `camera.onvif.enabled` | `auto` | `auto` = bật khi xác định được host; `true` = bắt buộc (thiếu host/mật khẩu là lỗi lúc nạp); `false` = tắt hẳn |
| `camera.onvif.host` | `""` | Để trống thì suy ra từ `camera.source` khi đó là URL `rtsp://`. Chỉ điền khi camera PTZ khác host luồng ảnh |
| `camera.onvif.port` | `80` | Cổng **HTTP của ONVIF**, không phải cổng RTSP 554 |
| `camera.onvif.user` | `admin` | Bị tài khoản nhúng trong `camera.source` thay khi dùng nó |

Mật khẩu **không bao giờ** nằm trong `config.yaml`. Thứ tự ưu tiên:

1. `POSTURE_ONVIF_PASSWORD` (biến môi trường) — luôn thắng.
2. Tài khoản nhúng trong URL của `POSTURE_CAMERA_SOURCE` — cùng một camera thì
   cùng một tài khoản, nên không phải nhập hai lần.

Không có mật khẩu ở đâu cả thì PTZ tự coi là **tắt** (chương trình vẫn xem ảnh
bình thường), và bấm nút sẽ hiện thông báo chỉ rõ hai biến môi trường cần đặt.

### 7.3 Khi bấm nút mà không có gì xảy ra

Route luôn trả JSON `{"ok": false, "message": "..."}` bằng tiếng Việt, và
dashboard hiện nguyên câu đó ở dòng thông báo dưới các nút. Câu thường gặp:

| Thông báo | Nguyên nhân |
|---|---|
| "...Đặt POSTURE_CAMERA_SOURCE thành URL RTSP..." | PTZ chưa có host: nguồn ảnh không phải RTSP và `camera.onvif.host` trống |
| "...Đặt biến môi trường POSTURE_ONVIF_PASSWORD..." | Không có mật khẩu ở cả hai đường |
| "Chưa cài thư viện điều khiển PTZ..." | Thiếu `rtsp-backchannel` |
| "Không kết nối được tới camera để điều khiển PTZ..." | Sai IP/cổng ONVIF, hoặc camera không bật ONVIF |

Đối chiếu bằng tay:

```bash
curl -s -X POST http://<ip-của-Pi>:8000/api/ptz \
     -H 'Content-Type: application/json' \
     -d '{"direction": "left", "duration": 0.5}'
```

### 7.4 Giới hạn

- Mỗi lệnh xoay bị chặn ở **3 giây** (`camera_control.MAX_MOVE_DURATION_S`);
  giao diện gửi từng bước 0,4 giây nên một lần bấm giữ dài là nhiều lệnh nối
  tiếp, không phải một lệnh dài.
- Camera không quảng cáo `ContinuousMove` sẽ trả 501 ("chỉ hỗ trợ preset") —
  dự án chưa có đường điều khiển preset.
