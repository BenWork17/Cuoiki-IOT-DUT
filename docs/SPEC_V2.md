# Spec dự án (v2): Hệ thống giám sát tư thế học tập trên Raspberry Pi 4

Tài liệu giao việc cho AI agent · Phương án 1: YOLO11n-pose + luật hình học + IoT cơ bản · **Bản v2, cập nhật 28/10/2026**

> **Đây là bản v2, ngày 28/10/2026.** Bản này **thay thế spec gốc (v1)** khi có xung đột giữa hai tài liệu. Mọi mục không được liệt kê trong bảng dưới đây giữ nguyên nội dung v1.

## Thay đổi so với v1

| Mục | Nội dung thay đổi | Lý do |
| --- | --- | --- |
| Toàn bộ | **Bản v2.1** cập nhật theo số liệu đo thật ngày 28/10/2026 trên chính Raspberry Pi 4 của dự án: bảng pin §2b (`pnnx`, `opencv-python`, `numpy`, `lgpio`), yêu cầu venv `--system-site-packages`, kích thước export và kết luận `export_on_pc` ở §5.2, mặc định `export_on_pc: false` ở §6, số FPS/nhiệt đo được ở §8, trạng thái kiểm tra camera ở §5.1, kết quả 5 bước A–E ở §14 | Thay số liệu suy đoán bằng số liệu đo trên máy đích |
| §2 | Sửa giả định "Hệ điều hành"; thêm giả định "Kiến trúc" | Raspberry Pi OS đã chuyển sang Trixie (Debian 13, Python 3.13), giả định Bookworm/Python 3.11 của v1 không còn đúng mặc định |
| §2b (mới) | Khóa phiên bản bắt buộc: ba bẫy `torch` 2.6.0, `ultralytics` 8.4.0–8.4.3, `opencv-python` 4.13.0.90; bảng pin đề xuất | Ba lỗi này đã được xác nhận bằng issue chính thức và tái hiện thực tế trên Pi 4 |
| §5.1 | Sửa **lỗi màu Pi Camera**: `main.format` đổi `BGR888` → `RGB888`; thêm bảng bẫy đặt tên format | Tên format của picamera2 ngược với thứ tự byte: `BGR888` cho `[R,G,B]` nên khung bị đảo kênh đỏ/xanh âm thầm |
| §5.2 | Thêm `model.export_on_pc`; thêm kích thước và thời gian export NCNN thực đo trên chính Pi | Export trên Pi chỉ mất 42,8 giây nên export trên Pi là mặc định (`export_on_pc: false`); `torch` vẫn là phụ thuộc bắt buộc lúc chạy |
| §5.3 | **Sửa công thức** `shoulder_tilt_deg`, `head_tilt_deg` (chuẩn hóa góc); thêm bảng độ tin cậy keypoint | Công thức thô của v1 sai gần 180°; keypoint tai có độ tin cậy thấp |
| §5.6 | Chọn người theo track id thay cho "khung bao lớn nhất" | Khung bao lớn nhất nhảy qua lại khi có người thứ hai |
| §5.7 | `gpio_mock` dùng `gpiozero.pins.mock.MockFactory` thay cho mã tự viết | Đã kiểm chứng chạy được trên gpiozero 2.0.1.post3 |
| §5.10 | `/stream` làm mờ người không được theo dõi bằng `ObjectBlurrer` | Bảo vệ quyền riêng tư |
| §6 | Bổ sung khóa cấu hình tương ứng §5.2 và §5.6 | Giữ config đồng bộ với thay đổi |
| §8 | Thêm dòng tiêu chí throttle; làm rõ ngưỡng nhiệt và ý nghĩa bitmask | FPS đo trong điều kiện throttle là số liệu không hợp lệ |
| §11.6 | Làm rõ quy tắc số liệu: mAP/thông số model được trích dẫn có nguồn; chỉ số hiệu năng bắt buộc đo tại máy | Tránh ngoại suy số liệu từ máy khác |
| §12 | Thêm 4 dòng rủi ro | Tương ứng các bẫy đã phát hiện |
| §14 (mới) | Bài kiểm chứng trên Pi trước khi bắt đầu M1, 5 bước A–E | Điều kiện tiên quyết để có số liệu hợp lệ |

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
| Hệ điều hành | Raspberry Pi OS 64-bit. Phiên bản phải xác nhận bằng `cat /etc/os-release` trước khi khóa `requirements.txt`, vì Raspberry Pi OS mặc định hiện tại đã chuyển sang Trixie (Debian 13, Python 3.13) trong khi spec v1 giả định Bookworm (Debian 12, Python 3.11). |
| Kiến trúc | aarch64 bắt buộc. Nếu `uname -m` trả `armv7l` thì dừng, cài lại OS 64-bit. |
| Camera | USB webcam hoặc Pi Camera; mã trừu tượng hóa nguồn ảnh |
| Góc đặt camera | Mặc định `front` (camera trên màn hình, nhìn thẳng người học); có hỗ trợ `side` (camera ở bên hông) |
| Model chính | yolo11n-pose, định dạng NCNN, imgsz 320 |
| Model dự phòng | yolov8n-pose (chỉ đổi tên trong config, code không đổi) |
| Người dùng | Một người học trước camera; nếu thấy nhiều người, chọn người theo track id (xem §5.6) |
| Ngôn ngữ | Tên hàm/biến/commit bằng tiếng Anh; README, giao diện và thông báo bằng tiếng Việt |

## 2b. Khóa phiên bản bắt buộc

Mục này liệt kê ba bẫy đã được xác nhận bằng issue chính thức của dự án upstream và bằng tái hiện thực tế. Agent **không được** cài phiên bản nằm trong vùng cấm, kể cả khi `pip` tự chọn phiên bản đó.

### Bẫy 1 — `torch==2.6.0` gây `Illegal instruction` trên Cortex-A72

