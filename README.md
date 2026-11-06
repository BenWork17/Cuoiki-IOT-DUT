# Hệ thống giám sát học tập trên Raspberry Pi 4

Giám sát người ngồi học bằng camera: nhận diện **có mặt / đang dùng điện thoại /
đúng người**, nhắc bằng giọng đọc ra loa camera khi vi phạm, hiển thị trên
dashboard web trong mạng LAN và ghi số liệu vào SQLite.

> **Trạng thái hiện tại.** Hệ thống đã chạy được đầu–cuối trên Raspberry Pi 4:
> camera IP RTSP → nhận diện khuôn mặt → dashboard web → cảnh báo bằng loa →
> ghi SQLite. Đã kiểm chứng bằng lần chạy thật trên Pi (camera 704×576, nhận
> ra khuôn mặt đã đăng ký, dashboard phục vụ luồng MJPEG).
>
> Đặc tả kỹ thuật: [`docs/SPEC_V2.md`](docs/SPEC_V2.md) (nền) và
> [`docs/SPEC_V3.md`](docs/SPEC_V3.md) (hiện hành — bỏ nhận diện tư thế, thêm
> nhận diện người học và phiên học bấm tay).

---

## Hệ thống làm gì

Ba tín hiệu, hiện liên tục trên dashboard:

| Tín hiệu | Câu hỏi | Cách xác định |
| --- | --- | --- |
| **Có mặt** | Có ai đang ngồi trước bàn không | Pose/detect trên khung hình, có bộ lọc nhiễu |
| **Điện thoại** | Có đang dùng điện thoại không | Model detect COCO lấy lớp `cell phone`, lọc theo vị trí so với vai |
| **Danh tính** | Có đúng người đã chọn không | YuNet phát hiện + SFace đặc trưng, so cosine với kho đã đăng ký |

Ba việc hệ thống làm:

1. **Dashboard web** (`http://<ip-pi>:8000/`) — khung camera trực tiếp, ba tín
   hiệu kèm tuổi tín hiệu, nút Bắt đầu/Dừng phiên, thêm người bằng quét khuôn
   mặt, xoay camera.
2. **Cảnh báo bằng loa camera** — đọc tiếng Việt khi vi phạm (rời khung hình,
   dùng điện thoại, người lạ), dùng bản thu giọng người nếu có, không thì
   giọng máy, cuối cùng là tiếng bíp.
3. **Ghi số liệu** — phiên học, sự kiện, thống kê mỗi phút vào SQLite.

**Không lưu ảnh, không lưu video.** Khung hình chỉ đi qua RAM để hiển thị và
suy luận. Nhận diện khuôn mặt chỉ giữ **vector đặc trưng**, không giữ ảnh mặt.
Cảnh báo tư thế mặc định **tắt** (`posture_labels_enabled: false`).

---

## Yêu cầu môi trường

Môi trường đích đã được kiểm chứng:

| Hạng mục | Giá trị |
| --- | --- |
| Bo mạch | Raspberry Pi 4 Model B Rev 1.5, RAM 3795 MB |
| Kiến trúc | `aarch64` (bắt buộc — `armv7l` thì phải cài lại OS 64-bit) |
| Hệ điều hành | Raspberry Pi OS Trixie (Debian 13), kernel `6.18.34+rpt-rpi-v8` |
| Python | 3.13.5 |
| Nhóm của user | `video gpio i2c spi dialout` |

Trên PC, dự án chạy được với `--no-gpio` và nguồn `file:` hoặc webcam USB.

---

## Cài đặt trên Raspberry Pi

