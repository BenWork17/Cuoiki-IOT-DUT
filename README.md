# Hệ thống giám sát tư thế học tập trên Raspberry Pi 4

Demo quan sát người học bằng camera, nhận diện tư thế ngồi theo thời gian thực
bằng YOLO11n-pose, cảnh báo bằng LED/buzzer/rung, hiển thị trạng thái trên
dashboard web trong mạng LAN và lưu thống kê vào SQLite.

> **Trạng thái hiện tại.** Đã có khung repo, cấu hình, logging, đủ bốn lệnh
> CLI (`run`, `calibrate`, `replay`, `benchmark`), nguồn camera hai đường
> (Pi Camera + USB), phần cứng thật/giả lập, **suy luận pose + vẽ 17
> keypoint/xương**, **phân loại tư thế** (`classifier.py`, `state.py`) và
> **lưu trữ SQLite** (`storage.py`).
>
> Hai phần **chưa được nối**: dashboard web **có mã trong `web/` và có test
> xanh**, nhưng chưa nối vào lệnh `run` — chạy `run` hiện chưa mở web. Lưu
> trữ SQLite cũng chưa được lệnh nào ghi vào; nó mới được dashboard dùng để
> đọc lịch sử. Bản thân `run` vẫn chỉ suy luận pose và vẽ lên khung hình —
> phân loại tư thế hiện chạy trong `replay` và `benchmark`.
> Đặc tả kỹ thuật đầy đủ nằm ở [`docs/SPEC_V2.md`](docs/SPEC_V2.md).

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

### 3. Không cài `ultralytics[export]`

Extra `export` gồm 5 sub-extra không điều kiện, đọc `requires_dist` thấy trên
Linux/aarch64/Python 3.13 sẽ áp dụng các ràng buộc `tensorflow>2.19.0`,
`openvino>=2024.0.0`, `onnxruntime>=1.20.0`, `onnx>=1.12.0`,
`coremltools>=9.0` — không cần cho việc export NCNN. Ràng buộc
`torch<2.15.0,>=2.12.0` trong extra này mang marker `python_version == "3.11"`
nên **không** áp dụng cho máy đích (Python 3.13.5), và không phải lý do ở đây.

Vì vậy chỉ cài trần `ultralytics==8.4.191` (đã có trong `requirements.txt`);
`pnnx` **không nằm trong extra `export`**, cài riêng chỉ khi cần export NCNN
ngay trên Pi. Chưa chạy resolve thật nên chưa khẳng định được pip cài được hay
thất bại. Chi tiết: [`docs/SPEC_V2.md` §2b](docs/SPEC_V2.md).

---

## Trạng thái camera trên Pi của dự án (đo ngày 28/10/2026)

Kết quả chạy `python scripts/camera_probe.py` trên chính Raspberry Pi 4 của dự án:

- **14 node `/dev/video10..31` là codec/ISP của SoC, không phải camera.**
  - `video10, 11, 12, 18, 31` → driver `bcm2835-codec`
  - `video13, 14, 15, 16, 20, 21, 22, 23` → driver `bcm2835-isp`
  - `video19` → driver `rpi-hevc-dec`

  Script loại đúng **cả 14/14** node. Đây là lý do phải lọc theo tên driver
  đọc từ sysfs chứ không dựa vào `isOpened()` — các node này vẫn mở được.

- **Hiện chưa gắn camera nào:** Pi Camera = không có, USB = không có. Script
  thoát với mã `1` và in hướng dẫn kiểm tra.

### Khi cắm Pi Camera

1. Kiểm tra cáp CSI đã cắm chắc ở cả hai đầu (bo mạch và camera).
2. Bảo đảm `/boot/firmware/config.txt` có `camera_auto_detect=1`, rồi khởi động lại.
3. Chạy lại `python scripts/camera_probe.py` — mục Pi Camera phải báo `CÓ SẴN`.
4. Đặt `camera.source: picamera` trong `config.yaml`.

### Khi cắm webcam USB

1. Cắm thẳng vào cổng USB của Pi, **không qua hub** (hub thiếu nguồn là nguyên
   nhân phổ biến khiến camera không nhận).
2. Chạy `lsusb` — phải thấy thiết bị UVC.
3. Chạy `python scripts/camera_probe.py` — node camera phải hiện trong bảng
   với kết luận `CAMERA`.
4. Đặt `camera.source: usb:0` trong `config.yaml`.

> ⚠️ Nếu gặp `Illegal instruction` khi chạy thì đang dính `torch 2.6.0`. Xem
> [`docs/SPEC_V2.md` §2b](docs/SPEC_V2.md) và cài lại `torch==2.7.1`.

---

## Ba bẫy phiên bản — đọc trước khi nâng cấp