- **Triệu chứng:** tiến trình chết ngay khi import hoặc khi chạy suy luận, thông báo `Illegal instruction`.
- **Nguyên nhân:** wheel aarch64 được build với `-march=armv8.2-a+sve`, sinh ra lệnh `ldaddal` — đây là lệnh atomic chỉ có từ ARMv8.1. Pi 4 (Cortex-A72) là ARMv8-A nên không có lệnh này.
- **Bằng chứng:** pytorch/pytorch#146792 (báo lỗi), bản vá pytorch/pytorch#149878; tái hiện thực tế ở ultralytics/ultralytics#19091 trên Pi 4B 8GB chạy Bookworm.
- **Lưu ý phiên bản:** 2.6.0 là bản 2.6.x duy nhất được phát hành — không có 2.6.1 và không có bản vá trong dòng 2.6.
- **Cách xử lý:** pin `torch!=2.6.*`, dùng `2.7.1` hoặc cao hơn.

### Bẫy 2 — `ultralytics` 8.4.0 đến 8.4.3 chặn NCNN trên ARM64

- **Triệu chứng:** raise `NotImplementedError: NCNN inference is not supported on ARM64` trên aarch64.
- **Bằng chứng:** ultralytics/ultralytics#23281, đã sửa ở 8.4.4.
- **Cách xử lý:** pin `ultralytics>=8.4.4`, và chọn một bản chính xác rồi **không nâng giữa chừng** (theo quy tắc §11.3).

### Bẫy 3 — `opencv-python==4.13.0.90` bị loại trừ

- **Nguyên nhân:** chính ultralytics loại trừ bản này trong `pyproject` (`opencv-python>=4.7.0,!=4.13.0.90`) do lỗi FIPS selftest.
- **Cách xử lý:** tránh bản này.

### Bắt buộc: venv phải có `--system-site-packages`

Trên Trixie, `picamera2` và `lgpio` chỉ có bản cài bằng apt trong `/usr/lib/python3/dist-packages`, không có wheel pip cho Python 3.13. Tạo venv bằng:

```bash
python3 -m venv --system-site-packages venv
```

Không có flag này thì `import picamera2` và `import lgpio` đều thất bại, kéo theo camera Pi và GPIO không dùng được.

### Bảng pin đề xuất (bản nháp để khóa)

> **Chỉ dùng được sau khi đã xác nhận OS thật bằng `cat /etc/os-release`** (§2). Đây là bản nháp để khóa `requirements.txt`, không phải bản đã nghiệm thu.

```
ultralytics==8.4.191
torch==2.7.1              # KHÔNG BAO GIỜ 2.6.0 trên Cortex-A72
torchvision==0.22.1       # pin cứng torch==2.7.1 (xác nhận từ metadata PyPI)
ncnn==1.0.20261020
pnnx==20260526            # chỉ cần khi export trên Pi
opencv-python==5.0.0.93   # KHÔNG 4.13.0.90
numpy==2.2.4              # bản apt của Trixie
PyYAML>=6.0
Flask==3.1.3
gpiozero==2.0.1.post3
lgpio                     # cài bằng sudo apt install python3-lgpio
psutil>=6.0
```

**Ghi chú pin `pnnx`:** Ultralytics 8.4.191 khai báo `pnnx==20260526` và sẽ tự động cài lại nếu khác; pin 20261020 là sai (đã kiểm chứng trên Pi ngày 28/10/2026).

**Ghi chú pin `opencv-python`:** Đã kiểm chứng chạy đúng trên Pi (resize, cvtColor, imencode JPEG). Vẫn tuân thủ ràng buộc `!=4.13.0.90` của ultralytics.

**Ghi chú pin `numpy`:** Bản apt của Trixie. Venv dùng `--system-site-packages` nên numpy đến từ hệ thống; đã kiểm chứng chạy đúng.

**Ghi chú pin `lgpio`:** Cài bằng `sudo apt install python3-lgpio`, bản `0.2.2-1~rpt1+trixie`.

**Ghi chú thêm:** `polars`, `ultralytics-thop`, `ultralytics-platform` đều là pure-python nên không chặn aarch64.

**Không cài `ultralytics[export]`.** Extra `export` gồm **5 sub-extra không điều kiện** (`export-base`, `export-openvino`, `export-tensorflow`, `export-coreml`, `export-litert`). Đọc `requires_dist` của chúng (metadata gói, xác nhận trên Pi ngày 28/10/2026, Python 3.13.5), trên Linux/aarch64/Python 3.13 có các ràng buộc **áp dụng được**: `tensorflow>2.19.0` (marker chỉ có `python_version >= "3.13"`, không giới hạn platform), `openvino>=2024.0.0`, `onnxruntime>=1.20.0`, `onnx>=1.12.0`, `coremltools>=9.0` (marker `platform_system != "Windows"` nên áp dụng cho Linux aarch64). Chưa chạy resolve thật (`pip install --dry-run` bị kill vì quá chậm) nên **chưa khẳng định được** pip cài được hay thất bại — nhưng đây rõ ràng là tập phụ thuộc lớn hơn nhiều so với `ultralytics` trần, và không cần cho việc export NCNN. Chỉ cài `ultralytics==8.4.191` trần; `pnnx` **không nằm trong extra `export`**, cài riêng khi cần export.

**Về ràng buộc `torch` trong extra `export`:** toàn bộ 6 mục `extra == "export"` của ultralytics 8.4.191 gồm 5 sub-extra trên và một ràng buộc `torch<2.15.0,>=2.12.0`. Ràng buộc đó mang marker `platform_system == "Linux" and platform_machine == "aarch64" and python_version == "3.11"`. **Máy đích chạy Python 3.13.5 nên marker này không kích hoạt** — vì vậy không được nêu nó làm lý do chính trên máy này.

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

- Giao diện `FrameSource.read()` trả khung BGR. Các triển khai: `OpenCVSource` (webcam), `FileSource` (file video), `PiCameraSource` (picamera2) và `RTSPSource` (camera IP). Chọn bằng `camera.source`: `usb:0`, `picamera`, `file:duong_dan.mp4`, `rtsp:rtsp://user:matkhau@host:554/1/2`.
- Thu 640x480; YOLO tự resize về imgsz khi suy luận.
- Tự kết nối lại khi mất camera (tối đa N lần), sau đó báo lỗi rõ ràng.
- Đóng nguồn là trạng thái cuối: sau `close()`, `read()` trả `None` và **không** mở lại thiết bị hay kết nối mạng (xem docstring `FrameSource`).

