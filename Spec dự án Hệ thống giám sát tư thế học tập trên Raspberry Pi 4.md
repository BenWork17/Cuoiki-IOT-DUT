# Spec dự án: Hệ thống giám sát tư thế học tập trên Raspberry Pi 4

Tài liệu giao việc cho AI agent · Phương án 1: YOLO11n-pose + luật hình học + IoT cơ bản · Cập nhật 28/10/2026

## 1. Mục tiêu và phạm vi

**Mục tiêu:** demo chạy ổn định trên Raspberry Pi 4: camera quan sát người học, nhận diện tư thế đúng/sai theo thời gian thực, cảnh báo bằng LED/buzzer/rung, hiển thị trạng thái trên dashboard web và lưu thống kê.

**Nguyên tắc:** ưu tiên chạy ổn định hơn độ mới của model; dùng model pretrained có sẵn, không huấn luyện model trong v1; mọi ngưỡng đặt trong file cấu hình, không viết cứng trong code.

**Trong phạm vi v1 (bắt buộc):**

- Pose estimation bằng YOLO11n-pose (xuất sang NCNN)
- Tính đặc trưng hình học, hiệu chỉnh cá nhân (calibration), phân loại tư thế bằng luật
- Phát hiện vắng mặt, ngồi quá lâu, gục đầu kéo dài
- Cảnh báo bằng LED + buzzer (+ mô-tơ rung nếu có)
- Cảm biến siêu âm đo khoảng cách (nếu có phần cứng)
- Lưu SQLite, dashboard web trong mạng LAN
- Chế độ giả lập không cần phần cứng và chế độ replay video để kiểm thử

**Ngoài phạm vi v1:** nhiều người (chỉ theo dõi một người), phát hiện nhắm mắt, servo, huấn luyện model, cloud, TTS, ứng dụng mobile.

**Mở rộng (chỉ làm khi v1 xong và được người dùng duyệt):** bộ phân loại MLP trên đặc trưng keypoint; servo pan-tilt; TTS tiếng Việt; bot Telegram.

## 2. Giả định mặc định

Agent dùng các giả định này và không hỏi lại, trừ khi bị chặn thật sự.

| Hạng mục | Giả định |
| --- | --- |
| Phần cứng | Raspberry Pi 4 (khuyến nghị 4 GB RAM trở lên), có tản nhiệt hoặc quạt |
| Hệ điều hành | Raspberry Pi OS Bookworm 64-bit, Python 3.11 |
| Camera | USB webcam hoặc Pi Camera; mã trừu tượng hóa nguồn ảnh |
| Góc đặt camera | Mặc định `front` (camera trên màn hình, nhìn thẳng người học); có hỗ trợ `side` (camera ở bên hông) |
| Model chính | yolo11n-pose, định dạng NCNN, imgsz 320 |
| Model dự phòng | yolov8n-pose (chỉ đổi tên trong config, code không đổi) |
| Người dùng | Một người học trước camera; nếu thấy nhiều người, chọn người có khung bao lớn nhất |
| Ngôn ngữ | Tên hàm/biến/commit bằng tiếng Anh; README, giao diện và thông báo bằng tiếng Việt |

## 3. Kiến trúc

```
Camera -> CaptureThread -> (khung mới nhất) -> InferenceLoop (~5 FPS)
                                                  |
                                         YOLO11n-pose NCNN
                                                  | 17 keypoint
                                          FeatureExtractor
                                                  | đặc trưng
                                  PostureClassifier (luật + baseline)
                                                  | nhãn + điểm
Sensors (HC-SR04) ----------------------> StateMachine (làm mượt, hold, cooldown)
                                                  |
                      +---------------------------+-------------------+
                 AlertManager               Storage (SQLite)       Web (Flask)
            LED/Buzzer/Rung/OLED           events, sessions     dashboard + API
```

Quy tắc luồng: luồng đọc camera luôn giữ khung mới nhất (bỏ khung cũ, không xếp hàng) để độ trễ không tăng dần. Suy luận chạy theo `target_fps` trong cấu hình.

## 4. Cấu trúc repo