| Bẫy | Triệu chứng | Cách xử lý |
| --- | --- | --- |
| `torch==2.6.0` | `Illegal instruction` ngay khi import | Pin `torch==2.7.1` |
| `ultralytics` 8.4.0–8.4.3 | `NotImplementedError: NCNN inference is not supported on ARM64` | Pin `==8.4.191` |
| `opencv-python==4.13.0.90` | Lỗi FIPS selftest | Pin `==5.0.0.93` |

Chi tiết và nguồn issue ở [`docs/SPEC_V2.md` §2b](docs/SPEC_V2.md). **Không
nâng `ultralytics` giữa chừng.**

---

## Chạy

```bash
# Từ gốc repo, với PYTHONPATH trỏ vào src/
export PYTHONPATH=src          # Windows PowerShell: $env:PYTHONPATH="src"

python -m posture_monitor --help

python -m posture_monitor run --no-gpio       # chạy không cần GPIO
python -m posture_monitor run                 # tự phát hiện GPIO
```

Bốn lệnh, đều đã triển khai:

| Lệnh | Cờ chính |
| --- | --- |
| `run` | `--config`, `--no-gpio`, `--view {front,side}`, `--save-overlay`, `--log-level` |
| `calibrate` | `--config`, `--output`, `--no-gpio` (no-op), `--log-level` |
| `replay <video>` | `video` (vị trí), `--config`, `--no-gpio` (no-op), `--save-report`, `--log-level` |
| `benchmark` | `--seconds`, `--config`, `--source`, `--json`, `--no-gpio` (no-op), `--log-level` |

- `run` — giám sát trực tiếp từ camera: suy luận pose và vẽ lên khung hình.
- `calibrate` — thu khung ở tư thế chuẩn rồi ghi baseline ra
  `calibration.json`.
- `replay` — chạy pipeline (pose → features → phân loại → máy trạng thái)
  trên một video có sẵn, in tóm tắt và tuỳ chọn ghi báo cáo JSON.
- `benchmark` — đo hiệu năng trên máy đích (spec §8).

`run` sẽ: nạp `config.yaml` → khởi tạo phần cứng (giả lập nếu `--no-gpio`) →
mở camera → nạp model pose → mở cửa sổ xem trước. Mỗi khung hình được suy
luận rồi vẽ 17 keypoint (chấm đỏ) và xương (nét xanh) lên trên.

> **Dashboard web chưa chạy trong `run`.** Mã dashboard nằm ở
> `src/posture_monitor/web/` và đã có test, nhưng vòng lặp của `run` hiện
> chưa khởi động Flask — chạy `run` sẽ **chưa** thấy web. Xem
> [`docs/WEB_DASHBOARD.md`](docs/WEB_DASHBOARD.md) để biết giao diện và API
> mà mã hiện có.

**Cách thoát:** bấm `q` (hoặc `Q`, hoặc `Esc`) khi cửa sổ đang được chọn, hoặc
bấm nút `X` của cửa sổ. Thoát bằng `Ctrl+C` cũng được (mã thoát `130`).

**Không có camera vẫn chạy được**: chương trình ghi log lý do cụ thể và thoát
với mã `1` — `run` cần camera để suy luận pose.

### Kiểm chứng trên máy không có màn hình

Cờ `--save-overlay` lưu **một** khung đã vẽ ra file ảnh rồi thoát, không mở
cửa sổ:

```bash
python -m posture_monitor run --no-gpio --save-overlay frame.jpg
```

Chương trình in đường dẫn file đã lưu và số người phát hiện được:

```
Đã lưu khung đã vẽ: /duong/dan/frame.jpg
persons=1
```

`persons=0` nghĩa là **không có ai trong khung ở thời điểm chụp** — trạng thái
hợp lệ, không phải lỗi.

### Nạp model và rơi cấp backend

Theo `model.format` trong `config.yaml` (mặc định `ncnn`), thứ tự là NCNN →
ONNX → PyTorch. Thiếu thư mục `*_ncnn_model` thì chương trình tự export một lần
với `imgsz` đã cấu hình; export lỗi (ví dụ thiếu `pnnx`) thì ghi WARNING rồi
rơi xuống backend kế tiếp, **không crash**. Chỉ khi không nạp được backend nào
mới báo lỗi và thoát với mã `2`.

Trọng số `yolo11n-pose.pt` và thư mục `yolo11n-pose_ncnn_model/` nằm trong
`.gitignore` — **không commit** chúng.

---

## Dò camera

```bash
python scripts/camera_probe.py
```

Script chạy được trên cả PC và Pi. Nó in:

- Bảng mọi node `/dev/video*` kèm tên driver và kết luận node nào là camera thật.
- Trạng thái Pi Camera (`picamera2`).
- Danh sách camera USB phát hiện được.
- Gợi ý giá trị `camera.source` nên dùng.