**Bẫy format màu của picamera2 (quan trọng).** Tên format của picamera2 — lấy từ libcamera — **ngược** với thứ tự byte thật trong bộ nhớ. Theo picamera2 manual RP-008156-DS-7 (Appendix A "Pixel and image formats"); manual ghi rõ nó mô tả **picamera2 version 0.3.37**, đúng bản apt đang cài trên máy đích, nên không có vênh phiên bản giữa tài liệu và máy:

| Format | Kích thước | Bố cục pixel |
| --- | --- | --- |
| `BGR888` | 24 bit, 3 byte, 32-bit aligned | `[R, G, B]` |
| `RGB888` | 24 bit, 3 byte, 32-bit aligned | `[B, G, R]` |

Tài liệu cũng cảnh báo nguyên văn: người dùng OpenCV thường muốn mỗi pixel là bộ ba `(B, G, R)`, và **phải chọn `RGB888`, không phải `BGR888`**.

Vì `FrameSource.read()` quy ước trả khung BGR (§5.1) và `OpenCVSource`/`FileSource` đều trả BGR, `PiCameraSource` **bắt buộc** cấu hình `main.format = "RGB888"`. Chọn `BGR888` sẽ khiến khung Pi Camera bị đảo kênh đỏ/xanh **một cách âm thầm** — không crash, chỉ sai màu và lệch phân phối kênh khi đưa vào YOLO.

Hệ quả nặng hơn bình thường vì `grep -rn "cvtColor\|COLOR_" src/ scripts/` cho **0 kết quả**: pipeline hoàn toàn tin vào tên format, **không có** đường chuyển màu dự phòng. Không phải "chỉ lệch khi ai đó quên convert" — mà là luôn lệch trên đường Pi Camera nếu tên sai.

Bằng chứng đã có (3 mức, ngày 28/10/2026):

1. **Đo trên Pi:** round-trip simplejpeg — encode mảng có pixel đỏ với `colorspace="RGB"` rồi `cv2.imdecode(..., IMREAD_COLOR)` cho BGR `[0, 0, 250]`; với `colorspace="BGR"` cho `[255, 0, 23]`. Nhãn colorspace chính là thứ tự byte trong bộ nhớ.
2. **Đọc từ source đã cài:** `FORMAT_TABLE` trong `picamera2/request.py` ánh xạ `"BGR888"` → `"RGB"` cho simplejpeg.
3. **Đọc từ tài liệu chính thức:** Appendix A, bảng format, bản 0.3.37.

**Chưa có:** phép thử bằng camera thật, vì Pi chưa gắn camera nào. Việc xác nhận cuối cùng khi có thiết bị là chụp một vật đỏ đã biết và kiểm tra kênh.

**Trạng thái kiểm tra trên Pi 4 của dự án (28/10/2026):** chưa gắn camera nào. `rpicam-hello --list-cameras` trả `No cameras available!`; `Picamera2.global_camera_info()` trả `[]`; `cv2.VideoCapture(0, cv2.CAP_V4L2).isOpened()` trả `False`; kernel không nạp `uvcvideo`. `picamera2` 0.3.37 (apt) đã sẵn sàng. `/dev/video10..31` là thiết bị codec/ISP của SoC, **không được** dùng làm nguồn ảnh.

Hệ quả bắt buộc:

- `camera.source: picamera` dùng `Picamera2`; `usb:N` dùng `cv2.VideoCapture(N, cv2.CAP_V4L2)`.
- Cả hai đường phải kiểm tra tồn tại trước khi mở và trả về `None` kèm log rõ ràng khi không có thiết bị — không được crash (theo §11.4).
- `usb:N` phải thử lần lượt các chỉ số và bỏ qua thiết bị codec/ISP: chỉ chấp nhận node có `V4L2_CAP_VIDEO_CAPTURE` và không thuộc `bcm2835-codec`/`bcm2835-isp`/`rpi-hevc-dec`.

#### Camera IP (RTSP)

`camera.source: rtsp:rtsp://user:matkhau@host:554/1/2` tạo `RTSPSource`. Nguồn này mở bằng `cv2.VideoCapture(url, cv2.CAP_FFMPEG)` và dùng cờ FFmpeg tương ứng lệnh tham chiếu:

```
ffplay -fflags nobuffer+discardcorrupt -flags low_delay -framedrop \
       -probesize 500000 -analyzeduration 1000000 -max_delay 500000 \
       -rtsp_transport udp rtsp://...
```

**Đo thật trên PC (không phải Pi):** OpenCV 4.13 từ chối cờ FFmpeg khi truyền qua tham số `.open()` (`VideoCapture(path, CAP_FFMPEG, [9999, 1])` → log "unsupported parameters in .open()", `isOpened()` = `False`), nên cờ phải đặt qua biến môi trường **process-global** `OPENCV_FFMPEG_CAPTURE_OPTIONS`, gán ngay trước khi mở và **khôi phục** trong `finally`. `CAP_PROP_BUFFERSIZE = 1` được đặt sau khi mở.

**Hệ quả về độ trễ — phải xả đệm trong mỗi lần đọc.** RTSP/FFmpeg vẫn đệm khung phía client dù đã đặt `BUFFERSIZE = 1`. Nếu pipeline chỉ đọc 5 FPS còn camera phát 20 FPS, đệm phình tuyến tính và độ trễ tăng vô hạn. Vì vậy `RTSPSource.read()` **bắt buộc** gọi `grab()` liên tiếp để vứt khung cũ, dừng khi một lần `grab()` phải chờ lâu hơn `RTSP_DRAIN_STEP_LIMIT_S = 0,03 s` (nghĩa là đã đuổi kịp luồng trực tiếp), rồi `retrieve()` đúng một lần.