```
posture-monitor/
├── README.md              # tiếng Việt: cài đặt, đấu dây, chạy, xử lý sự cố
├── requirements.txt       # khóa phiên bản sau khi chạy ổn
├── config.yaml
├── scripts/
│   ├── export_model.py    # xuất NCNN
│   ├── benchmark.py       # đo FPS, độ trễ, RAM, nhiệt độ CPU
│   ├── hw_selftest.py     # thử từng LED/buzzer/rung/siêu âm
│   └── install_pi.sh
├── src/posture_monitor/
│   ├── __main__.py        # CLI: run | calibrate | replay | benchmark
│   ├── config.py, capture.py, pose.py, features.py
│   ├── calibration.py, classifier.py, state.py
│   ├── alerts.py, sensors.py, storage.py
│   ├── hardware/ (gpio_real.py, gpio_mock.py)
│   └── web/ (app.py, templates/, static/)
└── tests/ (test_features.py, test_classifier.py, test_state.py, data/)
```

## 5. Chi tiết từng module

### 5.1 capture.py

- Giao diện `FrameSource.read()` trả khung BGR. Hai triển khai: `OpenCVSource` (webcam hoặc file video) và `PiCameraSource` (picamera2). Chọn bằng `camera.source`: `usb:0`, `picamera`, `file:duong_dan.mp4`.
- Thu 640x480; YOLO tự resize về imgsz khi suy luận.
- Tự kết nối lại khi mất camera (tối đa N lần), sau đó báo lỗi rõ ràng.

### 5.2 pose.py

- Tải model theo cấu hình. Nếu thư mục NCNN chưa có thì xuất một lần với imgsz đã cấu hình.
- `detect(frame)` trả `xy` (17x2, pixel), `conf` (17), `bbox`, hoặc None nếu không thấy người.
- Nếu xuất NCNN lỗi: tự rơi về ONNX rồi PyTorch, ghi cảnh báo rõ, không crash.

### 5.3 features.py

Chỉ số keypoint COCO: 0 mũi, 1/2 mắt trái/phải, 3/4 tai trái/phải, 5/6 vai trái/phải, 11/12 hông trái/phải. Chỉ dùng keypoint có conf >= `kp_conf_min` (mặc định 0.5). Thiếu keypoint thì đặc trưng tương ứng là None, tuyệt đối không đoán.

**Chế độ front:**

| Đặc trưng | Công thức | Ý nghĩa |
| --- | --- | --- |
| shoulder\_width | khoảng cách hai vai (px) | thước chuẩn hóa, đồng thời là thước đo độ gần |
| shoulder\_tilt\_deg | góc của đường nối hai vai so với phương ngang | nghiêng vai |
| head\_tilt\_deg | tương tự với hai tai | nghiêng đầu |
| head\_height | (y trung điểm vai − y mũi) / shoulder\_width | cao đầu so với vai; giảm khi cúi |
| closeness | shoulder\_width / baseline.shoulder\_width | lớn hơn 1 là tiến gần camera |
| lean\_x | (x trung điểm vai − baseline.x) / shoulder\_width | lệch/nghiêng người |
| head\_yaw | (x mũi − x trung điểm tai) / khoảng cách hai tai | quay đầu |

**Chế độ side:** `neck_angle` là góc tai–vai–hông ở phía thấy rõ hơn (chọn bên có conf cao hơn); `torso_angle` là góc vai–hông–gối nếu thấy. Ngưỡng riêng trong config. Cúi/gù khi góc nhỏ hơn baseline quá `neck_angle_drop_deg` (mặc định 15 độ).

### 5.4 calibration.py

- Lệnh `calibrate`: đếm ngược 3 giây, thu 5 giây khi người dùng ngồi đúng tư thế (yêu cầu tối thiểu 20 khung hợp lệ). Lấy trung vị từng đặc trưng làm baseline.
- Lưu `calibration.json` gồm baseline, độ phân giải, chế độ camera, thời điểm. Cảnh báo nếu độ phân giải hoặc chế độ khác lúc hiệu chỉnh.
- Không đủ khung hợp lệ thì báo lỗi kèm hướng dẫn chỉnh camera. `run` tự yêu cầu calibrate nếu chưa có file.

### 5.5 classifier.py

Mỗi khung sinh tập nhãn (có thể nhiều nhãn). Ngưỡng dưới đây là mặc định ban đầu để tinh chỉnh, đặt trong config:

| Nhãn | Điều kiện (front) | Mặc định |
| --- | --- | --- |
| HEAD\_DOWN | head\_height < baseline.head\_height × head\_down\_ratio | 0.70 |
| TOO\_CLOSE | closeness > too\_close\_ratio | 1.25 |
| SHOULDER\_TILT | abs(shoulder\_tilt − baseline) > ngưỡng | 8 độ |
| HEAD\_TILT | abs(head\_tilt − baseline) > ngưỡng | 12 độ |
| LEAN | abs(lean\_x) > ngưỡng | 0.35 |
| LOOK\_AWAY | abs(head\_yaw − baseline) > ngưỡng (xấp xỉ) | 0.5 |
| ABSENT | không thấy người hoặc thiếu hai vai | không áp dụng |
| GOOD | không có nhãn xấu nào | không áp dụng |