Mã thoát `0` nếu có ít nhất một nguồn ảnh, `1` nếu không có.

### Vì sao không dùng `/dev/video10..31`?

Trên Pi 4, các node đó là **thiết bị codec/ISP của SoC**, không phải camera:

| Node | Driver |
| --- | --- |
| `/dev/video10..` | `bcm2835-codec`, `bcm2835-codec (vchiq)` |
| `/dev/video11..` | `bcm2835-isp` |
| `/dev/video1x` | `rpi-hevc-dec` |

Chúng thường **vẫn mở được** bằng `cv2.VideoCapture(idx).isOpened()` — nên
`isOpened()` một mình không đủ để kết luận. Code dò tên driver trong
`/sys/class/video4linux/videoN/name` và loại ba họ driver trên trước, rồi mới
thử mở.

---

## Cấu hình

Toàn bộ ngưỡng nằm trong [`config.yaml`](config.yaml). Các mục:

| Mục | Nội dung |
| --- | --- |
| `camera` | `source` (`usb:N` / `picamera` / `file:...`), kích thước, góc nhìn |
| `model` | tên model, định dạng, `imgsz`, `target_fps`, `kp_conf_min`, `export_on_pc` |
| `tracking` | chọn người theo track id |
| `thresholds` | ngưỡng phân loại tư thế |
| `timing` | hold, cooldown, nhắc nghỉ |
| `alerts`, `hardware`, `sensors`, `storage`, `web` | phần cứng, dữ liệu, dashboard |

Khóa thiếu thì dùng mặc định; khóa **sai kiểu thì báo lỗi rõ tên khóa**.
File cấu hình không tồn tại cũng là lỗi rõ ràng, không lặng lẽ dùng mặc định.

---

## Đấu dây phần cứng (M3)

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

> ⚠️ **Chân ECHO của HC-SR04 là 5V.** Nối thẳng vào GPIO 3.3V sẽ làm hỏng
> chân. Dùng cầu chia áp (ví dụ 1 kΩ và 2 kΩ) trước khi nối.

### Nhắc nhiệt độ

Ngưỡng mục tiêu là dưới 80 °C. Theo tài liệu chính thức Raspberry Pi, core
bắt đầu bị throttle từ 80 °C và throttle mạnh ở 85 °C. **Tản nhiệt hoặc quạt
là bắt buộc, không phải tùy chọn** nếu muốn số đo FPS hợp lệ.

---

## Kiểm thử

```bash
python -m pytest tests/ -v
```

Đo trên PC (Python 3.13): **544 passed, 4 skipped**.

Test chạy được trên PC, không cần camera thật: video giả được tạo bằng
`cv2.VideoWriter` trong thư mục tạm.

Bài tích hợp `test_bus_image_has_three_persons` cần trọng số thật và ảnh mẫu.
Đặt chúng trong `tests/data/` (`yolo11n-pose.pt`, `bus.jpg`) hoặc trỏ ra bản
cục bộ bằng `POSTURE_TEST_WEIGHTS` và `POSTURE_TEST_IMAGE`; thiếu file thì test
tự bỏ qua (skip), không làm đỏ bộ test.

---

## Kiểm tra nhanh sau khi cài trên Pi

```bash
uname -m                                  # phải in aarch64
cat /etc/os-release | grep VERSION_CODENAME
python -V
python -c "import torch; print(torch.__version__)"   # phải 2.7.1, không Illegal instruction
python scripts/camera_probe.py
python -m posture_monitor run --no-gpio
python -m posture_monitor run
```

---

## Xử lý sự cố

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
| --- | --- | --- |
| `No cameras available!` | Chưa cắm camera, hoặc camera CSI chưa bật | Kiểm tra cáp; `camera_auto_detect=1` trong `/boot/firmware/config.txt`; `rpicam-hello --list-cameras` |
| `ModuleNotFoundError: picamera2` | Venv thiếu `--system-site-packages` | Tạo lại venv đúng cờ, hoặc `sudo apt install python3-picamera2` |
| `ModuleNotFoundError: lgpio` | Chưa cài `python3-lgpio` | `sudo apt install -y python3-lgpio` |
| `Illegal instruction` khi import torch | Dính `torch==2.6.0` | Cài lại đúng `torch==2.7.1` |
| `NCNN inference is not supported on ARM64` | `ultralytics` 8.4.0–8.4.3 | Nâng lên `==8.4.191` |
| Không mở được camera USB | Chỉ số sai, hoặc không có quyền | Chạy `python scripts/camera_probe.py`; kiểm tra `id` có nhóm `video` |
| `Camera: KHÔNG MỞ ĐƯỢC` nhưng vẫn chạy | Đúng thiết kế — thiếu camera không làm chết chương trình | Đọc log WARNING phía trên để biết lý do |
| Chân GPIO không bật được | Chạy nhầm trên PC, hoặc dùng `--no-gpio` | Trên Pi bỏ `--no-gpio`; trên PC luôn dùng `--no-gpio` |
| Màu bị đảo đỏ/xanh khi dùng Pi Camera | Chọn nhầm `BGR888` (byte là `[R,G,B]`) | Phải dùng `RGB888` (byte `[B,G,R]`) — xem [`docs/SPEC_V2.md` §5.1](docs/SPEC_V2.md) |