Bảng dưới **đo trên PC, camera 192.168.1.151, luồng phụ 704x576** — không phải số liệu Pi (§11.6):

| Pipeline để trôi | Khung đệm phải bỏ | Thời gian xả |
| --- | --- | --- |
| 0,2 s | 4 | 34 ms |
| 0,5 s | 10 | 40 ms |
| 1,0 s | 26 | 59 ms |
| 2,0 s | 42 | 51 ms |
| 3,0 s | 62 | 137 ms |
| 5,0 s | 101 | 66 ms |
| 8,0 s | 128 | 94 ms |

Đệm tích lũy khoảng **29 khung/giây** (20 FPS phát, pipeline đọc ~5 FPS). Một lần `grab()` trên khung đã đệm tốn **0,29 ms**; khi đệm cạn, `grab()` phải chờ khung trực tiếp ≈ **50 ms** (= 1/20 FPS). Hai số này là cơ sở chọn ngưỡng 0,03 s: lớn hơn 0,29 ms gần 100 lần, nhỏ hơn 50 ms. `RTSP_MAX_DRAIN_FRAMES = 240` phủ đệm của stall 8 s (128 khung). Ngưỡng 0,03 s và các giới hạn này đều là **tham số constructor** để sau này chỉnh trên Pi mà không sửa code.

**`RTSP_DRAIN_TIME_LIMIT_S = 2,0` KHÔNG giới hạn thời gian một lần `read()`.** Nó chỉ là hạn cho **vòng xả**: kiểm giữa các lần `grab()`, ngăn vòng lặp xả chạy mãi. Bản thân `cap.grab()` là lời gọi đồng bộ, không huỷ được từ ngoài, nên một `grab()` đang chờ gói tin không bị hạn này cắt; `grab()` đầu tiên còn nằm hoàn toàn ngoài hạn. Hệ quả: **`read()` không có trần thời gian**. Chính bảng dưới đây chứng minh điều đó — có lần `read()` mất **2201 ms**, vượt hạn 2,0 s, trong khi số khung phải xả của lần đó chỉ vài chục, không phải 240.

**Rủi ro còn tồn tại — chưa đặt `timeout`/`stimeout` cho RTSP.** `RTSP_FFMPEG_OPTIONS` hiện chỉ có `rtsp_transport|fflags|flags|framedrop|probesize|analyzeduration|max_delay`, **không** có khóa `timeout`. Nếu camera mất kết nối giữa chừng, `grab()` có thể chặn rất lâu và cả vòng lặp pipeline đứng theo — dạng treo, tệ hơn crash vì không có log nào (§11.4). **Chưa đo** mức độ trầm trọng (cần camera + kiểm trên Pi); chưa có biện pháp khắc phục trong M6. Không được đọc phần trên như một bảo đảm chịu được mất mạng.

**Đuôi phân bố độ trễ đọc rất dài — không được chỉ nhìn p50.** Bốn lần đo `RTSPSource` thật, **Lead đo trên PC**, camera `192.168.1.151`, 5 FPS (không phải số liệu Pi, §11.6):

| Lần đo | n | p50 | p95 | p99 | max | > 500 ms | > 1000 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 30 s | 67 | 132 ms | 887 ms | — | 1255 ms | — | — |
| 60 s | 156 | 77 ms | 725 ms | 1739 ms | 2201 ms | 13/156 (8%) | 5 |
| 45 s, `udp` | 151 | 67 ms | 255 ms | 646 ms | 946 ms | 5 | 0 |
| 45 s, `tcp` | 137 | 82 ms | 490 ms | 1052 ms | 1240 ms | 6 | 2 |

Bốn lần đo cùng một camera cho p95 lệch nhau 255 / 490 / 725 / 887 ms: độ trễ đọc RTSP **không ổn định**. Nguyên nhân quan sát được: cảnh báo `Could not find ref with POC` của HEVC — mất gói UDP làm hỏng chuỗi tham chiếu, buộc giải mã chờ keyframe kế tiếp. Đo riêng của Peer (30 s, cùng camera) cho p50 79 ms / p95 242 ms / max 1807 ms, cũng lệch theo hướng này.

Hệ quả: tiêu chí §8 "độ trễ cảnh báo ≤ 2 s" **chưa thể kết luận** từ các số trên. Một lần đọc chậm 2,2 s là đã vượt tiêu chí, và p95 có lúc sát ngưỡng 2 s. Phải đo lại trên Pi, và cân nhắc `udp` vs `tcp` (`udp` tốt hơn ở p95 trong lần đo 45 s, nhưng số dao động giữa các lần nên chưa đủ kết luận).

**Camera của dự án phát HEVC (H.265), không phải H.264.** Luồng phụ `/1/2` là 704x576 @ 20 FPS HEVC; `/1/1` và `/1` là 1920x1080 HEVC. Chọn `/1/2` vì pipeline thu 640x480 rồi YOLO resize về `imgsz: 320` — 1080p chỉ tốn CPU giải mã mà không thêm thông tin.

**Giải mã HEVC trên Pi 4 — phần cứng có node, nhưng chưa đo được đường dùng.** `README.md` ghi nhận trên chính Pi của dự án (đo 28/10/2026) node `/dev/video19` mang driver `rpi-hevc-dec`, tức SoC có bộ giải mã HEVC V4L2 stateless. **Chưa đo** liệu OpenCV/FFmpeg có dùng được node đó cho luồng RTSP này hay không (cần `v4l2-ctl --list-devices`, `vainfo`/`v4l2-ctl --list-formats-out` và thử decode thật), và **chưa đo** FPS/độ trễ của `RTSPSource` trên Pi. Do đó **FPS và độ trễ trên Pi 4 là CHƯA ĐO** — không được suy ra từ bảng PC ở trên (§11.6).