Điểm tư thế 0–100: bắt đầu 100, trừ điểm theo mức vượt ngưỡng của từng nhãn, giới hạn trong \[0, 100\]. Công thức đơn giản, ghi rõ trong code và README.

### 5.6 state.py

- Làm mượt: lấy trung vị đặc trưng trong cửa sổ `smooth_window_s` (1.0 s) trước khi áp luật.
- Nhãn xấu chỉ thành sự kiện cảnh báo khi duy trì liên tục từ `bad_hold_s` (5 s) trở lên; kết thúc khi trở lại bình thường từ `good_hold_s` (2 s) trở lên (hysteresis).
- Cooldown: không lặp cảnh báo cùng nhãn trong `alert_cooldown_s` (30 s); leo thang (đèn đỏ, buzzer dài hơn) nếu vẫn sai sau `escalate_after_s` (60 s).
- Nhắc nghỉ: ngồi liên tục từ `break_after_min` (45 phút) trở lên thì nhắc nghỉ; vắng mặt từ `absent_reset_s` (120 s) thì đặt lại bộ đếm.
- Gục đầu kéo dài: HEAD\_DOWN từ `drowsy_hold_s` (10 s) trở lên thì phát sự kiện DROWSY\_SUSPECT. Đây chỉ là xấp xỉ, README phải ghi rõ chưa phát hiện nhắm mắt.
- Đầu ra: trạng thái `GOOD | WARN | BAD | ABSENT`, danh sách nhãn, điểm, thời gian ngồi.

### 5.7 alerts.py và hardware

Giao diện `Hardware` có hai triển khai: `gpio_real` (dùng gpiozero) và `gpio_mock` (chỉ ghi log; dùng khi `--no-gpio` hoặc không phát hiện GPIO). Không dùng RPi.GPIO trực tiếp vì kém tương thích trên Bookworm.

Bảng đấu dây mặc định (số BCM, đổi được trong config):

| Linh kiện | Chân | Ghi chú |
| --- | --- | --- |
| LED xanh | GPIO17 | điện trở 220–330 ohm |
| LED vàng | GPIO27 | điện trở 220–330 ohm |
| LED đỏ | GPIO22 | điện trở 220–330 ohm |
| Buzzer chủ động | GPIO18 | qua transistor NPN nếu dòng lớn |
| Mô-tơ rung | GPIO23 | qua transistor NPN và diode flyback, không nối thẳng vào GPIO |
| HC-SR04 TRIG | GPIO5 |  |
| HC-SR04 ECHO | GPIO6 | bắt buộc chia áp 5V xuống 3.3V (ví dụ 1k và 2k ohm) |
| OLED SSD1306 (tùy chọn) | SDA GPIO2, SCL GPIO3 | I2C, địa chỉ 0x3C |

Ánh xạ trạng thái:

- GOOD: LED xanh sáng.
- WARN (nhãn xấu mới xuất hiện, chưa đủ bad\_hold\_s): LED vàng.
- BAD (sự kiện cảnh báo): LED đỏ, buzzer 2 tiếng ngắn, rung 300 ms; sau đó theo cooldown.
- ABSENT: tắt LED hoặc LED xanh nhấp nháy chậm.
- Nhắc nghỉ: buzzer 3 tiếng, hiện thông báo trên OLED và dashboard.

Linh kiện nào vắng thì module bỏ qua và ghi log, không được crash.

### 5.8 sensors.py

- HC-SR04: đọc mỗi 0.5 s trong luồng riêng, lấy trung vị 5 lần đọc, loại giá trị ngoài \[2, 200\] cm.
- Hợp nhất: TOO\_CLOSE nếu closeness của camera vượt ngưỡng hoặc khoảng cách siêu âm nhỏ hơn `min_distance_cm` (mặc định 35, chỉnh theo vị trí gắn cảm biến). Dashboard hiển thị cả hai nguồn.
- Có giao diện `Sensor` chung để sau này thêm BH1750 (ánh sáng), DHT22 (nhiệt độ/độ ẩm).

### 5.9 storage.py (SQLite)