### 1. Gói hệ thống (bắt buộc cài bằng apt)

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-lgpio python3-numpy
```

`picamera2` và `lgpio` **không có bản wheel pip dùng được** trên Trixie
aarch64 — phải cài bằng apt.

### 2. Tạo venv — phải có `--system-site-packages`

```bash
cd ~/posture-monitor
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt
```

> **Đừng bỏ `--system-site-packages`.** Thiếu cờ này thì venv không thấy
> `picamera2` và `lgpio` của hệ thống, và `import picamera2` sẽ thất bại dù
> đã cài apt.

### 3. Mô hình phải có sẵn

Ba tệp mô hình **không nằm trong git** (quá lớn):

| Tệp | Dùng cho | Cách lấy |
| --- | --- | --- |
| `yolo11n-pose.pt` + `yolo11n-pose_ncnn_model/` | Nhận diện người, điện thoại | Ultralytics tự tải lần đầu, hoặc export NCNN |
| `yolo11n.pt` + `yolo11n_ncnn_model/` | Dò điện thoại (lớp `cell phone`) | Như trên |
| `yunet.onnx` (228 KB) | Phát hiện khuôn mặt | [`docs/MODELS.md`](docs/MODELS.md) |
| `sface.onnx` (37 MB) | Đặc trưng khuôn mặt | [`docs/MODELS.md`](docs/MODELS.md) |

Xem [`docs/MODELS.md`](docs/MODELS.md) để có link tải và cách kiểm chứng.

### 4. Không cài `ultralytics[export]`

Extra `export` gồm 5 sub-extra không điều kiện, kéo theo `tensorflow`,
`openvino`, `onnxruntime`, `coremltools` — không cần cho việc export NCNN.
Chỉ cài trần `ultralytics==8.4.191`. `pnnx` **không nằm trong extra `export`**,
cài riêng chỉ khi cần export NCNN ngay trên Pi.

### 5. Camera — khai địa chỉ ở MỘT nơi

Camera IP RTSP (khuyến nghị, đã kiểm chứng):

```bash
export POSTURE_CAMERA_SOURCE="rtsp://admin:matkhau@<ip-camera>:554/1/2"
```

Thay `<ip-camera>` bằng địa chỉ thật lúc chạy — đừng chép một IP cố định từ tài
liệu, vì địa chỉ camera đổi theo mạng. Trong tài liệu, mọi địa chỉ ví dụ đều là
`192.0.2.x` (dải TEST-NET) hoặc `192.168.1.x` giả định.

Không đặt biến môi trường thì dùng `camera.source` trong `config.yaml`
(`usb:N`, `picamera`, `file:duong_dan.mp4`).

Cùng một URL đó cũng cấp host và tài khoản cho **PTZ** (bốn nút xoay trên
dashboard) và **loa camera** (phát cảnh báo). Chỉ điền `camera.onvif.host` khi
camera PTZ nằm ở host khác luồng ảnh. Mật khẩu ONVIF lấy từ
`POSTURE_ONVIF_PASSWORD`, hoặc từ tài khoản nhúng trong URL ở trên.

---

## Chạy

```bash
# Từ gốc repo, với PYTHONPATH trỏ vào src/
export PYTHONPATH=src          # Windows PowerShell: $env:PYTHONPATH="src"

python -m posture_monitor --help
python -m posture_monitor run --no-gpio       # không cần GPIO
python -m posture_monitor run                 # tự phát hiện GPIO
```

Mở `http://<ip-của-Pi>:8000/` trên điện thoại hoặc máy tính cùng mạng Wi-Fi.

Năm lệnh:

| Lệnh | Việc |
| --- | --- |
| `run` | Chạy giám sát trực tiếp + mở dashboard web + ghi SQLite |
| `calibrate` | Hiệu chỉnh tư thế chuẩn, ghi `calibration.json` |
| `replay <video>` | Chạy lại pipeline trên video có sẵn, xuất báo cáo JSON |
| `benchmark` | Đo FPS/độ trễ/nhiệt/RAM trên máy đích |
| `speak-test` | Phát thử giọng đọc ra loa camera rồi thoát |

Cờ đáng chú ý của `run`:

| Cờ | Tác dụng |
| --- | --- |
| `--config` | Đường dẫn `config.yaml` (mặc định `config.yaml`) |
| `--no-gpio` | Dùng phần cứng giả lập (bắt buộc trên PC) |
| `--fps N` | Ghi đè `model.target_fps`. Trên laptop đặt 15 được; Pi 4 mục tiêu 5 |
| `--view {front,side}` | Ghi đè góc đặt camera |
| `--save-overlay DUONG_DAN` | Lưu một khung đã vẽ ra ảnh rồi thoát (kiểm chứng khi không có màn hình) |
| `--preview` | Mở cửa sổ OpenCV. **Mặc định không mở** — hình đã có trên web, và trên Pi qua xrdp cửa sổ Qt hay lỗi |

**Cách thoát:** `Ctrl+C`.

---

## Phiên học: công tắc duy nhất bật model AI

Ngoài phiên, hệ thống **vẫn xem camera và nhận diện khuôn mặt** (để dashboard
biết ai đang ngồi) nhưng **không** chạy pose, không dò điện thoại, không cảnh
báo. Bấm **Bắt đầu học** trên dashboard thì model AI mới chạy, và tự dừng khi
hết thời lượng đặt trước (mặc định 60 phút).

Đây là thiết kế có chủ đích: một lớp học 4 tiết không cần model chạy 8 tiếng
liên tục trên Pi 4.

`session.auto_start: true` trong `config.yaml` để vào phiên ngay khi khởi động
(tiện demo, không nên dùng hằng ngày).

---

## Nhận diện người học

Bấm **Thêm người** trên dashboard → nhập tên → **quét khuôn mặt kiểu Face ID**:
vòng tròn ở giữa, năm bước hướng dẫn (nhìn thẳng → quay phải → quay trái →
ngẩng → cúi), mỗi bước một chấm tiến độ. Chỉ khi đủ mẫu hợp lệ thì danh tính
mới được ghi.

Quét không đạt thì bấm **Quét lại** — nút này mở một phiên đăng ký **mới** ở
máy chủ (hỏi lại phiên đã `failed` sẽ không bao giờ chạy tiếp).

Ngưỡng nhận diện: `face.match_threshold: null` nghĩa là **chưa đo tay**, hệ
thống tự suy từ chính các mẫu vừa đăng ký (độ giống nhau thấp nhất giữa hai
mẫu cùng người, trừ một khoảng an toàn). Muốn đặt tay thì đo rồi điền số vào —
số trong config **luôn thắng** số tự suy.

`id` của một người **chính là tên của họ** (kho `faces.json` khoá theo tên), nên
đổi tên = xoá + đăng ký lại.

---

## Cảnh báo bằng loa camera

Ba câu cố định: rời khung hình, dùng điện thoại, người lạ. Ba nguồn tiếng, tự
rơi xuống khi thiếu:

1. **Bản thu giọng người** trong `data/audio/giongnam` hoặc `giongnu` — đo bằng
   STOI qua đúng chuỗi của camera (8 kHz → A-law → loa nhỏ): 0,958–0,972, so
   với 0,929–0,945 của giọng máy. Dễ nghe hơn hẳn trên loa 2 cm.
2. **Giọng máy** `espeak-ng` cho câu chưa có bản thu.
3. **Tiếng bíp** nếu cả hai đều không dùng được.

Đặt tên tệp bản thu trùng mã loại cảnh báo (`leave_frame.mp3`, `phone.wav`,
`stranger.m4a`) là chắc chắn nhất. Chọn giọng trên dashboard, lựa chọn được ghi
vào `data/audio/voice.json`.

Thử bằng tai: `python -m posture_monitor speak-test --speed 0.85`

---

## Kiểm thử

```bash
python -m pytest tests/ -q
```

**1492 passed, 4 skipped** (đo trên PC, Python 3.13).

Test chạy được trên PC, không cần camera thật: video giả tạo bằng
`cv2.VideoWriter`, dịch vụ người học tiêm bằng bản giả trong bộ nhớ.

Bài cần trọng số thật (`test_bus_image_has_three_persons`) tự bỏ qua nếu thiếu
`yolo11n-pose.pt`, `bus.jpg` hoặc các tệp mô hình khác.

---

## Cấu hình

Toàn bộ ngưỡng nằm trong [`config.yaml`](config.yaml):