**Chưa có công cụ đo RTSP trên Pi.** `scripts/camera_probe.py` hiện **không** đọc `POSTURE_CAMERA_SOURCE`, không gọi `RTSPSource`, không in FPS, không đọc nhiệt độ — `probe_cameras()` chỉ dò `picamera` + `usb` (`capture.py`). Lệnh `python -m posture_monitor benchmark` cũng chưa triển khai (in "chưa triển khai"). Vậy bước đo trên Pi **chưa có công cụ sẵn**; cần bổ sung chế độ RTSP cho `camera_probe.py` (hoặc một script đo FPS/nhiệt độ riêng) trước khi có số liệu. Chỉ ghi nhận việc cần làm, không được viết như thể đã đo được.

**Bảo mật:** URL có mật khẩu **không** được nằm trong file commit. `parse_camera_source` che thông tin đăng nhập (`rtsp://***:***@host:554/...`) trước khi đưa vào `ConfigError`, log và `repr`. Cách đặt URL thật: `config.local.yaml` (đã gitignore) rồi chạy `--config config.local.yaml`, hoặc biến môi trường `POSTURE_CAMERA_SOURCE` (thắng `camera.source` khi khác rỗng). Ở biến môi trường, URL trần `rtsp://...` được tự hiểu là `rtsp:rtsp://...`; dạng tường minh cũng chạy. Còn ở `config.yaml`, tiền tố `rtsp:` là **bắt buộc**.

### 5.2 pose.py

- Tải model theo cấu hình. Nếu thư mục NCNN chưa có thì xuất một lần với imgsz đã cấu hình.
- `detect(frame)` trả `xy` (17x2, pixel), `conf` (17), `bbox`, hoặc None nếu không thấy người.
- Nếu xuất NCNN lỗi: tự rơi về ONNX rồi PyTorch, ghi cảnh báo rõ, không crash.
- **Mới so với v1 — tùy chọn `model.export_on_pc`:** file NCNN (`.param` + `.bin`) độc lập kiến trúc, nên có thể export một lần trên PC rồi copy thư mục sang Pi. Cách này **chỉ loại bỏ `pnnx` và bước export khỏi Pi**: Pi không phải cài `pnnx` (24,7 MB) và không phải chạy pipeline export. **Nhưng `torch` vẫn là phụ thuộc bắt buộc lúc chạy**, vì `ultralytics` import `torch` không điều kiện ở cả ba điểm: `ultralytics/utils/__init__.py` (dòng 24, cấp module, không có guard), `ultralytics/nn/autobackend.py` (dòng 9 `import torch`, dòng 10 `from torch import nn`), và `ultralytics/nn/backends/ncnn.py` (dòng 8 `import torch`, còn dùng `torch.device("cpu")` ở nhánh Vulkan trong `load_model()`); kiểm tra runtime `import ultralytics` thì `'torch' in sys.modules` trả `True`, và cấu trúc này giữ nguyên ở tag `v8.4.191`. Do đó:
  - Pin `torch!=2.6.*` **vẫn áp dụng trên Pi**, không được bỏ.
  - Bước B của §14 **vẫn bắt buộc**, không được miễn vì đã export trên PC.
  Đây là thay đổi so với v1 và phải báo cáo theo §11.2.
- **Kích thước thực đo khi export trên chính Pi 4 (28/10/2026):**
  - Thời gian export: 42,8 giây (tổng 43,9 giây), tổng thư mục 11,1 MB
  - `model.ncnn.bin`: 11.508.260 byte
  - `model.ncnn.param`: 25.354 byte
  - `metadata.yaml`: 442 byte, `model_ncnn.py`: 685 byte
  - pnnx báo: `inputshape = [1,3,320,320]f32`, `FLOPS = 1.887G`

**Kết luận về `export_on_pc` (cập nhật 28/10/2026):** vì export trên Pi chỉ mất 42,8 giây và đã chạy thành công, `model.export_on_pc` **không còn là hướng bắt buộc**. Mặc định export ngay trên Pi (`export_on_pc: false`). Tùy chọn `export_on_pc: true` chỉ còn ý nghĩa khi không muốn cài `pnnx` (24,7 MB) trên Pi. Lưu ý: dù export ở PC thì `torch` vẫn là phụ thuộc bắt buộc lúc chạy (xem ghi chú ở trên), nên bước B của §14 vẫn phải làm.

### 5.3 features.py

Chỉ số keypoint COCO: 0 mũi, 1/2 mắt trái/phải, 3/4 tai trái/phải, 5/6 vai trái/phải, 11/12 hông trái/phải. Chỉ dùng keypoint có conf >= `kp_conf_min` (mặc định 0.5). Thiếu keypoint thì đặc trưng tương ứng là None, tuyệt đối không đoán.

**Sửa so với v1 — chuẩn hóa góc nghiêng:**

`shoulder_tilt_deg` và `head_tilt_deg` **phải chuẩn hóa góc về khoảng (-90, 90] trước khi dùng**. Công thức thô `atan2(dy, dx)` cho kết quả gần ±180° khi keypoint trái nằm bên phải keypoint phải trong ảnh — chuyện xảy ra bình thường do góc nhìn camera, không phải người nghiêng. Đo thực tế trên ảnh mẫu: công thức thô ra **-179,69°** trong khi cùng dữ liệu đó chuẩn hóa ra **0,31°**. Nếu giữ công thức thô thì luật `abs(shoulder_tilt - baseline) > 8°` sẽ bắn cảnh báo liên tục.

Chuẩn hóa: nếu góc > 90 thì trừ 180; nếu góc < -90 thì cộng 180.

**Chế độ front:**

| Đặc trưng | Công thức | Ý nghĩa |
| --- | --- | --- |
| shoulder\_width | khoảng cách hai vai (px) | thước chuẩn hóa, đồng thời là thước đo độ gần |
| shoulder\_tilt\_deg | góc của đường nối hai vai so với phương ngang, chuẩn hóa về (-90, 90] | nghiêng vai |
| head\_tilt\_deg | tương tự với hai tai, chuẩn hóa về (-90, 90] | nghiêng đầu |
| head\_height | (y trung điểm vai − y mũi) / shoulder\_width | cao đầu so với vai; giảm khi cúi |
| closeness | shoulder\_width / baseline.shoulder\_width | lớn hơn 1 là tiến gần camera |
| lean\_x | (x trung điểm vai − baseline.x) / shoulder\_width | lệch/nghiêng người |
| head\_yaw | (x mũi − x trung điểm tai) / khoảng cách hai tai | quay đầu |