- `sessions(id, start_ts, end_ts)`
- `events(id, session_id, ts, type, label, duration_s, extra_json)`: ghi khi bắt đầu và kết thúc sự kiện
- `minute_stats(session_id, minute_ts, good_pct, avg_score, absent_s, distance_cm_avg)`
- Không lưu ảnh hay video, chỉ lưu số liệu. Ghi theo lô mỗi 10 s để bảo vệ thẻ nhớ. Xóa dữ liệu cũ hơn `retention_days` (30).

### 5.10 web (Flask)

- `GET /`: dashboard tiếng Việt, dùng được trên điện thoại: trạng thái hiện tại (màu, nhãn, điểm), thời gian ngồi, khoảng cách, biểu đồ % tư thế đúng theo giờ/ngày. Chart.js đặt cục bộ trong `static/`, không dùng CDN vì Pi có thể không có Internet.
- `GET /api/status`, `GET /api/history?range=today|7d`, `POST /api/calibrate`, `POST /api/mute`.
- `GET /stream` (MJPEG có vẽ khung xương): tắt mặc định, bật bằng `web.stream_enabled` vì tốn CPU và ảnh hưởng quyền riêng tư.
- Mặc định lắng nghe 0.0.0.0 để xem từ điện thoại trong LAN; README ghi chú không mở ra Internet.

## 6. Cấu hình mẫu (config.yaml)

```yaml
camera:
  source: usb:0          # usb:N | picamera | file:duong_dan.mp4
  width: 640
  height: 480
  view: front            # front | side
model:
  name: yolo11n-pose     # dự phòng: yolov8n-pose
  format: ncnn           # ncnn | onnx | pt
  imgsz: 320
  target_fps: 5
  kp_conf_min: 0.5
thresholds:
  head_down_ratio: 0.70
  too_close_ratio: 1.25
  shoulder_tilt_deg: 8
  head_tilt_deg: 12
  lean_x: 0.35
  look_away_yaw: 0.5
  neck_angle_drop_deg: 15   # chỉ dùng cho view side
timing:
  smooth_window_s: 1.0
  bad_hold_s: 5
  good_hold_s: 2
  alert_cooldown_s: 30
  escalate_after_s: 60
  break_after_min: 45
  absent_reset_s: 120
  drowsy_hold_s: 10
alerts:
  buzzer_enabled: true
  vibration_enabled: true
hardware:
  mock: auto             # auto | true | false
  pins: {led_green: 17, led_yellow: 27, led_red: 22, buzzer: 18, vibration: 23, trig: 5, echo: 6}
sensors:
  ultrasonic_enabled: true
  min_distance_cm: 35
storage:
  db_path: data/posture.db
  retention_days: 30
web:
  host: 0.0.0.0
  port: 8000
  stream_enabled: false
```

## 7. Giao diện dòng lệnh

```
python -m posture_monitor calibrate
python -m posture_monitor run [--config config.yaml] [--no-gpio] [--view front|side]
python -m posture_monitor replay video.mp4 [--no-gpio] [--save-report out.json]
python -m posture_monitor benchmark [--seconds 60]
```

`replay` chạy cùng pipeline trên video để kiểm thử mà không cần người ngồi trước camera.

## 8. Tiêu chí nghiệm thu

| Chỉ tiêu | Mục tiêu | Cách kiểm tra |
| --- | --- | --- |
| FPS suy luận trên Pi 4 | từ 5 FPS ở imgsz 320 (đây là mục tiêu, chưa được xác nhận trước; phải đo thật và báo cáo số liệu) | `benchmark` |
| Độ trễ cảnh báo | không quá 2 s sau khi vi phạm đủ bad\_hold\_s | log thời gian |
| Nhiệt độ CPU | dưới 80 độ C khi chạy 30 phút | `benchmark` |
| RAM | dưới 1 GB cho cả tiến trình | `benchmark` |
| Ổn định | chạy liên tục 2 giờ, không crash, không rò rỉ bộ nhớ | chạy dài |
| Không phần cứng | đủ chức năng với `--no-gpio` | kiểm tra tay |
| Báo nhầm | tối đa 1 cảnh báo sai mỗi 10 phút khi ngồi đúng sau calibrate | kiểm tra tay |

**Quy tắc dự phòng khi không đạt FPS:** (1) giảm imgsz từ 320 xuống 256; (2) giảm target\_fps xuống 3; (3) đổi sang yolov8n-pose; (4) nếu cả ba đều thất bại thì dừng và báo lại người dùng để cân nhắc MoveNet hoặc MediaPipe. Không tự ý đổi sang model khác ngoài danh sách này.

## 9. Kiểm thử