| Mục | Nội dung |
| --- | --- |
| `camera` | `source`, kích thước, góc nhìn, `onvif` (PTZ), `speaker` (loa) |
| `model` | model pose, định dạng, `imgsz`, `target_fps`, `kp_conf_min` |
| `tracking` | chọn người theo track id |
| `phone` | model dò điện thoại, ngưỡng conf, bộ lọc báo nhầm |
| `thresholds`, `timing` | ngưỡng phân loại tư thế, hold/cooldown |
| `alerts`, `hardware`, `sensors` | phần cứng, cảm biến |
| `presence` | ngưỡng "vắng mặt" |
| `face` | mô hình khuôn mặt, ngưỡng, số mẫu đăng ký |
| `storage` | SQLite, số ngày giữ dữ liệu |
| `speaker_alert` | giọng đọc, âm lượng, tốc độ |
| `web` | host, port, `stream_enabled` |
| `schedule` | khung giờ học, nhịp nhắc lại từng loại cảnh báo |
| `session` | thời lượng gợi ý, tự vào phiên |

Khóa thiếu thì dùng mặc định; khóa **sai kiểu thì báo lỗi rõ tên khóa**. File
cấu hình không tồn tại cũng là lỗi rõ ràng, không lặng lẽ dùng mặc định.

**Mật khẩu không nằm trong `config.yaml`** (file được commit). Dùng biến môi
trường: `POSTURE_CAMERA_SOURCE`, `POSTURE_ONVIF_PASSWORD`.

---

## Ba bẫy phiên bản — đọc trước khi nâng cấp

| Bẫy | Triệu chứng | Cách xử lý |
| --- | --- | --- |
| `torch==2.6.0` | `Illegal instruction` ngay khi import | Pin `torch==2.7.1` |
| `ultralytics` 8.4.0–8.4.3 | `NotImplementedError: NCNN inference is not supported on ARM64` | Pin `==8.4.191` |
| `opencv-python==4.13.0.90` | Lỗi FIPS selftest | Pin `==5.0.0.93` |

Chi tiết ở [`docs/SPEC_V2.md` §2b](docs/SPEC_V2.md). **Không nâng `ultralytics`
giữa chừng.**

---

## Đấu dây phần cứng

Số chân là BCM, đổi được trong `config.yaml` → `hardware.pins`.

| Linh kiện | Chân | Ghi chú |
| --- | --- | --- |
| LED xanh | GPIO17 | điện trở 220–330 Ω |
| LED vàng | GPIO27 | điện trở 220–330 Ω |
| LED đỏ | GPIO22 | điện trở 220–330 Ω |
| Buzzer chủ động | GPIO18 | qua transistor NPN nếu dòng lớn |
| Mô-tơ rung | GPIO23 | qua transistor NPN + diode flyback, **không** nối thẳng |
| HC-SR04 TRIG | GPIO5 | |
| HC-SR04 ECHO | GPIO6 | **bắt buộc chia áp 5V → 3.3V** |
| OLED SSD1306 | SDA GPIO2, SCL GPIO3 | I2C, địa chỉ 0x3C |

> ⚠️ **Chân ECHO của HC-SR04 là 5V.** Nối thẳng vào GPIO 3.3V sẽ làm hỏng chân.
> Dùng cầu chia áp (ví dụ 1 kΩ và 2 kΩ).

`alerts.gpio_alert_enabled` mặc định **false**: đề tài không chấm điểm tư thế
nên GPIO chỉ cập nhật trạng thái, không kêu/rung. Bật lên nếu thực sự cần.

Nhiệt độ mục tiêu dưới 80 °C. Pi 4 bắt đầu throttle từ 80 °C — **tản nhiệt hoặc
quạt là bắt buộc** nếu muốn số đo FPS hợp lệ.

---

## Dò camera

```bash
python scripts/camera_probe.py
```

Chạy được trên cả PC và Pi. In bảng mọi node `/dev/video*` kèm driver, trạng
thái Pi Camera, danh sách camera USB, và gợi ý giá trị `camera.source`. Mã thoát
`0` nếu có ít nhất một nguồn ảnh, `1` nếu không.