**Độ tin cậy đặc trưng theo keypoint (đo trên ảnh mẫu):**

Đo trên `bus.jpg` (N=8 người, backend PyTorch):

| Nhóm keypoint | Conf trung bình | Số keypoint dưới ngưỡng 0,5 |
| --- | --- | --- |
| Tai | 0,40–0,48 | 3/6 đến 5/8 |
| Vai | 0,67–0,83 | — |
| Mũi | 0,55–0,71 | — |

Hệ quả: `head_tilt_deg` và `head_yaw` (phụ thuộc tai) sẽ thường xuyên trả None và **không nên là nguồn cảnh báo chính**; `head_height`, `shoulder_*`, `lean_x`, `closeness` bền hơn nhiều.

> Đây là đo trên ảnh minh họa chung, không phải bản học, nên chỉ dùng để định hướng thiết kế chứ **không phải số liệu nghiệm thu**.

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

> Lưu ý từ §5.3: HEAD\_TILT và LOOK\_AWAY phụ thuộc keypoint tai có độ tin cậy thấp, nên là nhãn phụ; không dùng làm nguồn cảnh báo chính.

### 5.6 state.py

- Làm mượt: lấy trung vị đặc trưng trong cửa sổ `smooth_window_s` (1.0 s) trước khi áp luật.
- Nhãn xấu chỉ thành sự kiện cảnh báo khi duy trì liên tục từ `bad_hold_s` (5 s) trở lên; kết thúc khi trở lại bình thường từ `good_hold_s` (2 s) trở lên (hysteresis).
- Cooldown: không lặp cảnh báo cùng nhãn trong `alert_cooldown_s` (30 s); leo thang (đèn đỏ, buzzer dài hơn) nếu vẫn sai sau `escalate_after_s` (60 s).
- Nhắc nghỉ: ngồi liên tục từ `break_after_min` (45 phút) trở lên thì nhắc nghỉ; vắng mặt từ `absent_reset_s` (120 s) thì đặt lại bộ đếm.
- Gục đầu kéo dài: HEAD\_DOWN từ `drowsy_hold_s` (10 s) trở lên thì phát sự kiện DROWSY\_SUSPECT. Đây chỉ là xấp xỉ, README phải ghi rõ chưa phát hiện nhắm mắt.
- **Sửa so với v1 — chọn người để theo dõi:** v1 dùng "khung bao lớn nhất", cách này nhảy qua lại khi có người thứ hai đi vào khung. Thay bằng track id (`YOLO.track()` với `botsort.yaml`) và **chỉ đổi người khi track hiện tại mất quá `absent_reset_s`**. Đã kiểm chứng `YOLO.track()` chạy được với backend NCNN và trả track id ổn định. Chi phí tracking phải được đo trong `benchmark`; nếu vượt ngân sách thì quay lại khung bao lớn nhất và ghi lại lý do.
- Đầu ra: trạng thái `GOOD | WARN | BAD | ABSENT`, danh sách nhãn, điểm, thời gian ngồi.

### 5.7 alerts.py và hardware

Giao diện `Hardware` có hai triển khai: `gpio_real` (dùng gpiozero) và `gpio_mock` (chỉ ghi log; dùng khi `--no-gpio` hoặc không phát hiện GPIO). Không dùng RPi.GPIO trực tiếp vì kém tương thích trên Bookworm.

**Sửa so với v1 — `gpio_mock` không tự viết:** thay mã tự viết bằng `gpiozero.pins.mock.MockFactory` có sẵn trong thư viện:

```python
from gpiozero import Device
from gpiozero.pins.mock import MockFactory

Device.pin_factory = MockFactory()
```

Đã kiểm chứng trên gpiozero 2.0.1.post3: LED mock bật/tắt đúng, `DistanceSensor` khởi tạo được ở chế độ mock và chỉ log cảnh báo `DistanceSensorNoEcho`/`PWMSoftwareFallback`.

> **Giới hạn:** `MockPin` không có sẵn phương thức giả lập khoảng cách, nên muốn test giá trị siêu âm thì phải bọc một lớp fake sensor ở tầng `sensors.py` thay vì ở tầng pin.

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
- Khi test ở chế độ mock: bọc lớp fake sensor ở tầng này (xem ghi chú §5.7), không giả lập ở tầng pin.

### 5.9 storage.py (SQLite)

- `sessions(id, start_ts, end_ts)`
- `events(id, session_id, ts, type, label, duration_s, extra_json)`: ghi khi bắt đầu và kết thúc sự kiện
- `minute_stats(session_id, minute_ts, good_pct, avg_score, absent_s, distance_cm_avg)`
- Không lưu ảnh hay video, chỉ lưu số liệu. Ghi theo lô mỗi 10 s để bảo vệ thẻ nhớ. Xóa dữ liệu cũ hơn `retention_days` (30).

### 5.10 web (Flask)

- `GET /`: dashboard tiếng Việt, dùng được trên điện thoại: trạng thái hiện tại (màu, nhãn, điểm), thời gian ngồi, khoảng cách, biểu đồ % tư thế đúng theo giờ/ngày. Chart.js đặt cục bộ trong `static/`, không dùng CDN vì Pi có thể không có Internet.
- `GET /api/status`, `GET /api/history?range=today|7d`, `POST /api/calibrate`, `POST /api/mute`.
- `GET /stream` (MJPEG có vẽ khung xương): tắt mặc định, bật bằng `web.stream_enabled` vì tốn CPU và ảnh hưởng quyền riêng tư.
- **Mới so với v1 — làm mờ người lạ:** khi `/stream` được bật, dùng `ultralytics.solutions.ObjectBlurrer` để làm mờ mọi người không phải người đang được theo dõi. Đã kiểm chứng class này chạy được với model pose NCNN. Đây là biện pháp bảo vệ quyền riêng tư, phù hợp quy tắc "không lưu, không truyền ảnh".
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
  export_on_pc: false    # export NCNN ngay trên Pi (xem §5.2)