### Ghi chú về môi trường có sẵn

Trạng thái phần cứng đã kiểm chứng trực tiếp trên Pi đích khi viết mã này:

- `rpicam-hello --list-cameras` → `No cameras available!`
- `Picamera2.global_camera_info()` → `[]`
- `cv2.VideoCapture(0, cv2.CAP_V4L2).isOpened()` → `False`
- Kernel không nạp `uvcvideo`

Nghĩa là **chưa có camera nào được gắn**. Logic lọc node codec/ISP đã được
kiểm chứng trên máy thật (loại đúng 14/14 node — xem mục "Trạng thái camera
trên Pi" phía trên). Phần **mở** camera thật (Pi Camera và USB) thì **chưa
được nghiệm thu trên phần cứng**, vì chưa có thiết bị để cắm; mới chỉ kiểm
chứng được đường xử lý khi thiếu camera (trả `None` + log rõ, không crash).
Khi có camera, chạy lại `python scripts/camera_probe.py` để xác nhận.

---

## Cấu trúc repo

```
.
├── README.md
├── requirements.txt
├── config.yaml
├── docs/
│   ├── SPEC_V2.md
│   └── WEB_DASHBOARD.md
├── scripts/
│   ├── camera_probe.py        # dò và in bảng thiết bị quay hình
│   └── hw_selftest.py         # tự kiểm tra LED/buzzer/rung/siêu âm
├── src/posture_monitor/
│   ├── __main__.py            # CLI: run | calibrate | replay | benchmark
│   ├── config.py              # đọc + kiểm tra config.yaml
│   ├── logging_setup.py       # logging dùng chung
│   ├── capture.py             # OpenCVSource, PiCameraSource, FileSource, probe
│   ├── pose.py                # nạp model + detect() → PoseResult
│   ├── overlay.py             # vẽ 17 keypoint + xương theo kp_conf_min
│   ├── features.py            # trích đặc trưng tư thế
│   ├── calibration.py         # baseline tư thế chuẩn ⇄ calibration.json
│   ├── classifier.py          # gán nhãn tư thế
│   ├── state.py               # máy trạng thái GOOD/WARN/BAD/ABSENT
│   ├── alerts.py              # quyết định cảnh báo
│   ├── sensors.py             # HC-SR04, cảm biến phụ
│   ├── storage.py             # SQLite: phiên, sự kiện, lịch sử
│   ├── benchmark.py           # đo FPS/độ trễ/nhiệt/RAM/throttle
│   ├── hardware/
│   │   ├── base.py            # giao diện Hardware
│   │   ├── gpio_mock.py       # MockFactory của gpiozero (chỉ log)
│   │   └── gpio_real.py       # LED/buzzer/rung thật
│   └── web/                   # dashboard Flask (CHƯA nối vào lệnh run)
│       ├── app.py             # DashboardState, create_app, run_server
│       ├── templates/
│       └── static/
└── tests/
```

Các module của M2 trở đi (`features.py`, `calibration.py`, `classifier.py`,
`state.py`, `alerts.py`, `sensors.py`, `storage.py`, `benchmark.py`, `web/`)
đều đã có mã và test. Phần còn thiếu là **dây nối** giữa vòng lặp của `run`
với `web/` và `storage.py`; cho tới khi nối xong, `run` chỉ suy luận pose và
vẽ khung hình, không mở dashboard và không ghi SQLite.

---

## Ghi chú thiết kế

- **Không dùng `RPi.GPIO`** — dùng `gpiozero`, tương thích tốt hơn trên
  Bookworm/Trixie.
- **Không import `picamera2` và `lgpio` ở cấp module.** Chúng chỉ được import
  bên trong hàm, để trên PC mọi thứ vẫn import được.
- **`gpio_mock` dùng `gpiozero.pins.mock.MockFactory`** có sẵn, thay vì tự
  viết mock pin. Nhờ vậy không thể vô tình bật chân thật khi đang ở `--no-gpio`.
- **Nguồn ảnh giữ khung mới nhất, không xếp hàng** — độ trễ không tăng dần.
- **Không lưu, không truyền ảnh.** Chỉ lưu số liệu; stream mặc định tắt.