Trên Pi 4, `/dev/video10..31` là **codec/ISP của SoC, không phải camera** — và
chúng vẫn mở được bằng `isOpened()`. Vì vậy script lọc theo tên driver trong
`/sys/class/video4linux/videoN/name` trước, rồi mới thử mở (đã loại đúng
14/14 node trên máy thật).

---

## Xử lý sự cố

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
| --- | --- | --- |
| **Sửa CSS xong vẫn thấy giao diện cũ** | Cache trình duyệt | Tải lại cứng `Ctrl+Shift+R`. Hệ thống đã gắn `?v=<mốc sửa đổi>` vào URL CSS/JS nên các lần sau tự hết |
| Trang đứng ở "Đang kết nối tới camera…" | Luồng MJPEG chưa có khung | Kiểm tra log `run`; xem `/stream` có trả ảnh không |
| Khung hình có dải đen hai bên | Tỉ lệ nguồn khác tỉ lệ khung | Hệ thống tự đọc tỉ lệ thật từ khung đầu tiên; nếu vẫn lệch thì báo lỗi kèm kích thước |
| `No cameras available!` | Chưa cắm camera, hoặc CSI chưa bật | `rpicam-hello --list-cameras`; `camera_auto_detect=1` trong `/boot/firmware/config.txt` |
| `ModuleNotFoundError: picamera2` | Venv thiếu `--system-site-packages` | Tạo lại venv đúng cờ, hoặc `sudo apt install python3-picamera2` |
| `ModuleNotFoundError: lgpio` | Chưa cài `python3-lgpio` | `sudo apt install -y python3-lgpio` |
| `Illegal instruction` khi import torch | Dính `torch==2.6.0` | Cài lại `torch==2.7.1` |
| `NCNN inference is not supported on ARM64` | `ultralytics` 8.4.0–8.4.3 | Nâng lên `==8.4.191` |
| Nút xoay camera báo lỗi tiếng Việt | PTZ chưa cấu hình / thiếu mật khẩu | Đặt `POSTURE_CAMERA_SOURCE` dạng `rtsp://`, hoặc `POSTURE_ONVIF_PASSWORD` |
| Màu bị đảo đỏ/xanh (Pi Camera) | Chọn nhầm `BGR888` | Phải dùng `RGB888` — xem [`docs/SPEC_V2.md` §5.1](docs/SPEC_V2.md) |

---

## Cấu trúc repo

```
.
├── README.md
├── requirements.txt
├── config.yaml
├── docs/
│   ├── SPEC_V2.md            # đặc tả nền (tư thế, phần cứng)
│   ├── SPEC_V3.md            # đặc tả hiện hành (người học, phiên học)
│   ├── WEB_DASHBOARD.md      # dashboard: giao diện, API, PTZ
│   ├── MODELS.md             # nguồn tải và cách kiểm chứng mô hình
│   └── REUSE_AUDIT.md        # đánh giá tài nguyên tái sử dụng
├── scripts/
│   ├── camera_probe.py       # dò và in bảng thiết bị quay hình
│   └── hw_selftest.py        # tự kiểm tra LED/buzzer/rung/siêu âm
├── src/posture_monitor/
│   ├── __main__.py           # CLI: run | calibrate | replay | benchmark | speak-test
│   ├── config.py             # đọc + kiểm tra config.yaml
│   ├── logging_setup.py      # logging dùng chung
│   ├── capture.py            # OpenCVSource, PiCameraSource, FileSource, probe
│   ├── pose.py               # nạp model + detect() → PoseResult
│   ├── overlay.py            # vẽ 17 keypoint + xương
│   ├── phone.py              # tín hiệu "đang dùng điện thoại"
│   ├── phone_detector.py     # model detect COCO + bộ lọc báo nhầm
│   ├── presence.py           # tín hiệu "có mặt / vắng mặt"
│   ├── faces.py              # YuNet + SFace, kho vector, cosine
│   ├── face_worker.py        # luồng nhận diện riêng
│   ├── people_service.py     # phiên đăng ký, tín hiệu có tuổi
│   ├── schedule.py           # khung giờ học, nhịp cảnh báo
│   ├── study_session.py      # phiên học bấm tay (công tắc model AI)
│   ├── camera_audio.py       # loa camera qua RTSP backchannel
│   ├── speaker_alert.py      # chọn giọng, phát câu cảnh báo
│   ├── voice_library.py      # quản lý bản thu giọng nam/nữ
│   ├── camera_control.py     # PTZ qua ONVIF
│   ├── features.py           # trích đặc trưng tư thế
│   ├── calibration.py        # baseline ⇄ calibration.json
│   ├── classifier.py         # gán nhãn tư thế
│   ├── state.py              # máy trạng thái GOOD/WARN/BAD/ABSENT
│   ├── alerts.py             # quyết định cảnh báo
│   ├── sensors.py            # HC-SR04, cảm biến phụ
│   ├── storage.py            # SQLite: phiên, sự kiện, thống kê phút
│   ├── benchmark.py          # đo FPS/độ trễ/nhiệt/RAM/throttle
│   ├── hardware/
│   │   ├── base.py           # giao diện Hardware
│   │   ├── gpio_mock.py      # MockFactory của gpiozero (chỉ log)
│   │   └── gpio_real.py      # LED/buzzer/rung thật
│   └── web/                  # dashboard Flask
│       ├── app.py            # DashboardState, create_app, run_server
│       ├── people_service.py # hợp đồng dịch vụ người học cho tầng web
│       ├── templates/index.html
│       └── static/           # style.css, app.js, font Geist nội bộ
└── tests/                    # 53 tệp test
```