- **Unit test (pytest):** `features` với keypoint tổng hợp (góc và tỉ lệ đã biết); `classifier` quanh ngưỡng; `state` (hold, hysteresis, cooldown, leo thang) bằng đồng hồ giả.
- **Tích hợp bằng `replay`:** video mẫu ngắn quay sẵn (ngồi đúng, cúi, nghiêng, quá gần, vắng mặt), kết quả kỳ vọng ghi trong `tests/data/expected.json`.
- **Phần cứng:** `scripts/hw_selftest.py` bật lần lượt từng LED, buzzer, rung và đọc siêu âm 10 lần.
- Mọi test trừ self-test phần cứng phải chạy được trên PC.

## 10. Lộ trình giao việc

Agent làm tuần tự theo mốc, dừng và báo cáo sau mỗi mốc.

| Mốc | Nội dung | Tiêu chí hoàn thành |
| --- | --- | --- |
| M0 | Khung repo, config, CLI, logging, mock hardware | `run --no-gpio` khởi động và in trạng thái giả |
| M1 | capture, pose, vẽ overlay | thấy keypoint từ webcam trên PC; xuất NCNN và chạy được trên Pi |
| M2 | features, calibration, classifier, state và unit test | `replay` ra nhãn đúng trên video mẫu; test pass |
| M3 | alerts, phần cứng thật, sensors | LED/buzzer/rung/siêu âm hoạt động; self-test pass |
| M4 | storage và web dashboard | xem trạng thái và biểu đồ từ điện thoại trong LAN |
| M5 | tối ưu, benchmark, README | đạt bảng mục 8, có báo cáo số liệu |
| M6 (tùy chọn) | mở rộng | chỉ làm khi được duyệt |

Nếu agent không truy cập được Raspberry Pi: hoàn thành M0, M2, M4 trên PC với mock hardware, phần M1, M3, M5 trên Pi thì viết sẵn kịch bản kiểm tra từng bước để người dùng tự chạy rồi gửi lại kết quả.

## 11. Quy tắc làm việc cho AI agent

1. Đọc toàn bộ spec trước khi code; làm theo mốc, bước nhỏ, có test.
2. Không tự đổi kiến trúc, model hay ngưỡng mặc định mà không ghi lại và báo cáo; tinh chỉnh ngưỡng chỉ qua `config.yaml`.
3. Khóa phiên bản thư viện trong `requirements.txt` sau khi chạy ổn; không nâng cấp `ultralytics` giữa chừng.
4. Không crash khi thiếu phần cứng, camera hoặc GPIO; luôn có đường rơi về an toàn và log rõ nguyên nhân.
5. Không lưu hay truyền ảnh/video; stream tắt mặc định.
6. Không viết số liệu hiệu năng chưa đo; mọi con số trong báo cáo phải đến từ `benchmark`.
7. Mỗi mốc kết thúc bằng: việc đã làm, cách chạy/kiểm tra, vấn đề còn tồn tại.
8. Chỉ hỏi người dùng khi bị chặn thật sự (thiếu phần cứng, lỗi môi trường, spec mâu thuẫn); ngoài ra dùng giả định ở mục 2.

## 12. Rủi ro và cách xử lý

| Rủi ro | Xử lý |
| --- | --- |
| FPS thấp trên Pi 4 | quy tắc dự phòng ở mục 8 |
| Báo nhầm do góc camera hoặc ánh sáng | calibration bắt buộc; hold và hysteresis; camera cố định |
| Keypoint bị che (hông sau bàn) | front chỉ dùng đầu và vai; thiếu thì không đánh giá thay vì đoán |
| Lỗi xuất NCNN | tự rơi về ONNX hoặc PyTorch và ghi log |
| GPIO trên Bookworm | dùng gpiozero, không dùng RPi.GPIO trực tiếp |
| ECHO của HC-SR04 (5V) làm hỏng GPIO | bắt buộc chia áp, ghi cảnh báo nổi bật trong README |
| Thẻ nhớ mòn do ghi SQLite | ghi theo lô, có retention |

## 13. Sản phẩm bàn giao

- Mã nguồn đầy đủ và README tiếng Việt (cài đặt, đấu dây dạng chữ, chạy, xử lý sự cố)
- `requirements.txt` đã khóa, `config.yaml` mẫu, thư mục `scripts/`
- Báo cáo benchmark trên Pi 4: FPS, độ trễ, nhiệt độ, RAM
- Bộ test, video mẫu và kết quả kỳ vọng
- Kịch bản demo 5 phút: calibrate, ngồi đúng, cúi, nghiêng, quá gần, vắng mặt, xem dashboard