tracking:
  enabled: true          # chọn người theo track id (xem §5.6)
  tracker: botsort.yaml
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
| **Throttle** | **không có bit throttle nào bật trong suốt bài đo** | **`vcgencmd get_throttled` ghi trong `benchmark`** |
| Ổn định | chạy liên tục 2 giờ, không crash, không rò rỉ bộ nhớ | chạy dài |
| Không phần cứng | đủ chức năng với `--no-gpio` | kiểm tra tay |
| Báo nhầm | tối đa 1 cảnh báo sai mỗi 10 phút khi ngồi đúng sau calibrate | kiểm tra tay |

**Số liệu đã đo trên Pi 4 của dự án (28/10/2026, NCNN imgsz 320):**

| Chỉ tiêu | Đo được | Điều kiện |
| --- | --- | --- |
| Inference median | 107,3 ms (p95 116,2; min 105,5) | 549 lần chạy trong 60 giây, cùng một ảnh tĩnh |
| FPS suy luận | 9,32 | Từ median; **chỉ là suy luận thuần** |
| Nhiệt độ CPU | 55,0 → 58,0 °C | Lấy mẫu mỗi 5 giây trong suốt bài đo |
| Throttle | `0x0` mỗi lần lấy mẫu | `vcgencmd get_throttled` |

Đây là FPS suy luận thuần trên ảnh tĩnh: chưa gồm đọc camera, chưa gồm feature extractor, chưa gồm web. FPS pipeline đầy đủ **chưa đo** và sẽ thấp hơn các số trên.

**Quy tắc dự phòng khi không đạt FPS:** (1) giảm imgsz từ 320 xuống 256; (2) giảm target\_fps xuống 3; (3) đổi sang yolov8n-pose; (4) nếu cả ba đều thất bại thì dừng và báo lại người dùng để cân nhắc MoveNet hoặc MediaPipe. Không tự ý đổi sang model khác ngoài danh sách này.

**Ý nghĩa bitmask của `vcgencmd get_throttled`:**

| Bit | Ý nghĩa |
| --- | --- |
| 0x1 | under-voltage (đang thiếu áp) |
| 0x2 | freq capped (đang bị hạ xung) |
| 0x4 | đang throttle (đang bị bóp hiệu năng) |
| 0x10000 | đã từng xảy ra under-voltage |
| 0x20000 | đã từng xảy ra freq capped |
| 0x40000 | đã từng xảy ra throttle |

**Nếu bật 0x40000 thì mọi số FPS đo được không hợp lệ.**

**Ngưỡng nhiệt — trích nguyên văn tài liệu chính thức Raspberry Pi:**

> "When the core temperature is between 80°C and 85°C, the Arm cores will be progressively throttled back. If the temperature reaches 85°C, both the Arm cores and the GPU will be throttled back."

Vì mục tiêu dưới 80 °C nằm sát biên dưới của dải throttle, **tản nhiệt hoặc quạt là bắt buộc chứ không phải tùy chọn**.

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

> **Bổ sung v2:** M1 chỉ được bắt đầu sau khi hoàn thành bài kiểm chứng ở §14.

## 11. Quy tắc làm việc cho AI agent

1. Đọc toàn bộ spec trước khi code; làm theo mốc, bước nhỏ, có test.
2. Không tự đổi kiến trúc, model hay ngưỡng mặc định mà không ghi lại và báo cáo; tinh chỉnh ngưỡng chỉ qua `config.yaml`.
3. Khóa phiên bản thư viện trong `requirements.txt` sau khi chạy ổn; không nâng cấp `ultralytics` giữa chừng.
4. Không crash khi thiếu phần cứng, camera hoặc GPIO; luôn có đường rơi về an toàn và log rõ nguyên nhân.
5. Không lưu hay truyền ảnh/video; stream tắt mặc định.
6. **Quy tắc số liệu (làm rõ ở v2):** số liệu mAP hoặc thông số model trích dẫn từ tài liệu chính thức được phép, **nhưng phải ghi rõ nguồn**. Chỉ số hiệu năng (FPS, độ trễ, nhiệt độ, RAM) **bắt buộc** phải do `benchmark` của dự án sinh ra trên chính máy Pi đích — không được lấy từ tài liệu, không được ngoại suy từ máy khác.
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
| `torch==2.6.0` gây `Illegal instruction` trên Cortex-A72 | Pin `torch!=2.6.*` |
| `ultralytics` 8.4.0–8.4.3 chặn NCNN trên ARM64 | Pin `>=8.4.4` |
| `shoulder_tilt_deg`/`head_tilt_deg` sai gần 180° nếu không chuẩn hóa góc | Chuẩn hóa về (-90, 90] |
| Keypoint tai tin cậy thấp, `head_tilt`/`head_yaw` thường None | Không dùng làm nguồn cảnh báo chính; tinh chỉnh ngưỡng qua config |
| Pi Camera bị đảo kênh đỏ/xanh | Dùng `RGB888` (byte `[B,G,R]`), không dùng `BGR888` (byte `[R,G,B]`) — xem §5.1 |

## 13. Sản phẩm bàn giao

- Mã nguồn đầy đủ và README tiếng Việt (cài đặt, đấu dây dạng chữ, chạy, xử lý sự cố)
- `requirements.txt` đã khóa, `config.yaml` mẫu, thư mục `scripts/`
- Báo cáo benchmark trên Pi 4: FPS, độ trễ, nhiệt độ, RAM
- Bộ test, video mẫu và kết quả kỳ vọng
- Kịch bản demo 5 phút: calibrate, ngồi đúng, cúi, nghiêng, quá gần, vắng mặt, xem dashboard

## 14. Bài kiểm chứng trên Pi trước khi bắt đầu M1