---

## Ghi chú thiết kế

- **Không dùng `RPi.GPIO`** — dùng `gpiozero`, tương thích tốt hơn trên
  Bookworm/Trixie.
- **Không import `picamera2` và `lgpio` ở cấp module.** Chúng chỉ được import
  bên trong hàm, để trên PC mọi thứ vẫn import được.
- **`gpio_mock` dùng `gpiozero.pins.mock.MockFactory`** có sẵn, thay vì tự viết
  mock pin. Nhờ vậy không thể vô tình bật chân thật khi đang ở `--no-gpio`.
- **Nguồn ảnh giữ khung mới nhất, không xếp hàng** — độ trễ không tăng dần.
- **Không lưu, không truyền ảnh.** Chỉ lưu số liệu.
- **Nhận diện khuôn mặt không chặn vòng lặp.** `PeopleService.observe()` chỉ cất
  tham chiếu khung rồi trả về ngay; phần nặng (YuNet + SFace, 86,1 ms/lượt) chạy
  trên một luồng riêng. Chặn ở đó là vi phạm ngân sách khung.
- **`UNKNOWN` không bao giờ bị suy thành "người lạ".** Che mặt, ngược sáng,
  gallery rỗng hay chưa có ngưỡng đều là `UNKNOWN`. Chỉ khi so được với gallery
  và mọi người đều dưới ngưỡng mới là `MISMATCH` — báo nhầm vì không nhận ra là
  lỗi nghiêm trọng hơn bỏ sót.
- **Tín hiệu cũ phải nói "chưa có dữ liệu mới".** Không được lặp lại kết luận cũ
  như vừa đo được.
- **Dashboard chỉ dùng trong LAN.** Không NAT, không forward cổng ra Internet,
  không đặt sau proxy công khai. Giao diện không có đăng nhập.
- **CSS/JS có `?v=<mốc sửa đổi>`** để trình duyệt tải bản mới sau mỗi lần sửa.

---

## Giấy phép và lưu ý

`ultralytics` là **AGPL-3.0**. Đồ án chỉ dùng nội bộ và nộp báo cáo thì bình
thường; nếu sau này phát hành sản phẩm thì AGPL bắt buộc mở mã nguồn.

Chart.js (MIT) nằm cục bộ trong `web/static/` nhưng trang hiện không dùng. Chi
tiết giấy phép từng tài nguyên: [`docs/REUSE_AUDIT.md`](docs/REUSE_AUDIT.md).