Đây là **điều kiện tiên quyết** trước M1. Không có số FPS nào được ghi vào tài liệu cho tới khi hoàn thành bước D và E.

### Bước A — Nhận dạng máy

```bash
uname -m                                    # phải là aarch64
grep -E "VERSION_CODENAME|PRETTY" /etc/os-release
python3 -V
grep -m1 Features /proc/cpuinfo             # Pi 4 phải thấy "fp asimd evtstrm crc32 cpuid"
free -m | head -2
df -h /
```

**Mục đích:** biết chính xác hệ điều hành, kiến trúc và phiên bản Python trước khi chọn wheel — đây là đầu vào bắt buộc của §2 và §2b.

**Tiêu chí đạt:** `aarch64`, có `crc32`, còn ít nhất 4 GB trống.

### Bước B — Cài trong venv riêng

```bash
mkdir -p ~/posetest && cd ~/posetest
python3 -m venv venv && source venv/bin/activate
pip install -U pip wheel
pip install ultralytics==8.4.191 torch==2.7.1 torchvision==0.22.1 ncnn
python -c "import torch; print(torch.__version__)"
```

**Mục đích:** xác nhận bộ pin ở §2b cài được và import được trên máy thật, tách khỏi môi trường của dự án.

**Tiêu chí đạt:** in ra phiên bản, không có `Illegal instruction`.

### Bước C — Export NCNN

```bash
yolo export model=yolo11n-pose.pt format=ncnn imgsz=320
ls -la yolo11n-pose_ncnn_model/
```

**Mục đích:** xác nhận pipeline export chạy được, hoặc xác nhận rằng nên chuyển sang phương án export trên PC (§5.2).

**Tiêu chí đạt:** có `model.ncnn.param` và `model.ncnn.bin`. `Illegal instruction` nghĩa là dính bẫy `torch`; `NotImplementedError` nghĩa là dính bẫy `ultralytics`.

### Bước D — Đo suy luận và nhiệt

```bash
# terminal 1
while true; do echo "$(date +%T) $(vcgencmd measure_temp) $(vcgencmd get_throttled)"; sleep 5; done | tee ~/posetest/thermal.log
# terminal 2
cd ~/posetest && source venv/bin/activate
yolo predict model=yolo11n-pose_ncnn_model source=0 task=pose imgsz=320 show=False save=False
```

Chạy 3–5 phút.

**Mục đích:** lấy số đo thật của máy đích, kèm log nhiệt và throttle chạy song song.

**Tiêu chí đạt:** có dòng `Speed: X ms preprocess, Y ms inference, Z ms postprocess`. FPS ước tính bằng `1000/(X+Y+Z)`.

### Bước E — Kiểm tra throttle

```bash
grep -v "throttled=0x0" ~/posetest/thermal.log | head
```

**Mục đích:** loại bỏ các bài đo bị nhiễu bởi throttle (xem bảng bitmask ở §8).

**Tiêu chí đạt:** không có dòng nào. Nếu có `0x4` hoặc `0x40000` thì số ở bước D **không dùng được**.

### Kết quả chạy ngày 28/10/2026

| Bước | Kết quả |
| --- | --- |
| A | Đạt. `aarch64`, Trixie, Python 3.13.5, Pi 4 Model B Rev 1.5, có `crc32`, RAM 3795 MB, đĩa còn 7,6 GB |
| B | Đạt. Venv `--system-site-packages`; `torch 2.7.1+cpu` import OK, không có `Illegal instruction` |
| C | Đạt. Export NCNN trên Pi thành công 42,8 giây, 11,1 MB |
| D | Đạt. 9,32 FPS suy luận thuần, nhiệt 55–58 °C. Chạy lại trên camera thật có FPS pipeline: **marginal**, 4/8 lần chạy đạt ≥ 5 FPS, trung vị ~4,96 FPS |
| E | Đạt. `throttled=0x0` mỗi lần lấy mẫu |

**Bổ sung — bước D đã chạy trên camera thật:** bước D giờ đã dùng camera thật, nên có FPS pipeline đầy đủ thay vì chỉ FPS suy luận thuần. Điều kiện đo: camera IP qua RTSP substream 704x576 @20fps, model `yolo11n-pose` NCNN, `imgsz: 320`, số liệu do `benchmark` của dự án sinh ra trên chính Pi 4, ngày 28/10/2026.

Tám lần chạy, cùng build cùng camera:

| Thời lượng | FPS pipeline | Đạt ≥ 5? |
| --- | --- | --- |
| 12 s | 5,006 | có |
| 20 s | 5,085 | có |
| 20 s | 4,985 | không |
| 30 s | 5,015 | có |
| 40 s | 3,929 | không |
| 45 s | 3,833 | không |
| 60 s | 4,207 | không |
| 60 s | 5,019 | có |

→ **4/8 đạt, trung vị ~4,96 FPS.** FPS pipeline **chưa đạt ổn định** mục tiêu 5 FPS ở §8.

Chi tiết một lần chạy 60 giây (lần có 5,019 FPS), phân vị p50 tính bằng ms:

| Đại lượng | p50 | p95 | max |
| --- | --- | --- | --- |
| `pipeline_total` | 199,25 | 233,09 | 1082,77 |
| `capture` | 65,93 | 96,85 | — |
| `pose_detect` | 133,32 | 142,25 | — |
| `pose_inference` | 100,51 | 108,63 | — |

Trong lần chạy đó: nhiệt độ max 58,9 °C, RAM peak 464,0 MiB, `vcgencmd get_throttled` = `0x0` suốt lần chạy. Ba tiêu chí §8 còn lại (nhiệt < 80 °C, RAM < 1024 MiB, throttle `0x0`) **đạt với biên rộng**; riêng FPS **không đạt ổn định**.

**Còn thiếu:** FPS ổn định ≥ 5. Bậc thang dự phòng của §8 là bước tiếp theo nhưng **chưa thực hiện**. Đổi model hoặc `imgsz` phải được ghi nhận và báo cáo theo §11 (quy tắc 2), nên cần người quyết định trước khi làm.
