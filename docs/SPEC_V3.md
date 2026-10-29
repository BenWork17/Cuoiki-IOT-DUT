# Spec dự án (v3): Hệ thống lớp học thông minh — giám sát người học bằng camera IP

Tài liệu giao việc cho AI agent · **Bản v3, 29/10/2026** · Thay đề tài "giám sát tư thế ngồi" ở `docs/SPEC_V2.md` bằng đề tài "giám sát sự hiện diện và tập trung khi học".

> **Đây là bản v3.** Khi xung đột, v3 thắng v2. Những gì v3 **không** nói tới vẫn giữ nguyên theo v2 — v3 chủ yếu **bổ sung** module, không xoá hạ tầng v2. Bảng dưới liệt kê đúng những chỗ v2 bị thay thế hoặc bị nới.

## Quy ước số liệu (áp dụng cho toàn tài liệu)

| Nhãn | Nghĩa |
| --- | --- |
| **ĐÃ ĐO** | Số đo thực trên chính Raspberry Pi 4 của dự án, có người đo, có ngày. Được dùng làm căn cứ thiết kế và nghiệm thu. |
| **TÍNH TỪ ĐO** | Số học suy ra từ các số **ĐÃ ĐO** (cộng, chia, trung bình). Ghi rõ công thức. | 
| **GIẢ THIẾT** | Chưa đo. Chỉ dùng để lập kế hoạch; **không được** dùng làm căn cứ nghiệm thu hay cam kết hiệu năng. |

Đúng theo quy tắc v2 §11.6: chỉ số hiệu năng (FPS, độ trễ, nhiệt, RAM) phải do chính dự án đo trên máy đích. Không có số nào trong tài liệu này lấy từ blog, README của người khác hay suy diễn từ máy khác.

---

## Thay đổi so với v2

| Mục | Thay đổi | Lý do |
| --- | --- | --- |
| §1 | Mục tiêu đổi: từ "tư thế đúng/sai" sang "có mặt / dùng điện thoại / học hộ / trong giờ học" | Đề tài mới: camera IP đặt góc trước bàn học, nhìn cả bàn và người ngồi |
| §3, §5.11–§5.15 (mới) | Thêm 5 module: `presence`, `phone`, `faces`, `schedule`, `speaker_alert` | Bốn hành vi cần giám sát + khung giờ + kênh cảnh báo |
| §5.7 | Kênh cảnh báo chính đổi từ **buzzer trên GPIO** sang **loa của camera IP** (RTSP backchannel) | Yêu cầu đề tài; loa camera to hơn buzzer và không cần đấu dây |
| §5.2 | Thêm model thứ hai `yolo11n` (detect) chạy **cách khung**; thêm `yunet.onnx` + `sface.onnx` cho khuôn mặt | Nhận diện điện thoại và nhận diện người |
| §8 | Ngân sách FPS mới theo 3 model; ghi rõ cấu hình nào **đã đo**, cấu hình nào **chưa đo** | Số đo 6,18 FPS chỉ đúng cho 2 model, chưa gồm khuôn mặt |
| §11 | Giữ nguyên toàn bộ, **bổ sung** quy tắc dữ liệu sinh trắc học (§11.9 mới) | Khuôn mặt là dữ liệu nhạy cảm hơn tư thế ngồi |
| §5.10, §5.16 | **`web.stream_enabled` mặc định `true`** (v2 để `false`). Hiển thị camera là chức năng chính của đề tài | Đề tài yêu cầu web hiển thị luồng camera; khung vẫn chỉ nằm trong RAM, không lưu |
| §5.13 | Bắt buộc **thu nhỏ về 320 trước khi detect mặt** + **trả hộp về hệ pixel khung gốc**; CLAHE bật mặc định nhưng không phải điều kiện để chạy | Đo thật 2026-10-29: YuNet 99,9 ms @704x576 so với 19,3 ms @320x262 |
| §5.13.1 | Embedding lưu **nhị phân cục bộ, không mã hoá**; mã hoá chuyển thành hướng mở rộng ở §12 | Thêm phụ thuộc chưa kiểm chứng vào đường chạy chính là rủi ro không đáng |
| §12, §13 | Bảng rủi ro mới cho điện thoại/khuôn mặt/loa camera | Rủi ro khác hẳn v2 |
| §14 | Thêm bài kiểm chứng trước M7 (đo cấu hình 3 model) | Không được tuyên bố đạt 5 FPS khi chưa đo cấu hình đầy đủ |
| §17 (mới) | Điều tra sự cố nút PTZ — ba lớp lỗi độc lập | Hiện trạng thực tế: route có và đã test, nhưng UI, cấu hình và môi trường Pi đều chưa sẵn |

**Giữ nguyên, không đổi:** §2 (giả định môi trường), §2b (ba bẫy phiên bản + bảng pin), §4 (cấu trúc repo, chỉ thêm file), §5.1 (capture, RTSP, bảo mật mật khẩu), §5.3–§5.6 (đặc trưng, hiệu chỉnh, phân loại, máy trạng thái), §5.9 (SQLite), §5.10 (web), §7 (CLI, chỉ thêm lệnh con), §9 (kiểm thử).

---

## 1. Mục tiêu và phạm vi

### 1.1 Bài toán

Một người ngồi học một mình trước bàn, camera IP gắn ở góc trước mặt bàn sao cho khung hình thấy được **cả người ngồi và mặt bàn**. Trong khung giờ học đã đặt trước, hệ thống phải trả lời ba câu hỏi ở nhịp vài giây một lần:

1. Người đang học có **còn trong khung hình** không?
2. Người đó có **đang dùng điện thoại** không?
3. Người đang ngồi có **đúng là người đã đăng ký học** không?

Khi câu trả lời là "không tốt" và kéo dài đủ lâu, hệ thống **phát cảnh báo bằng tiếng ra loa của camera**, đồng thời hiện trạng thái trên dashboard web trong LAN.

### 1.2 Mục tiêu kỹ thuật

- Chạy ổn định trên Raspberry Pi 4, **không GPU**, dùng model pretrained, **không huấn luyện lại model**.
- Toàn bộ suy luận trên Pi; ảnh **không** rời khỏi máy, **không** lưu ra đĩa.
- Mọi ngưỡng và lịch đặt trong `config.yaml`.
- Tái sử dụng tối đa hạ tầng v2 đã chạy được (capture RTSP, vòng lặp, web, PTZ, loa camera, storage).

### 1.3 Trong phạm vi

| # | Chức năng | Ghi chú |
| --- | --- | --- |
| 1 | Nhận diện người ngồi có mặt / vắng mặt trong khung | Suy ra từ kết quả model pose, không cần model riêng |
| 2 | Cảnh báo ra **loa camera** khi: ra khỏi khung, dùng điện thoại, người khác ngồi học hộ | Chỉ trong khung giờ học |
| 3 | Phát hiện dùng điện thoại bằng YOLO detect (`cell phone`) + keypoint cổ tay từ pose | Quy tắc "khoảng cách = 0" |
| 4 | Nhận diện khuôn mặt người đang ngồi với người đã đăng ký | YuNet + SFace có sẵn trong `cv2` |
| 5 | Web server hiển thị luồng camera | **Chức năng chính, bật mặc định** (`web.stream_enabled: true`). Tái dùng `/stream` v2 |
| 6 | Thêm người mới: một nút bấm, camera hướng dẫn quay phải/trái/lên/xuống, rồi cập nhật bộ nhận diện | "Train lại" = **tính lại embedding**, không huấn luyện model |
| 7 | Chọn người đang học trong khung hình | Giao diện chọn danh tính |
| 8 | Điều khiển PTZ trái/phải/lên/xuống trong app | Tái dùng `camera_control.py` + `/api/ptz` |
| 9 | Khung giờ học cấu hình được | `schedule` |

### 1.4 Ngoài phạm vi

- Nhận diện hành vi khác (quay cóp, ngủ gật, nói chuyện, rời bàn quá lâu) — không làm trong v3.
- Chấm điểm, xếp hạng, báo cáo phụ huynh qua Internet, ứng dụng mobile riêng, cloud, Telegram.
- Huấn luyện/fine-tune model khuôn mặt hay model detect.
- Chống giả mạo khuôn mặt (ảnh in, video replay) — **ghi nhận là lỗ hổng đã biết**, xem §12.
- Theo dõi nhiều người học cùng lúc (v3 chỉ giám sát **một** người được chọn).

### 1.5 Nguyên tắc

Ưu tiên chạy ổn định hơn độ mới của model; mọi thứ đo được mới được viết vào tài liệu; cảnh báo phải **im khi không chắc** (thà bỏ sót còn hơn báo nhầm liên tục làm người học tắt máy).

---

## 2. Giả định mặc định

Kế thừa nguyên vẹn §2 của v2 (phần cứng, OS, kiến trúc, model, ngôn ngữ). Bổ sung:

| Hạng mục | Giả định |
| --- | --- |
| Camera | Camera IP RTSP có **loa** (đã kiểm chứng: backchannel qua cổng 554, xem `camera_audio.py`) và **PTZ** (đã kiểm chứng: `/api/ptz`) |
| Luồng dùng | Luồng **phụ** (sub-stream) 704x576 @ 20 FPS, HEVC — theo đo của v2 §5.1 |
| Vị trí camera | Cố định, góc trước mặt bàn, thấy cả người và mặt bàn. PTZ chỉ để **chỉnh một lần lúc lắp**, không xoay trong lúc giám sát |
| Số người trong khung lúc giám sát | 1 người được chọn. Có người thứ hai đi qua là **tình huống biên**, xem §3.4 |
| Danh tính | Mỗi người đăng ký có một tên hiển thị; không có tài khoản/mật khẩu người dùng |
| Múi giờ | Giờ Việt Nam (UTC+7), **không có DST**. Lịch học tính theo giờ địa phương của Pi |
| Đồng hồ | Pi bật NTP. Lịch học sai nếu đồng hồ sai — xem §5.14 |
| Người dùng | Người học (không rành kỹ thuật, dùng điện thoại), người giám sát (phụ huynh/giáo viên), người triển khai (admin) |

---

## 2b. Khóa phiên bản bắt buộc

**Không đổi so với v2 §2b.** Ba bẫy (`torch==2.6.0`, `ultralytics` 8.4.0–8.4.3, `opencv-python==4.13.0.90`) và bảng pin giữ nguyên.

Bổ sung cho đề tài mới:

- **Không thêm thư viện nhận diện khuôn mặt nào.** `cv2` 5.0.0 trên Pi **đã có** `FaceDetectorYN_create` và `FaceRecognizerSF_create` (**ĐÃ ĐO**). Không cài `insightface`, `face_recognition`, `dlib` — các gói này kéo theo build C++/model tải từ mạng và không cần thiết.
- **Model khuôn mặt là file rời, tải một lần:** `yunet.onnx` **228 KB**, `sface.onnx` **37 MB** (**ĐÃ ĐO** dung lượng). Đĩa Pi còn **3,1 GB** trống (**ĐÃ ĐO**).
- **`espeak-ng` và `ffmpeg` có sẵn trên Pi** (**ĐÃ ĐO**). `espeak-ng -v vi -w out.wav 'text'` tạo được file WAV tiếng Việt. Lưu ý: `ffmpeg` **không có** trên máy phát triển Windows của dự án, nên đường phát file tiếng Việt chỉ kiểm thử được trên Pi.
- **Không cần thư viện mã hoá nào.** Embedding lưu nhị phân thô (§5.17); mã hoá là hướng mở rộng chưa kiểm chứng (§12), **không** nằm trong đường chạy chính. Không thêm phụ thuộc chưa kiểm chứng vào máy đích khi đĩa chỉ còn 3,1 GB.

---

## 3. Phân tích nghiệp vụ

### 3.1 Người dùng và nhu cầu

| Vai | Cần gì | Ràng buộc |
| --- | --- | --- |
| **Người học** | Biết mình có đang bị nhắc không; không bị làm phiền vô cớ; đăng ký khuôn mặt nhanh | Điện thoại là thiết bị chính để xem dashboard; không đọc hướng dẫn dài |
| **Người giám sát** | Thấy trạng thái hiện tại và lịch sử vi phạm theo giờ; xem được luồng camera khi cần | Không có quyền đăng ký/xoá khuôn mặt (thao tác đó cần có mặt người học) |
| **Người triển khai** | Lắp camera, đặt giờ học, thêm người, kiểm tra loa và PTZ | Có quyền truy cập cấu hình và biến môi trường chứa mật khẩu |

### 3.2 Luồng sử dụng chính

**A. Chuẩn bị một lần (khi lắp máy)**

1. Bật dashboard, mở `/stream`, dùng nút PTZ chỉnh camera cho thấy cả người và mặt bàn. Bấm lưu vị trí (không cần lưu số — camera giữ nguyên vị trí vật lý).
2. Vào mục "Người học" → "Thêm người" → nhập tên.
3. Pi phát hướng dẫn bằng giọng nói ra loa camera: "Nhìn thẳng", "Quay sang phải", "Quay sang trái", "Ngẩng lên", "Cúi xuống" — mỗi bước giữ yên khoảng 1,5 s.
4. Hệ thống thu mẫu, tính embedding cho từng mẫu, **vứt ngay khung hình**, lưu vector `float32` cục bộ.
5. Đặt khung giờ học (ví dụ 19:00–22:00, thứ 2 đến thứ 6).
6. Bấm "Chọn người đang học" cho phiên hiện tại.

**B. Trong giờ học**

1. Hệ thống chạy vòng lặp: pose mỗi khung, detect điện thoại cách khung, nhận diện khuôn mặt định kỳ.
2. Mỗi tín hiệu có bộ lọc thời gian riêng (hold/hysteresis) trước khi thành sự kiện.
3. Sự kiện lọt cooldown → phát cảnh báo ra loa camera + ghi vào SQLite + hiện trên dashboard.
4. Người học quay lại / bỏ điện thoại → sự kiện kết thúc, hệ thống im.

**C. Ngoài giờ học** — không cảnh báo, chỉ ghi số liệu tối thiểu để biết hệ thống còn sống.

### 3.3 Quy tắc phát cảnh báo (hợp nhất ba tín hiệu)

| Tín hiệu | Điều kiện "xấu" | Nguồn | Ghi chú |
| --- | --- | --- | --- |
| `ABSENT` | Người được chọn không còn trong khung | Pose/tracking | **Không** dùng "có ai đó trong khung" làm điều kiện đúng — xem §3.4 |
| `PHONE_USE` | Cổ tay nằm trong hộp bao `cell phone`, giữ liên tục `phone_hold_s` | Pose + detect | Quy tắc "khoảng cách = 0", định nghĩa ở §5.12 |
| `IMPOSTOR` | Danh tính nhận được **khác** người đã chọn, liên tục `impostor_hold_s`, với độ tin cậy trên ngưỡng | YuNet + SFace | Có đường "không nhận ra" tách khỏi "nhận ra người khác" — §5.13 |

Luật chung:

- Chỉ phát khi `schedule` đang mở.
- Dùng lại đúng cơ chế hold/hysteresis/cooldown của v2 §5.6 (`bad_hold_s`, `good_hold_s`, `alert_cooldown_s`, `escalate_after_s`) — không viết cơ chế thứ hai.
- Cảnh báo phát ra loa camera là **âm thanh ngắn** (mặc định tiếng bíp + câu tiếng Việt). Không phát lặp lại mỗi khung.
- Dashboard tắt tiếng (`muted`) thì **không phát ra loa** nhưng vẫn ghi sự kiện — giữ đúng hành vi v2 `WEB_DASHBOARD.md` §2.2.

### 3.4 Tình huống biên (bắt buộc xử lý, không được crash)

| Tình huống | Hành vi mong muốn |
| --- | --- |
| Người học ra khỏi khung, **người khác** đi vào | Vẫn là `ABSENT` (đang xét người được chọn), **không** báo `IMPOSTOR` — người kia không ngồi vào vị trí |
| Người khác **ngồi vào bàn** thay người học | `IMPOSTOR`, sau `impostor_hold_s` |
| Khuôn mặt bị che (khẩu trang, tay, ánh sáng ngược) | `UNKNOWN` — **không** báo `IMPOSTOR`. Báo nhầm vì không nhận ra là lỗi nghiêm trọng hơn bỏ sót |
| Chỉ có một phần khuôn mặt trong khung | YuNet không trả khuôn mặt → `UNKNOWN`, giữ nguyên trạng thái trước đó, không leo thang |
| Điện thoại nằm trên bàn cạnh tay, không cầm | Không báo. Quy tắc đòi **cổ tay nằm trong hộp bao**, không phải chỉ gần |
| Hai tay gõ phím, điện thoại kê dưới tay | Có thể báo nhầm — ghi nhận là hạn chế đã biết (§12), giảm bằng `phone_hold_s` |
| Camera bị xoay (PTZ) giữa phiên | Track id mất → khoảng ân hạn `absent_grace_s` trước khi coi là vắng; không báo ngay |
| Mất mạng / camera rớt RTSP | Vòng lặp vẫn chạy, ghi log; cảnh báo ra loa thất bại thì ghi sự kiện `SPEAK_FAILED`, không crash |
| Loa camera đang bận (lần phát trước chưa xong) | Bỏ lần phát mới (không xếp hàng dài), ghi log — chính sách "mất cảnh báo còn hơn trễ 30 s" |
| Giờ học vắt qua nửa đêm (22:00–02:00) | Phải tính đúng, test riêng |
| Giờ học có ngày nghỉ (thứ 7, CN) | Cấu hình theo thứ trong tuần |
| Đồng hồ Pi sai (mất NTP, pin RTC yếu) | Dashboard hiện cảnh báo; **không** cảnh báo hành vi khi đồng hồ lệch quá `clock_skew_warn_s` so với thời điểm lần đồng bộ cuối |
| Đăng ký khuôn mặt bị ngắt giữa chừng | Không ghi danh tính nửa vời: hoặc đủ mẫu và ghi, hoặc bỏ toàn bộ |
| Hai người đăng ký trông giống nhau | Nhận nhầm — ghi nhận hạn chế, ngưỡng do người triển khai chỉnh |
| Không có khuôn mặt nào đăng ký | Chức năng 4 tự tắt, các chức năng khác chạy bình thường; dashboard ghi rõ "chưa có ai được đăng ký" |

---

## 4. Kiến trúc

### 4.1 Sơ đồ luồng dữ liệu

```
                    camera IP (RTSP sub-stream 704x576 @20)
                                   |
                          CaptureThread (v2 §5.1)
                                   | khung mới nhất (bỏ khung cũ)
                    +--------------+-------------------+
                    |                                  |
              InferenceLoop                      Web/Stream
                    |                            (v2 §5.10)
        +-----------+-----------+--------------+
        |                       |              |
  PoseEstimator(v2)      PhoneDetector   FaceWorker (luồng riêng)
  yolo11n-pose NCNN      yolo11n NCNN    YuNet + SFace
  MỖI KHUNG              1 / 2 KHUNG     mỗi N giây
        |                       |              |
   keypoints+bbox          hộp cell phone   embedding + khoảng cách
        |                       |              |
        +-----------+-----------+--------------+
                    |
            SignalFusion (presence / phone / identity)
                    |
             ScheduleGate (chỉ mở trong giờ học)
                    |
              StateMachine (v2 §5.6 — hold, hysteresis, cooldown)
                    |
        +-----------+------------+------------------+
  SpeakerAlerter            Storage (v2 §5.9)      Web (v2 §5.10)
  (loa camera, backchannel)  sự kiện, số liệu      dashboard + API
```

Quy tắc luồng:

- Ảnh **không** đi vào `Storage` dưới bất kỳ dạng nào.
- `FaceWorker` chạy **luồng riêng**, không chặn vòng lặp pose/detect (**GIẢ THIẾT** — phải đo tranh chấp CPU, xem §14 bước G).
- `ScheduleGate` là cổng duy nhất quyết định "có phát cảnh báo hay không"; module nào khác không được tự đọc giờ.
- Giao tiếp với web vẫn qua `DashboardState` như v2 (`WEB_DASHBOARD.md` §2) — vòng lặp không chạm Flask.

### 4.2 Chu kỳ chạy từng model

| Model | Chu kỳ | Chi phí | Trạng thái số liệu |
| --- | --- | --- | --- |
| `yolo11n-pose` NCNN @320 | **mỗi khung** | 105,5–112,5 ms/khung, 1 lớp `person` | **ĐÃ ĐO** |
| `yolo11n` (detect) NCNN @320 | **mỗi 2 khung** | 98,6 ms/lần chạy | **ĐÃ ĐO** (thời gian một lần chạy) |
| **Cả đường ống khuôn mặt** @320x262 (thu nhỏ + CLAHE + YuNet + alignCrop + SFace feature) | mỗi `face_interval_s` (mặc định 2 s) **hoặc** khi có người mới vào khung | **86,1 ms/lượt → 11,6 lượt/giây** | **ĐÃ ĐO** |

Số **ĐÃ ĐO** ngày 2026-10-29, trên Pi 4, khung thật từ camera của dự án (704x576):

| Phép đo | Thời gian |
| --- | --- |
| YuNet ở 704x576 (không thu nhỏ) | 99,9 ms/lần |
| YuNet ở 320x262 (thu nhỏ trước) | **19,3 ms/lần** — nhanh gấp ~5 lần, vẫn tìm được khuôn mặt |
| CLAHE (LAB, clipLimit 2,0, tile 8x8) ở 320x262 | 11,4 ms/lần |
| **Trọn đường ống @320x262** (thu nhỏ + CLAHE + YuNet + alignCrop + SFace) | **86,1 ms → 11,6 lượt/giây** |

> **ĐÍNH CHÍNH số liệu cũ.** Bản trước của tài liệu ghi "YuNet 75,0 ms/khung; SFace 63,8 ms/khuôn mặt". Hai số đó **sai để dùng làm căn cứ thiết kế**: 75 ms đo trên một khung **tổng hợp** (ảnh đen vẽ blob), không đại diện cho khung thật; và hai phép đo riêng lẻ không cộng gộp đúng thành chi phí đường ống. Số đúng là bảng trên. Mọi tính toán ngân sách dùng 86,1 ms, **không** dùng 138,8 ms.

Lý do chu kỳ khác nhau:

- **Pose mỗi khung** vì presence và quy tắc bàn tay đều cần keypoint, và đây là tín hiệu tươi nhất.
- **Detect điện thoại cách khung** vì đo thật cho thấy chạy cả hai mỗi khung chỉ đạt **4,74–4,90 FPS**, dưới mục tiêu 5 FPS (**ĐÃ ĐO**). Cách khung đạt **6,18 FPS**.
- **Khuôn mặt không chạy mỗi khung**: 86,1 ms cho một lượt (đường ống đầy đủ). Chạy mỗi khung sẽ ăn gần một nửa ngân sách 200 ms chỉ cho danh tính — trong khi danh tính không đổi sau vài trăm ms. Chu kỳ 2 s là đủ và rẻ (≈7,2 ms/khung khi chạy 6 FPS).

### 4.3 Ngân sách FPS

Mô hình chi phí một khung (**TÍNH TỪ ĐO**): `T_khung ≈ T_pose + (T_detect nếu khung này chạy detect)`. Kiểm chứng lại với số đo:

| Cấu hình | Tính ra | Đo được | Khớp |
| --- | --- | --- | --- |
| pose + detect mỗi khung | 105,5+98,6 = 204,1 ms → 4,90 FPS<br>112,5+98,6 = 211,1 ms → 4,74 FPS | 4,74–4,90 FPS | **khớp** |
| pose mỗi khung + detect 1/2 khung | ≈109,0 + 49,3 = 158,3 ms → 6,32 FPS | 6,18 FPS | khớp trong ~2% |

Nghĩa là chi phí pipeline gần như chỉ là hai lần suy luận, phần quản lý vòng lặp không đáng kể. Đây là cơ sở để lập ngân sách **GIẢ THIẾT**:

| Hạng mục | Chi phí mỗi khung (trung bình) | Căn cứ |
| --- | --- | --- |
| pose | 109,0 ms (trung bình hai đầu 105,5–112,5) | **ĐÃ ĐO** |
| detect điện thoại, 1/2 khung | 49,3 ms | **TÍNH TỪ ĐO** |
| Cả đường ống khuôn mặt, chu kỳ 2 s @ ~6 FPS (≈12 khung) | ≈7,2 ms | **TÍNH TỪ ĐO** (86,1 / 12) |
| **Tổng** | **≈165,5 ms → 6,04 FPS** | **GIẢ THIẾT — chưa đo cấu hình này** |
| Ngân sách để đạt 5 FPS | 200 ms | mục tiêu §8 |

**Kết luận phải nói rõ:** con số 6,04 FPS là **suy ra**, không phải đo. Cấu hình ba model chạy cùng nhau trên Pi **chưa từng được đo**. Nếu chi phí thật vượt ngân sách, thứ tự cắt giảm là:

1. Giãn `face_interval_s` lên 3–5 s.
2. Đổi detect điện thoại sang 1/3 khung.
3. Giảm `imgsz` 320 → 256 (áp cho cả ba model).
4. Giảm `target_fps` xuống 4.
5. Dừng và báo người dùng — **không** tự đổi sang model khác ngoài danh sách.

---

## 5. Chi tiết từng module

Phần này chỉ mô tả **module mới và phần sửa**. `capture.py`, `features.py`, `calibration.py`, `classifier.py`, `state.py`, `sensors.py`, `storage.py` (phần lõi), `web/` (phần lõi) giữ nguyên v2.

### 5.1 capture.py — không đổi

Dùng `RTSPSource` của v2. Nhắc lại hai điều bắt buộc: xả đệm mỗi lần `read()`; URL có mật khẩu **không** nằm trong file commit (chỉ `config.local.yaml` hoặc `POSTURE_CAMERA_SOURCE`). Không có gì mới.

### 5.2 pose.py — bổ sung model thứ hai, không đổi model thứ nhất

`PoseEstimator` giữ nguyên: trả `xy`, `conf`, `bbox` của một người, có tracking theo track id.

Bổ sung:

- **`last_person_count`** (đã có trong mã) được dùng làm đầu vào presence.
- `PhoneDetector` là lớp **mới, riêng**, nạp `yolo11n.pt` → NCNN theo đúng cơ chế `PoseEstimator` (cùng hàm export, cùng đường fallback NCNN → ONNX → pt). Không gộp vào `PoseEstimator` để hai model có chu kỳ độc lập.
- Tham số `model.phone_detect_every_n_frames` (mặc định 2) điều khiển chu kỳ.
- **Giới hạn tài nguyên:** hai model NCNN nạp đồng thời. Dung lượng thư mục NCNN của detect và tổng RAM khi chạy hai model **CHƯA ĐO** — xem §14 bước G.

### 5.3–5.6 features / calibration / classifier / state — không đổi

`state.StateMachine` được **dùng lại nguyên vẹn** cho các nhãn mới: nó chỉ phụ thuộc `Classifier` nhãn và `TimingConfig`, không biết gì về camera. Việc thêm nhãn mới là thêm hằng số nhãn + luật, **không** thêm cơ chế thời gian thứ hai.

Nhãn tư thế của v2 (`HEAD_DOWN`, `TOO_CLOSE`, …) **vẫn còn trong mã** nhưng **tắt mặc định** trong v3 (`posture_labels_enabled: false`) — đề tài không còn yêu cầu cảnh báo tư thế, và chạy cả hai bộ luật sẽ tăng báo nhầm. Không được xoá mã v2 chỉ vì v3 không dùng: nó đã có test.

### 5.7 alerts.py / hardware — kênh cảnh báo chính đổi

- `AlertDispatcher` (v2) vẫn dùng cho **LED/buzzer GPIO** nhưng **tắt mặc định** trên triển khai v3 (`alerts.gpio_alert_enabled: false`).
- Cảnh báo chính đi qua `SpeakerAlerter` (§5.15) tới loa camera.
- Vẫn giữ nguyên tắc v2: phần cứng thiếu thì bỏ qua và ghi log, không crash.

### 5.11 presence.py (mới)

Trả lời câu hỏi 1: **người được chọn có còn trong khung không**.

- Đầu vào: `PoseResult` + track id của người đang bám (từ `PoseEstimator`).
- Có mặt = `last_person_count > 0` **và** track đang bám còn được thấy trong khung.
- Không thấy người nào → `ABSENT` sau `absent_grace_s` (mặc định 3 s, ngắn hơn `absent_reset_s` của v2 vì đề tài cần phản ứng nhanh hơn).
- Không có model riêng: model pose đã có lớp `person` (**ĐÃ ĐO**: 1 lớp `person`), thêm model thứ ba chỉ để biết "có người" là lãng phí ngân sách FPS.
- **Không** dùng hộp bao lớn nhất (v2 §5.6 đã sửa lỗi này): phải theo track id, nếu không thì khi người khác đi qua, trạng thái nhảy.
- Viết log ở mức INFO mỗi lần chuyển PRESENT ↔ ABSENT, không log mỗi khung.

### 5.12 phone.py (mới)

Trả lời câu hỏi 2: **có đang dùng điện thoại không**.

**Định nghĩa "khoảng cách = 0" theo đề tài, phát biểu chính xác:**

> Gọi `P` là tập keypoint cổ tay (COCO index 9 = cổ tay trái, 10 = cổ tay phải) có `conf >= kp_conf_min`.
> Gọi `B` là hộp bao của mọi phát hiện lớp `cell phone` trong khung.
> Khoảng cách `d = 0` khi **tồn tại** `p ∈ P` và `b ∈ B` sao cho `p` nằm **trong** hoặc **trên biên** của `b`.
> Khi đó khung được đánh dấu `PHONE_TOUCH`.

Chi tiết triển khai:

- Khoảng cách điểm–hình chữ nhật là 0 khi điểm nằm trong; công thức dùng chung `point_rect_distance(p, b)` để sau này nới ra `touching_slack_px` nếu đo thực tế cho thấy cần.
- Chỉ keypoint cổ tay, **không** dùng khuỷu/vai: cổ tay là bộ phận thật sự cầm máy, và keypoint vai/khuỷu tin cậy cao nhưng quá xa để nói "đang cầm".
- Ngưỡng conf của keypoint lấy từ `model.kp_conf_min` (v2). Cổ tay thường có conf cao hơn tai nhiều; nếu conf thấp thì **không** kết luận (không đoán).
- Detect chạy mỗi `phone_detect_every_n_frames` khung; **giữ hộp bao của lần detect gần nhất** cho các khung ở giữa, cùng với tuổi của hộp. Hộp cũ hơn `phone_box_ttl_s` (mặc định 0,5 s) thì bỏ, không dùng.
- Kiểm tra giao chỉ khi khung đó có keypoint cổ tay tin cậy **và** có hộp bao còn hạn.
- `phone_hold_s` (mặc định 2 s) liên tục mới thành sự kiện; dùng `bad_hold_s` của v2 nếu cấu hình muốn thống nhất.
- Điện thoại **không** phải là lý do để bỏ qua presence: hai nhãn độc lập.

**Vì sao dùng model của chính dự án:** đề tài chỉ định rõ dùng YOLO detect của project. Không dùng model điện thoại bên thứ ba, không dùng heuristic màu/hình dạng.

### 5.13 faces.py (mới)

Trả lời câu hỏi 3 và cung cấp chức năng 6, 7.

**Công cụ (ĐÃ ĐO là có sẵn trên `cv2` 5.0.0 của Pi):**

| Việc | API |
| --- | --- |
| Tìm khuôn mặt + 5 điểm mốc | `cv2.FaceDetectorYN_create("yunet.onnx", ...)` |
| Căn chỉnh khuôn mặt về 112x112 | `cv2.FaceRecognizerSF.alignCrop(img, face_row)` |
| Trích đặc trưng | `cv2.FaceRecognizerSF_create("sface.onnx", ...)` → `feature()` → vector **128 chiều** |

Toàn bộ đường ống đã đo trên Pi 4 với khung thật: **86,1 ms/lượt, 11,6 lượt/giây** (§4.2).

#### Ràng buộc kỹ thuật bắt buộc (từ số đo, không phải tùy tiện)

**(1) Phải thu nhỏ khung về 320 trước khi detect.** Ở 704x576, YuNet tốn **99,9 ms**; ở 320x262 chỉ **19,3 ms** — nhanh gấp ~5 lần và **vẫn tìm được khuôn mặt**. Vậy module `faces` **bắt buộc** `cv2.resize` khung về chiều rộng `face_detect_width: 320` (giữ tỉ lệ, 704x576 → 320x262) rồi mới đưa vào YuNet. Đây là quyết định dựa trên đo, không phải tuỳ tiện; chạy nguyên 704x576 là chọn cấu hình **chậm hơn 5 lần** mà không được thêm gì.

**(2) Phải trả hộp khuôn mặt về hệ pixel của khung gốc.** YuNet ở 320x262 trả toạ độ trong hệ 320. Trả nguyên hệ đó lên tầng trên là **sai** — mọi phép vẽ overlay, so khớp với keypoint (hệ 704x576) và tính khoảng cách đều lệch theo tỉ lệ `704/320 = 2,2` lần. Bắt buộc nhân ngược:

```
scale_x = frame_w / detect_w      # 704 / 320 = 2.2
scale_y = frame_h / detect_h      # 576 / 262 ≈ 2.198
box_goc = (x, y, w, h) * (scale_x, scale_y, scale_x, scale_y)
```

**Đây là điều khoản hợp đồng dữ liệu:** `FaceDetector.detect()` trả hộp **luôn ở hệ pixel của khung gốc** mà nó nhận vào. Tầng trên không được biết tới hệ 320. Đã kiểm chứng: hộp tìm được ở hệ 320 được ánh xạ ngược thành `[158.9, 214.4, 123.0, 216.6]` và nằm gọn trong khung 704x576 (**ĐÃ ĐO**). Unit test bắt buộc cho phép ánh xạ này.

**(3) Bật CLAHE mặc định — biện pháp phòng ngừa, không phải điều kiện để chạy.** CLAHE trong không gian LAB, `clipLimit=2.0`, `tileGridSize=8x8`, chạy ở hệ 320x262, tốn **11,4 ms** (**ĐÃ ĐO**) — rẻ so với 86,1 ms của cả đường ống, nên bật mặc định.

Bằng chứng hai chiều (đo trên Pi, khung thật, 2026-10-29):

| Lần đo | Ảnh thô | Sau CLAHE |
| --- | --- | --- |
| Khung đầu tiên, độ sáng trung bình 99,6 (ngược sáng mạnh) | **0 khuôn mặt** | **1 khuôn mặt**, score 0,806 |
| 12 khung thật liên tiếp, độ sáng 110,8–111,0 | 1 khuôn mặt ở **cả 12** khung | 1 khuôn mặt ở **cả 12** khung, score 0,919–0,923 |

Đọc đúng bảng này: CLAHE **cứu được một ca khó thật** (ngược sáng mạnh), nhưng ở điều kiện sáng bình thường của chính bộ 12 khung đó, **thô và CLAHE cho kết quả như nhau**. Vì vậy:

- CLAHE là **biện pháp phòng ngừa** cho ngược sáng, **không** phải điều kiện bắt buộc để hệ thống chạy được.
- **Không được cam kết** "nhờ CLAHE là luôn thấy mặt". Một khung cứu được không chứng minh được điều đó.
- Độ chính xác của CLAHE trên nhiều điều kiện chiếu sáng khác nhau (tối, đèn vàng, có bóng đổ, ngược sáng vừa) **là câu hỏi mở cần đo** — xem §15.

**Hai lớp tách biệt, không trộn:**

1. **`FaceMatcher`** — thuần số học: cho một embedding, so cosine với gallery, trả `(person_id | None, score)`. Không đọc ảnh, không cầm camera. Test được bằng vector tổng hợp.
2. **`FaceWorker`** — vòng đời: nhận khung từ vòng lặp, chạy YuNet/SFace trong luồng riêng, cập nhật kết quả danh tính mới nhất. Không chặn vòng lặp chính.

**Ba kết quả danh tính, không phải hai:**

| Kết quả | Điều kiện | Ảnh hưởng |
| --- | --- | --- |
| `MATCH` | `score >= face_match_threshold` với một người trong gallery | Đúng người, im |
| `MISMATCH` | Khuôn mặt tìm thấy, so với mọi người đều dưới ngưỡng | Ứng viên `IMPOSTOR`, cần hold |
| `UNKNOWN` | Không tìm thấy khuôn mặt, chất lượng thấp, hoặc gallery rỗng | **Không** ảnh hưởng trạng thái; giữ nguyên kết luận trước |

`UNKNOWN` là thiết kế có chủ đích: hệ thống **không được** suy "không nhận ra ⇒ người lạ". Che mặt, quay đi, ngược sáng đều dẫn tới `UNKNOWN`.

**Ngưỡng `face_match_threshold`:** **chưa có số đo** về phân bố score giữa chính chủ và người khác. Đã đo được score phát hiện của YuNet (0,806 / 0,919–0,923) và biết SFace trả vector 128 chiều, nhưng **chưa** đo cosine giữa hai người khác nhau trên camera này. Không được chép ngưỡng từ tài liệu OpenCV hay từ repo khác vào làm mặc định "đã kiểm chứng". Trước M10 phải thu một tập mẫu (chính chủ / người khác / che mặt) và chọn ngưỡng theo bảng đo, ghi vào `config.yaml` kèm ghi chú ngày đo. Xem §14 bước H.

**Đăng ký người mới (chức năng 6):**

- Một nút trên dashboard → `POST /api/enroll/start {"name": "..."}`.
- Trình tự hướng dẫn (5 tư thế): nhìn thẳng → quay phải → quay trái → ngẩng → cúi. Mỗi tư thế `enroll_step_s` (mặc định 1,5 s), tổng ~7,5 s.
- Hướng dẫn phát **ra loa camera** bằng giọng tiếng Việt (espeak-ng sinh WAV → `speak_file`), đồng thời hiện chữ trên web. Phát giọng là để người đứng xa màn hình vẫn làm đúng, không phải để trang trí.
- Với mỗi tư thế, lấy các khung có `conf` YuNet trên ngưỡng, tính embedding, **giữ lại vector**; khung hình bị **vứt ngay** trong cùng lần lặp.
- Đủ tối thiểu `enroll_min_samples` (mặc định 3) embedding hợp lệ thì ghi; thiếu thì trả lỗi tiếng Việt và **không** ghi gì.
- **"Train lại bộ nhận diện" trong đề tài hiểu là: tính lại embedding và dựng lại gallery.** SFace là model pretrained đóng băng, không fine-tune trên Pi (không đủ dữ liệu, không đủ thời gian, và sẽ phá tính "pretrained, không huấn luyện" của v2 §1). Tài liệu và UI phải dùng chữ "cập nhật bộ nhận diện", **không** dùng "huấn luyện". Nếu người dùng thật sự muốn huấn luyện/fine-tune thì đó là yêu cầu mới, cần người quyết định, không tự làm.
- Xoá người: xoá bản ghi + vector, không để lại file ảnh nào (vì không có file ảnh).

**Dung lượng:** một embedding SFace là vector `float32` **128 chiều** = 512 byte (**ĐÃ ĐO** số chiều). 100 người × 3 mẫu ≈ 150 KB — không đáng kể so với 3,1 GB trống. Không cần cơ chế nén; lưu nhị phân thô (§5.17).

#### 5.13.1 Quyền riêng tư — cam kết bắt buộc

Đây là **ràng buộc cứng**, không phải khuyến nghị. Nó giữ nguyên phần cốt lõi của v2 §11.5 — **không lưu, không truyền ảnh ra ngoài** — nhưng **thay đổi một điểm so với v2**: hiển thị trực tiếp trên web là chức năng chính của đề tài, nên `web.stream_enabled` mặc định **bật** (xem §5.16).

**Phân biệt bắt buộc — HIỂN THỊ khác LƯU.** Người dùng xem được camera trên dashboard, nhưng khung hình **chỉ tồn tại trong RAM**:

| Khía cạnh | Hiển thị (`/stream`) | Lưu |
| --- | --- | --- |
| Bật mặc định | **Có** — chức năng chính | **Không bao giờ** |
| Vòng đời khung | Chỉ trong bộ nhớ, `DashboardState` giữ **một** khung mới nhất, khung cũ bị thay | — |
| Ghi xuống đĩa | Không | Không |
| Lịch sử phát lại | Không | Không |
| Route trả file ảnh | Không có | Không có |
| Ra khỏi mạng LAN | Không khuyến khích (giữ nguyên v2 §5.10) | — |

| Quy tắc | Cách thực hiện |
| --- | --- |
| **Không lưu ảnh khuôn mặt** | Khung hình chỉ tồn tại trong RAM trong đúng lời gọi `feature()`. Vứt ngay sau đó. Không có `cv2.imwrite`, không có buffer ghi đĩa trong đường này |
| **Chỉ lưu embedding** | Gallery lưu vector + `person_id` + tên + thời điểm tạo + phiên bản model. Không lưu crop, không lưu ảnh nguồn |
| **Embedding lưu cục bộ, không mã hoá ở v3** | Vector `float32` ghi trong CSDL/thư mục dữ liệu **trên chính Pi**. Quyền file hệ điều hành là lớp bảo vệ duy nhất. Mã hoá khi lưu là **hướng mở rộng chưa kiểm chứng** (§12), **không** phải tiêu chí nghiệm thu |
| **Vector không ra khỏi Pi** | Không có route HTTP nào trả embedding. Dashboard chỉ trả tên và kết quả khớp |
| **`/stream` bật mặc định, không lưu gì** | `web.stream_enabled: true`. Khung đi thẳng từ bộ nhớ ra HTTP MJPEG, không chạm đĩa. Vẫn làm mờ mọi người **không phải** người đang học bằng `ObjectBlurrer` (v2 §5.10) |
| **Màn hình đăng ký** | Hiện khung hình để người dùng tự canh, tắt ngay khi hết bước. Không phải nguồn lưu |
| **Xoá là xoá thật** | Xoá danh tính thì xoá luôn file vector, không để "thùng rác" |
| **Log** | Không log đường dẫn ảnh (không có ảnh), không log vector, không log mật khẩu camera. Mọi chuỗi có URL camera đi qua `redact_camera_source` |

**Ghi chú pháp lý (cần người dùng xác nhận, không phải kết luận của tài liệu):** dữ liệu sinh trắc học (khuôn mặt) là **dữ liệu cá nhân nhạy cảm** theo Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân. Việc thu thập cần có sự đồng ý của chính người được đăng ký. Thiết kế trên (chỉ lưu vector, không lưu ảnh, không truyền ra ngoài, xoá được) giảm rủi ro nhưng **không tự động** tạo ra sự tuân thủ. Người quyết định sản phẩm phải xác nhận phạm vi sử dụng trước khi triển khai ngoài phòng thí nghiệm.

### 5.14 schedule.py (mới)

Trả lời "có đang trong giờ học không".

- Cấu hình theo **thứ trong tuần + khoảng giờ**, hỗ trợ nhiều khung trong một ngày và khung vắt qua nửa đêm.
- Dạng cấu hình: danh sách `{days: [2,3,4,5,6], start: "19:00", end: "22:00"}` với `days` theo ISO (1 = thứ 2, 7 = chủ nhật).
- `is_open(now)` nhận **thời điểm từ ngoài** (giây epoch hoặc `datetime` đã có timezone), giống cách `state.py` nhận `now` — để test bằng đồng hồ giả, không phụ thuộc `time.time()` bên trong.
- Vắt qua nửa đêm: `start > end` nghĩa là qua ngày hôm sau; `days` được hiểu là ngày **bắt đầu**.
- Không có ngày lễ. Nếu cần nghỉ, người dùng sửa cấu hình hoặc dùng một khung giờ rỗng.
- **Kiểm tra đồng hồ:** đọc độ lệch NTP nếu đọc được; không đọc được thì không chặn. Lệch quá `clock_skew_warn_s` → dashboard hiện cảnh báo và **tắt phát cảnh báo** (vì có thể đang ngoài giờ học thật).
- Ghi log mỗi lần cổng mở/đóng.

### 5.15 speaker_alert.py (mới)

Đưa cảnh báo ra **loa của camera IP** (chức năng 2).

- **Tái dùng `camera_audio.SpeakController`** đã có: nó đã tự sinh G.711 cho tiếng bíp **không cần ffmpeg**, có khoá chống hai luồng cùng đẩy RTP, có chặn thời lượng, có che mật khẩu trong log, và import an toàn khi thiếu `rtsp-backchannel`.
- **Đã chạy thật trên camera của dự án (2026-10-29):** `SpeakResult(mode='tone', codec='PCMA', sample_rate=8000, packets_sent=20, duration_seconds=0.8)` — 20 gói RTP PCMU/PCMA ở 8 kHz đã tới camera và ra loa. Đây là bằng chứng chức năng 2 **khả thi về kênh truyền**, không còn là giả thuyết. Điều này **không** chứng minh câu tiếng Việt do espeak-ng sinh nghe rõ — xem §18 điểm 2.
- `SpeakerAlerter` chỉ là lớp quyết định **phát gì, khi nào**:
  - `ABSENT` → câu "Bạn ơi, quay lại bàn học nhé" (WAV sinh sẵn bằng espeak-ng, phát qua `speak_file`).
  - `PHONE_USE` → câu "Cất điện thoại và tập trung học nhé".
  - `IMPOSTOR` → câu "Người đang ngồi không phải người đã đăng ký học".
- **Quy ước sinh âm thanh:** file WAV tiếng Việt được sinh **một lần lúc khởi động** (hoặc lúc cấu hình đổi) bằng `espeak-ng -v vi -w`, lưu trong `data/audio/`. Sinh lại mỗi lần cảnh báo là lãng phí và gây trễ.
- `speak_file` cần `ffmpeg`; **ĐÃ ĐO**: Pi có `ffmpeg`, máy Windows phát triển không có. Nếu thiếu ffmpeg → rơi về tiếng bíp (`speak_tone`) thay vì im lặng, và ghi log một lần.
- Loa bận (`CameraAudioBusy`) → **bỏ** lần phát, ghi log; không xếp hàng.
- Không phát hai cảnh báo chồng nhau. Nếu hai sự kiện cùng lúc, thứ tự ưu tiên: `IMPOSTOR` > `ABSENT` > `PHONE_USE` (người lạ ngồi vào là nghiêm trọng nhất).
- Giới hạn tần suất: `alert_cooldown_s` của v2 đã lo; alerter **không** đếm lại lần nữa.
- Mọi lỗi loa (mất mạng, thiếu thư viện, camera từ chối backchannel) → ghi sự kiện `SPEAK_FAILED` và **tiếp tục chạy**. Không được crash, không được làm rơi vòng lặp camera.

### 5.16 web — bổ sung route và giao diện

Giữ nguyên toàn bộ route v2 (`/`, `/api/status`, `/api/history`, `/api/calibrate`, `/api/mute`, `/api/speak`, `/api/ptz`, `/stream`). Thêm:

| Route | Kiểu | Mô tả |
| --- | --- | --- |
| `GET /api/people` | JSON | Danh sách người đã đăng ký: `id`, `name`, `created_ts`. **Không** trả embedding |
| `POST /api/people` | JSON | Bắt đầu đăng ký: `{"name": "..."}` → trả `{"enroll_id", "steps": [...]}` |
| `GET /api/enroll/<id>` | JSON | Tiến độ: bước hiện tại, số mẫu hợp lệ, lỗi |
| `POST /api/enroll/<id>/cancel` | JSON | Huỷ, không ghi gì |
| `DELETE /api/people/<id>` | JSON | Xoá danh tính + vector |
| `POST /api/select` | JSON | Chọn `person_id` đang học cho phiên hiện tại |
| `GET /api/schedule` / `PUT /api/schedule` | JSON | Đọc/ghi khung giờ học |
| `GET /api/signals` | JSON | Tín hiệu thô gần nhất: presence, phone, identity + tuổi của mỗi tín hiệu |

UI:

- Thẻ "Trạng thái học" thay thẻ "Tư thế": ba dòng (Có mặt / Điện thoại / Danh tính), mỗi dòng màu + biểu tượng + chữ (giữ nguyên tắc v2 không truyền đạt chỉ bằng màu).
- Nút "Thêm người" mở luồng đăng ký có hướng dẫn từng bước.
- Nút "Chọn người đang học".
- **Bốn nút PTZ — chưa tồn tại, phải làm mới.** Route `/api/ptz` đã có và đã test, nhưng `index.html` hiện **không** có nút nào và `app.js` **không** gọi `/api/ptz` lần nào. Ba lớp lỗi phải sửa đồng thời; xem §17.
- **`/stream` hiển thị ngay trên trang chủ** (không ẩn sau tab), vì đây là chức năng chính. Khung hình do `/stream` trả về không đi vào bảng hay lịch sử nào.
- **Tuổi tín hiệu hiển thị được:** mỗi tín hiệu có `age_s`; nếu một tín hiệu cũ hơn ngưỡng của nó, UI phải nói "chưa có dữ liệu mới" thay vì hiện kết luận cũ như mới. Đây là yêu cầu chống hiểu nhầm, không phải chi tiết trang trí.

### 5.17 storage.py — bổ sung bảng, không lưu ảnh

Giữ nguyên ba bảng v2 (`sessions`, `events`, `minute_stats`). Thêm:

```sql
CREATE TABLE IF NOT EXISTS people (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    created_ts  REAL NOT NULL,
    model_ver   TEXT NOT NULL,      -- phiên bản sface, để biết khi nào gallery cũ
    sample_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS face_embeddings (
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    vector      BLOB NOT NULL,      -- float32 thô, 128 chiều × 4 byte = 512 byte
    PRIMARY KEY (person_id, idx)
);
```

- `vector` là `numpy.float32` 128 chiều (**ĐÃ ĐO**: SFace trả vector 128 chiều) đóng gói bằng `tobytes()`; đọc lại bằng `np.frombuffer(..., dtype=np.float32)`. Dung lượng: 512 byte/embedding, 3 mẫu/người ≈ 1,5 KB/người.
- **Không mã hoá ở v3.** Bảo vệ dựa vào quyền file hệ điều hành và việc không có route nào trả vector. Mã hoá khi lưu là hướng mở rộng, xem §12.

- `events.type` thêm các giá trị: `PHONE_USE`, `ABSENT`, `IMPOSTOR`, `UNKNOWN`, `SPEAK_FAILED`, `ENROLL`.
- **Không** có bảng nào chứa ảnh, đường dẫn ảnh, hay JPEG/BLOB hình ảnh. Cột `vector` chứa **số thực**, không phải dữ liệu hình — không thể dựng lại khuôn mặt từ đó nếu không có model, nhưng vẫn là dữ liệu sinh trắc học; xem §5.13.1 và §15.
- Giữ nguyên v2: ghi theo lô, `retention_days`, lỗi DB không được giết chương trình. Bảng `people`/`face_embeddings` **không** bị `retention_days` xoá — dữ liệu đăng ký là cấu hình, không phải log.

---

## 6. Cấu hình mẫu (phần thêm vào `config.yaml`)

```yaml
model:
  # giữ nguyên khối v2
  phone_detect_model: yolo11n   # model detect thứ hai, riêng cho điện thoại
  phone_detect_every_n_frames: 2

face:
  enabled: true
  detector: yunet.onnx          # 228 KB
  recognizer: sface.onnx        # 37 MB
  interval_s: 2.0               # KHÔNG chạy mỗi khung (ngân sách §4.3)
  match_threshold: null         # BẮT BUỘC đặt sau khi đo — xem §5.13, §14 bước H
  impostor_hold_s: 5.0
  enroll_step_s: 1.5
  enroll_min_samples: 3
  detect_width: 320             # BẮT BUỘC thu nhỏ trước khi detect (§5.13)
  clahe_enabled: true           # phòng ngừa ngược sáng, 11,4 ms — rẻ

phone:
  box_ttl_s: 0.5                # hộp bao detect còn dùng được bao lâu
  hold_s: 2.0                   # thấy liên tục bao lâu thì thành sự kiện
  touching_slack_px: 0          # đề tài yêu cầu "khoảng cách = 0"

presence:
  absent_grace_s: 3.0           # ngắn hơn absent_reset_s của v2

schedule:
  timezone: "Asia/Ho_Chi_Minh"
  clock_skew_warn_s: 60
  windows:
    - days: [2, 3, 4, 5, 6]     # ISO: 1 = thứ 2 ... 7 = chủ nhật
      start: "19:00"
      end: "22:00"
    - days: [7]
      start: "08:00"
      end: "11:30"

speaker_alert:
  enabled: true
  tone_fallback: true           # thiếu ffmpeg thì bíp thay vì im
  audio_dir: data/audio
  language: vi                  # espeak-ng -v vi
  escalate_repeat_s: 120        # nhắc lại nếu vẫn sai (khác cooldown của state)

alerts:
  gpio_alert_enabled: false     # v3 dùng loa camera, không dùng buzzer

posture_labels_enabled: false   # tắt bộ luật tư thế v2

web:
  host: 0.0.0.0
  port: 8000
  stream_enabled: true          # v3 ĐỔI so với v2 (v2 để false): hiển thị camera
                                # là chức năng chính. Khung hình chỉ đi qua bộ
                                # nhớ ra HTTP, không ghi đĩa, không lưu lịch sử.
```

> **Khác biệt v3 so với v2:** `web.stream_enabled` mặc định **`true`**. Đây không phải nới lỏng quy tắc "không lưu ảnh" — chỉ là tách bạch **hiển thị** khỏi **lưu**. Xem bảng phân biệt ở §5.13.1 và tiêu chí 5b ở §8.2.

Mọi giá trị trên đều **đặt được**, không viết cứng trong code (giữ nguyên quy tắc v2 §1). Giá trị ở trên là **mặc định khởi điểm**, trừ `match_threshold` cố ý để `null` vì chưa đo.

---

## 7. Giao diện dòng lệnh (thêm vào v2)

```
python -m posture_monitor run            # thêm cờ --no-face, --no-phone
python -m posture_monitor faces list
python -m posture_monitor faces add TEN                # đăng ký qua camera, có hướng dẫn
python -m posture_monitor faces remove ID
python -m posture_monitor schedule check               # in cổng mở/đóng 7 ngày tới
python -m posture_monitor speak-test                   # phát thử câu tiếng Việt ra loa camera
python -m posture_monitor replay video.mp4 --signals   # replay cho cả 3 tín hiệu
```

Giữ nguyên v2: `calibrate`, `replay`, `benchmark`. `benchmark` được mở rộng để đo **ba cấu hình** (xem §8) và in rõ cấu hình nào chạy model nào.

---

## 8. Tiêu chí nghiệm thu

### 8.1 Hiệu năng

| Chỉ tiêu | Mục tiêu | Cách kiểm tra | Trạng thái |
| --- | --- | --- | --- |
| FPS pipeline, **cấu hình đầy đủ** (pose mỗi khung + detect 1/2 + face 1/2 s) | ≥ 5 FPS | `benchmark` trên Pi, ≥ 3 lần chạy ≥ 60 s | **CHƯA ĐO** — chỉ số đo hiện có là 6,18 FPS cho cấu hình **2 model** |
| FPS pipeline, 2 model (pose + detect 1/2) | ≥ 5 FPS | **ĐÃ ĐO**: 6,18 FPS | đạt |
| FPS pipeline, 2 model mỗi khung | — | **ĐÃ ĐO**: 4,74–4,90 FPS | **không đạt** — đây là lý do detect chạy cách khung |
| Độ trễ từ lúc vi phạm đủ `hold_s` tới lúc nghe tiếng | ≤ 2 s | log mốc thời gian (đo bằng tay, bấm giờ) | chưa đo |
| Nhiệt CPU, chạy 30 phút | < 80 °C | `benchmark` | chưa đo cho cấu hình 3 model |
| RAM cả tiến trình (2 model NCNN + face + web) | < 1 GB | `benchmark` | chưa đo |
| Throttle | `vcgencmd get_throttled` = `0x0` suốt bài đo | `benchmark` | bắt buộc, nếu khác 0 thì mọi số FPS không hợp lệ |
| Ổn định | 2 giờ liên tục, không crash, không rò rỉ | chạy dài | chưa đo |

**Quy tắc:** chỉ được ghi "đạt ≥ 5 FPS" khi bài đo chạy **đúng cấu hình ba model** và không có throttle. Không được suy từ 6,18 FPS của cấu hình hai model.

### 8.2 Nghiệm thu theo chức năng

| # | Chức năng | Tiêu chí | Bằng chứng cần có |
| --- | --- | --- | --- |
| 1 | Presence | Báo `ABSENT` trong ≤ 3 s sau khi người rời khung; về `PRESENT` ≤ 1 s khi quay lại; **0** lần báo vắng khi người vẫn ngồi, trong 10 phút | Replay clip có sẵn; `expected.json` ghi mốc chuyển trạng thái; log chuyển trạng thái |
| 1b | Người khác đi qua khung | Không đổi trạng thái presence của người được chọn | Replay clip 2 người; test tự động trên track id giả |
| 2 | Cảnh báo ra loa | Nghe được tiếng Việt từ loa camera ở khoảng cách ngồi học; ≤ 2 s sau khi đủ điều kiện; không phát lặp trong `alert_cooldown_s` | Video quay bằng điện thoại (chỉ để làm bằng chứng, **không** commit vào repo), log `SPEAK_OK`, `curl /api/speak` |
| 2b | Ngoài giờ học | Không phát cảnh báo nào; sự kiện không sinh | `schedule check` + test đồng hồ giả trên `ScheduleGate`; chạy thật ngoài giờ 5 phút, log sạch |
| 2c | Loa/mạng hỏng | Có `SPEAK_FAILED` trong log/DB; vòng lặp tiếp tục chạy | Rút mạng camera, chạy 2 phút, xem log |
| 3 | Dùng điện thoại | Phát hiện đúng ≥ 80 % trên clip có dùng điện thoại thật; ≤ 1 báo nhầm / 10 phút khi không dùng | Replay ≥ 3 clip (dùng, không dùng, điện thoại trên bàn không chạm); bảng đếm TP/FP/FN ghi vào báo cáo |
| 3b | Quy tắc khoảng cách = 0 | `point_rect_distance` = 0 khi cổ tay trong hộp, > 0 khi ngoài | Unit test với hình chữ nhật và điểm tổng hợp (biên, trong, ngoài, chạm cạnh) |
| 4 | Nhận diện khuôn mặt | `MATCH` đúng chủ ≥ 95 %; `MISMATCH` cho người khác ≥ 95 %; che mặt → `UNKNOWN` chứ không `MISMATCH` | Bộ mẫu đo (chính chủ / người khác / khẩu trang / ngược sáng), bảng confusion ghi vào báo cáo kèm ngưỡng đã chọn |
| 5 | Web xem luồng (**chức năng chính**) | Mặc định `web.stream_enabled: true`; mở dashboard từ điện thoại trong LAN là thấy luồng camera ngay, không phải sửa cấu hình. Tắt chủ động thì `/stream` trả 403 kèm thông báo tiếng Việt | Kiểm tra tay trên điện thoại thật + test `/stream` đã có ở v2 |
| 5b | Hiển thị không kèm lưu | Xem luồng 10 phút: không sinh file ảnh/video nào; không có route trả file khung hình | `find data/ -newer` trước/sau; kiểm tra danh sách route |
| 6 | Thêm người mới | Bấm một nút, đi đủ 5 bước, đăng ký thành công; bị ngắt giữa chừng thì **không** có bản ghi nào | Chạy thật trên Pi; test API; kiểm tra DB không có dòng rác; `data/audio/` không có ảnh |
| 6b | Chỉ lưu embedding | Sau khi đăng ký, không tồn tại file ảnh nào do đường này tạo ra; bảng chỉ có cột `vector` chứa `float32` | `find data/ -newer <mốc>` và đọc bảng; test tự động quét thư mục |
| 4b | **Đường ống khuôn mặt đúng hệ toạ độ** | Hộp khuôn mặt trả về nằm trong hệ pixel khung gốc: với khung 704x576, `x+w <= 704`, `y+h <= 576`, và khớp vị trí khi vẽ overlay | Unit test ánh xạ ngược; ảnh overlay kiểm tra bằng mắt trên khung thật |
| 4c | **Thu nhỏ trước khi detect** | `detect()` gọi YuNet với ảnh rộng 320, không phải 704 | Test đếm kích thước đầu vào; log kích thước một lần lúc khởi động |
| 4d | CLAHE bật mặc định | Cấu hình `clahe_enabled: true`; khung ngược sáng mạnh (sáng trung bình ~99,6) tìm được 1 khuôn mặt | Chạy trên khung thật đã lưu; **không** cam kết mọi điều kiện sáng |
| 7 | Chọn người đang học | Đổi người chọn thì identity so với đúng người mới; chọn người chưa đăng ký bị từ chối | Kiểm tra tay + test `POST /api/select` |
| 8 | PTZ | Bốn hướng xoay đúng chiều; camera không hỗ trợ thì báo lỗi tiếng Việt | Đã có test `test_web_ptz.py` ở v2; bổ sung kiểm tra tay trên camera thật |
| 9 | Giờ học | Đúng trong khung; đúng ngày trong tuần; đúng khung vắt nửa đêm; đúng khi đổi `TZ` | Unit test với `datetime` cố định, gồm 22:00–02:00, thứ 7/CN, giây cuối cùng của khung |

**Tiêu chí "báo nhầm" chung:** khi ngồi đúng, không dùng điện thoại, trong giờ học, **tối đa 1 cảnh báo sai / 10 phút**. Đây là mục tiêu, đo bằng chạy tay 30 phút.

### 8.3 Tiêu chí quyền riêng tư (chặn phát hành, không phải "nice to have")

| Kiểm tra | Đạt khi | Cách kiểm |
| --- | --- | --- |
| Không có ảnh trên đĩa | Sau 1 giờ chạy đủ chức năng (kể cả đăng ký), không có file ảnh/video mới trong `data/` | So sánh danh sách file trước/sau, `find -newer` |
| Chỉ embedding, không ảnh | Bảng `face_embeddings` chỉ có cột `vector` (`float32` 512 byte); **không** route nào trả vector | Query DB + duyệt danh sách route + `test_faces.py` |
| Không rò vector ra HTTP | `GET /api/people` không trả vector; không route nào trả | Đọc mã + test |
| Không có mật khẩu trong tài liệu/log | `grep` mật khẩu thật trên repo, log, báo cáo benchmark đều không thấy | `grep -rn` + chạy benchmark rồi grep kết quả |
| Stream bật mặc định nhưng **không lưu** | `web.stream_enabled: true` trong `config.yaml` mẫu; xem luồng xong không có file ảnh/video nào mới | Đọc file + `find data/ -newer` trước/sau khi xem 10 phút |

---

## 9. Kiểm thử

- **Unit test (chạy trên PC):**
  - `test_phone.py`: `point_rect_distance` (điểm trong, ngoài, trên cạnh, góc), chọn đúng hộp bao khi có nhiều điện thoại, hộp hết hạn bị bỏ, keypoint conf thấp không kết luận.
  - `test_presence.py`: chuyển trạng thái với track id giả, người khác đi qua không làm mất track.
  - `test_faces.py`: `FaceMatcher` với vector tổng hợp (khớp, không khớp, gallery rỗng, ngưỡng biên); **ánh xạ hộp từ hệ 320 về hệ khung gốc** (kể cả khung không phải bội số của 320); **khẳng định đầu vào YuNet đúng rộng 320**; **test quét thư mục để khẳng định không có file ảnh sinh ra**; vòng `tobytes()`/`frombuffer()` giữ nguyên vector.
  - `test_schedule.py`: đồng hồ giả, vắt nửa đêm, ngày trong tuần, biên mở/đóng, lệch TZ.
  - `test_speaker_alert.py`: chọn câu theo loại sự kiện, thứ tự ưu tiên, tôn trọng `muted`, loa bận thì bỏ, thiếu ffmpeg thì rơi về bíp (dùng controller giả).
  - `test_enroll_api.py`: đủ mẫu mới ghi, ngắt giữa chừng không ghi, tên rỗng bị từ chối.
- **Tích hợp bằng `replay`:** clip mẫu có dùng điện thoại / không dùng / hai người / ra khỏi khung. Kỳ vọng ghi trong `tests/data/expected_v3.json`.
- **Trên Pi (bắt buộc, người triển khai chạy):** `benchmark` cho ba cấu hình; `speak-test`; đăng ký người thật; chạy 30 phút trong giờ học để đếm báo nhầm.
- Mọi test trừ phần âm thanh/PTZ phải chạy được trên PC (giữ nguyên v2 §9).

---

## 10. Lộ trình

Tiếp sau v2 (M0–M5 đã xong). Thứ tự bắt buộc vì phụ thuộc ngân sách FPS.

| Mốc | Nội dung | Tiêu chí hoàn thành |
| --- | --- | --- |
| **M7** | `presence.py` + nhãn `ABSENT` vào state machine + tắt bộ luật tư thế | Presence đúng trên clip replay; `--no-face --no-phone` chạy như cũ |
| **M8** | `schedule.py` + cổng `ScheduleGate` | `schedule check` đúng; không sinh cảnh báo ngoài giờ |
| **M9** | `phone.py` + `PhoneDetector` + ngân sách FPS 2 model | Đo lại FPS **có** detect điện thoại; quy tắc khoảng cách = 0 có unit test; bảng TP/FP trên clip |
| **M10** | `faces.py` (thu nhỏ 320 + CLAHE + ánh xạ hộp) + gallery + chọn ngưỡng bằng đo | Bảng confusion trên bộ mẫu thật; hộp khuôn mặt ở hệ khung gốc; không có file ảnh |
| **M11** | `speaker_alert.py` + espeak-ng + hướng dẫn đăng ký bằng giọng nói | Nghe được trên loa camera; thiếu ffmpeg vẫn bíp; mất mạng không crash |
| **M12** | Web: `/stream` hiển thị trên trang chủ, thẻ trạng thái mới, nút thêm người, chọn người, **sửa 3 lớp lỗi nút PTZ (§17)** | Dùng được trên điện thoại; tuổi tín hiệu hiển thị; bấm nút PTZ trên giao diện thì camera **quay thật**, không chỉ `curl` |
| **M13** | Benchmark đầy đủ + README + báo cáo | Bảng §8.1 có số **của cấu hình ba model**; hoặc báo cáo trung thực "chưa đạt 5 FPS" kèm bậc thang dự phòng đã thử |

Không được bắt đầu M10 trước khi M9 kết thúc bằng số FPS đo được: thêm module khuôn mặt lên một pipeline **chưa rõ còn ngân sách hay không** là tích luỹ rủi ro.

---

## 11. Quy tắc làm việc cho AI agent

Kế thừa nguyên vẹn 8 quy tắc của v2 §11. Bổ sung:

9. **Dữ liệu sinh trắc học.** Chỉ lưu embedding (`float32` 128 chiều). Không tạo file ảnh ở bất kỳ đâu trong đường đăng ký/nhận diện, kể cả khi gỡ lỗi. Muốn gỡ lỗi bằng ảnh thì dùng ảnh tĩnh đặt sẵn trong `tests/data/`, không dùng khung từ camera người thật.
10. **Không hạ ngưỡng để test xanh.** Nếu test đỏ vì ngưỡng thật không đạt, đó là thông tin về hệ thống, không phải lỗi của test. Hạ `match_threshold` hay nới 80 % của chức năng 3 để test pass là vi phạm.
11. **Không thêm model thứ tư** khi chưa đo ngân sách. Bậc thang dự phòng ở §4.3 là danh sách đóng.
12. **"Train" là chữ cấm** trong UI và tài liệu: dùng "cập nhật bộ nhận diện". Nếu bắt buộc phải hiểu là fine-tune thì dừng và hỏi người dùng.

---

## 12. Rủi ro

| Rủi ro | Mức | Xử lý |
| --- | --- | --- |
| Cấu hình 3 model không đạt 5 FPS | **Cao** | Bậc thang §4.3; bắt buộc đo ở M9 trước khi làm M10; báo cáo trung thực nếu không đạt |
| Báo nhầm "dùng điện thoại" khi tay đặt lên bàn cạnh máy | Cao | Quy tắc đòi cổ tay **trong** hộp bao + `hold_s`; đo FP trên clip thật; nếu vẫn cao, nới `touching_slack_px` **không** cứu được — phải xem lại quy tắc và báo người dùng |
| Báo nhầm "học hộ" do nhận diện khuôn mặt kém (ánh sáng, khẩu trang) | **Cao** | Ba kết quả `MATCH`/`MISMATCH`/`UNKNOWN`; `UNKNOWN` không bao giờ báo; ngưỡng đo bằng thực nghiệm; `impostor_hold_s` dài |
| Người học **giả** bằng ảnh/video trên điện thoại | Trung bình | **Không** xử lý trong v3. Phải ghi rõ trong README: hệ thống không chống giả mạo. Thêm phát hiện liveness là đề tài khác |
| Loa camera không mở backchannel trên một số firmware | Trung bình | Đã kiểm chứng trên **đúng camera của dự án**; camera khác phải chạy `speak-test` trước. Thiếu thì rơi về bíp, thiếu nữa thì ghi `SPEAK_FAILED` |
| `espeak-ng` giọng tiếng Việt khó nghe | Trung bình | **Chưa đo chất lượng**; nếu không đủ rõ thì dùng tiếng bíp + chữ trên dashboard. Không tự ý thêm dịch vụ TTS cloud (vi phạm "không truyền ra ngoài") |
| Mất mạng làm rơi cảnh báo đúng lúc cần | Trung bình | Ghi sự kiện; dashboard hiện trạng thái "loa không phản hồi"; không có kênh dự phòng tự động trong v3 |
| Đồng hồ Pi sai → cảnh báo ngoài giờ | Trung bình | Kiểm tra lệch NTP; lệch nhiều thì **tắt phát** và cảnh báo trên dashboard |
| Khung giờ vắt nửa đêm tính sai | Trung bình | Unit test riêng, có ca 22:00–02:00 |
| Embedding lưu dạng rõ → ai đọc được đĩa/SD card thì có vector khuôn mặt | Trung bình | Đã chấp nhận trong v3. Giảm nhẹ: không có route trả vector, quyền file hạn chế, xoá là xoá thật. **Hướng mở rộng, chưa kiểm chứng:** mã hoá khi lưu (AES-GCM + khoá ngoài file cấu hình) — chỉ làm khi người dùng duyệt, và phải kiểm tra wheel `cryptography` aarch64 cp313 trên Pi 4 trước; **hiện chưa có bằng chứng** cài được |
| CLAHE không đủ cho mọi điều kiện sáng | Trung bình | Chỉ có bằng chứng ở 1 ca ngược sáng mạnh (0 → 1 mặt) và 12 khung sáng đều (không đổi kết quả). Thiếu sáng, đèn vàng, bóng đổ **chưa đo**; hậu quả rơi vào `UNKNOWN` chứ không phải `IMPOSTOR`, nên không gây báo nhầm |
| Quên ánh xạ hộp khuôn mặt về hệ khung gốc | Trung bình | Lỗi im lặng: overlay lệch 2,2 lần, mọi so khớp vị trí sai. Phòng bằng unit test ánh xạ + tiêu chí 4b/4c ở §8.2 |
| Ba model giành CPU, FPS giật | Trung bình | `FaceWorker` luồng riêng; đo ở M9/M10; nếu giật, giãn `face_interval_s` |
| Thẻ nhớ mòn do ghi log cảnh báo | Thấp | Giữ nguyên ghi theo lô + retention của v2 |
| Dữ liệu sinh trắc học bị dùng ngoài phạm vi đồng ý | Thấp về kỹ thuật, cao về pháp lý | §5.13.1; người quyết định sản phẩm xác nhận trước khi triển khai thật |

---

## 13. Sản phẩm bàn giao

Thêm vào danh sách v2 §13:

- 5 module mới + test của chúng
- Báo cáo benchmark **ba cấu hình** (2 model / +face / +web) trên Pi 4
- Bảng đo chọn `face_match_threshold`, kèm bộ mẫu **số liệu**, không kèm ảnh
- Tài liệu hướng dẫn đăng ký người mới có ảnh chụp **giao diện** (không phải ảnh khuôn mặt người thật)
- Kịch bản demo: chỉnh PTZ → thêm người → chọn người → trong giờ học: ra khỏi khung, dùng điện thoại, người khác ngồi vào → nghe cảnh báo trên loa → xem dashboard

---

## 14. Bài kiểm chứng trước khi bắt đầu M7

Điều kiện tiên quyết. Không có số FPS nào của cấu hình ba model được ghi vào tài liệu trước khi xong bước G.

### Bước F — Kiểm tra phụ thuộc mới

```bash
python -c "import cv2; print(cv2.__version__)"
python -c "import cv2; print(cv2.FaceDetectorYN_create, cv2.FaceRecognizerSF_create)"
which espeak-ng ffmpeg
ls -la *.onnx
du -sh *_ncnn_model/
free -m; df -h /
```

**Tiêu chí đạt:** in được cả hai hàm khuôn mặt của `cv2`; có `espeak-ng`; có `ffmpeg`; hai file `.onnx` đúng dung lượng **ĐÃ ĐO** (228 KB / 37 MB); còn ≥ 3 GB đĩa. **Không** kiểm tra thư viện mã hoá — v3 không dùng (§2b).

### Bước G — Đo ba cấu hình, liên tiếp, cùng buổi

```bash
# terminal 1
while true; do echo "$(date +%T) $(vcgencmd measure_temp) $(vcgencmd get_throttled)"; sleep 5; done | tee ~/bench3/thermal.log

# terminal 2 — mỗi cấu hình chạy ≥ 60 s, 3 lần
python -m posture_monitor benchmark --seconds 60 --profile pose_phone
python -m posture_monitor benchmark --seconds 60 --profile pose_phone_face
python -m posture_monitor benchmark --seconds 60 --profile full
```

**Tiêu chí đạt:** mỗi cấu hình có 3 lần chạy, ghi FPS, p50/p95, nhiệt, RAM; `throttled` = `0x0` suốt thời gian đo. Nếu profile `full` không đạt 5 FPS ở cả 3 lần, **dừng**: không làm M10, báo người dùng kèm bảng số và đề xuất bậc thang §4.3.

### Bước H — Chọn ngưỡng khuôn mặt bằng đo

Thu trên Pi, với vị trí camera thật, đủ sáng và thiếu sáng:

| Nhóm mẫu | Số mẫu tối thiểu | Đo gì |
| --- | --- | --- |
| Chính chủ | 20 | phân bố `score` với gallery của chính mình |
| Người khác | 20 | phân bố `score` cao nhất khi so với người khác |
| Che mặt (khẩu trang / tay) | 10 | tỉ lệ ra `UNKNOWN`, **không** ra `MISMATCH` |
| Ngược sáng | 10 | tỉ lệ `UNKNOWN` |

**Tiêu chí đạt:** tìm được ngưỡng tách được hai phân bố đầu với biên; ghi ngưỡng + ngày đo + số mẫu vào `config.yaml` và báo cáo. **Không có ngưỡng mặc định nào được coi là đã kiểm chứng.**

---

## 15. Câu hỏi còn mở

1. **"Dùng điện thoại" có tính cả đặt máy trên bàn để tra cứu?** Quy tắc hiện tại *chỉ* báo khi cổ tay chạm vào hộp bao. Đặt máy trên bàn nhưng tay không chạm → không báo. Cần người dùng xác nhận đây là đúng ý.
2. **Người học ra khỏi khung bao lâu thì cảnh báo?** `absent_grace_s = 3 s` là khởi điểm; đi lấy nước 2 phút có bị nhắc liên tục không — cần chọn chính sách (nhắc một lần, hay nhắc lại mỗi `escalate_repeat_s`).
3. **CLAHE có đủ cho mọi điều kiện sáng không?** Mới đo 1 ca ngược sáng mạnh (thô 0 mặt → CLAHE 1 mặt) và 12 khung sáng đều (không khác biệt). Chưa đo: thiếu sáng, đèn vàng, bóng đổ, ngược sáng vừa. Cần đo trên nhiều điều kiện trước khi cam kết độ chính xác nhận diện khuôn mặt.
4. **Ghi âm/tiếng có được phép không?** Hệ thống chỉ **phát**, không **thu** âm thanh từ camera. Nếu sau này cần thu thì đó là thay đổi về quyền riêng tư, cần quyết định riêng.
5. **Có cần chống giả mạo khuôn mặt (ảnh/video)?** Hiện không có. Người học có thể dùng ảnh để "có mặt". Đây là lỗ hổng đã biết, không phải lỗi cài đặt.
6. **Ai được xoá danh tính?** Dashboard không có đăng nhập (v2 §5.10). Trong LAN thì ai cũng xoá được. Có cần mã PIN cho thao tác xoá/đăng ký không?
7. **Có cần nhiều khung giờ khác nhau cho từng ngày trong tuần** (ví dụ thứ 2 khác thứ 6)? Cấu hình hiện tại đã hỗ trợ; câu hỏi là UI có cần sửa được từ điện thoại không.
8. **`yunet.onnx` và `sface.onnx` lấy từ đâu, giấy phép gì?** Tài liệu này chưa xác định nguồn tải và giấy phép. Cần bổ sung vào `docs/REUSE_AUDIT.md` theo đúng tiêu chí ba điều kiện trước khi commit file model.
9. **Khi Pi khởi động lại giữa giờ học**, có tự chạy lại phiên và chọn đúng người không? Chưa có cơ chế tự khôi phục trong v3.
10. **Có cần mã hoá embedding khi lưu không?** v3 không làm, đã ghi là hướng mở rộng (§12). Câu hỏi dành cho người quyết định sản phẩm: mức bảo vệ hiện tại (quyền file + không có route trả vector) có đủ cho phạm vi triển khai thật không.

---

## 16. Hiện trạng đã kiểm chứng trên thiết bị thật

Toàn bộ đo ngày **2026-10-29, trên Pi 4 của dự án, với camera thật của dự án**. Đây là các sự thật đã chứng minh, không phải kế hoạch.

| Hạng mục | Kết quả | Ý nghĩa cho spec |
| --- | --- | --- |
| RTSP từ Pi | Đọc được khung thật **704x576** | Đường capture hoạt động; kích thước khung đúng giả định §2 |
| Loa camera (backchannel) | **Đã phát thật**: `SpeakResult(mode='tone', codec='PCMA', sample_rate=8000, packets_sent=20, duration_seconds=0.8)` | Chức năng 2 khả thi; dùng tái dùng `SpeakController`, không viết mới |
| PTZ (ONVIF) | **Đã xoay thật**: `PtzStatus(pan_tilt=PtzVector(x=-0.008833, y=0.856344), zoom=0.0)` | Route và thư viện PTZ chạy được trên phần cứng thật |
| YOLO detect trên khung thật | `person=2, chair=4` ở conf 0.05; `person=2` ở conf 0.15. **Không có `cell phone` trong cảnh** | Model chạy được; **chưa** có bằng chứng phát hiện điện thoại trên cảnh thật — xem §8.2 mục 3 |
| YuNet ở 704x576 | 99,9 ms/lần | Quá chậm để chạy nguyên khung |
| YuNet ở 320x262 | 19,3 ms/lần, **vẫn tìm được mặt** | Quyết định thu nhỏ ở §5.13 |
| CLAHE ở 320x262 | 11,4 ms/lần | Rẻ, bật mặc định |
| Trọn đường ống khuôn mặt @320x262 | **86,1 ms → 11,6 lượt/giây** | Cơ sở ngân sách §4.3 |
| Ánh xạ hộp khuôn mặt | Hộp hệ 320 → `[158.9, 214.4, 123.0, 216.6]` trong khung 704x576 | Ánh xạ ngược chạy đúng; ràng buộc §5.13(2) khả thi |
| SFace feature | Vector **128 chiều** | Kích thước lưu trữ §5.17 |
| CLAHE và điều kiện sáng | Ngược sáng mạnh (sáng TB 99,6): thô 0 mặt → CLAHE 1 mặt (0,806). 12 khung sáng đều (110,8–111,0): cả hai đều 1 mặt, score 0,919–0,923 | CLAHE là phòng ngừa, **không** phải điều kiện bắt buộc — §5.13(3) |

**Chưa kiểm chứng:** phát hiện `cell phone` trên cảnh thật; ba model chạy đồng thời; câu tiếng Việt qua espeak-ng nghe rõ; ngưỡng cosine giữa hai người; độ chính xác CLAHE ở điều kiện sáng khác.

---

## 17. Điều tra sự cố: nút PTZ không hoạt động

**Triệu chứng người dùng báo:** "điều khiển camera trong app không bấm được / không thấy nút".

**Kết luận điều tra: KHÔNG phải một lỗi, mà là BA lớp lỗi độc lập chồng lên nhau.** Sửa một lớp vẫn không làm nút chạy được. Phải sửa đồng thời cả ba.

### Lớp 1 — Giao diện: nút chưa từng tồn tại

| Kiểm tra | Kết quả |
| --- | --- |
| `POST /api/ptz` có trong `web/app.py` | **Có** — `src/posture_monitor/web/app.py:474` |
| Có test cho route | **Có** — `tests/test_web_ptz.py` |
| `index.html` có nút PTZ | **Không.** Chỉ có `mute-btn` và `calibrate-btn` |
| `app.js` có gọi `/api/ptz` | **Không.** Không có một dòng nào |

Đây là lớp **gốc rễ**: backend hoàn chỉnh nhưng người dùng không có đường nào chạm tới nó.

**Cách sửa:** thêm khối 4 nút (trái/phải/lên/xuống) vào `index.html`, thêm handler trong `app.js` gọi `POST /api/ptz {"direction": ..., "duration": 0.5}`, hiện thông điệp lỗi tiếng Việt trả về từ server. Nút cao ≥ 52 px theo chuẩn cảm ứng của `WEB_DASHBOARD.md` §6.

### Lớp 2 — Cấu hình: tính năng bị tắt và không có địa chỉ

`config.yaml` hiện có:

```yaml
camera:
  onvif:
    enabled: false
    host: ""
```

Dù bấm được nút, `_get_ptz()` sẽ trả lỗi cấu hình vì `enabled: false` và `host` rỗng.

**Cách sửa:** người triển khai bật `enabled: true` và đặt `host` (địa chỉ camera trong LAN) trong `config.local.yaml` — **không** đặt mật khẩu ở đó, mật khẩu chỉ qua `POSTURE_ONVIF_PASSWORD`. Spec mục §6 và README phải nói rõ chuỗi này.

### Lớp 3 — Môi trường: thiếu thư viện trên Pi

`camera_control._load_library()` cần `rtsp-backchannel`. Trên Pi, venv của dự án **thiếu** thư viện này, nên `PtzError` với thông điệp `MISSING_LIBRARY_MESSAGE` sẽ trả 503.

**Cách sửa:** `pip install rtsp-backchannel==0.5.2` trong venv trên Pi. Ghi vào bước cài đặt của README và `requirements.txt` (đã có dòng này — cần xác nhận đã cài thật, không chỉ có trong file).

### Bảng sửa và cách kiểm chứng từng lớp

| Lớp | Sửa gì | Kiểm chứng đạt khi |
| --- | --- | --- |
| 1 — UI | Nút + handler trong `index.html`/`app.js` | Bấm nút thấy request `POST /api/ptz` trong log server |
| 2 — Cấu hình | `camera.onvif.enabled: true`, `host` đặt trong `config.local.yaml` | `/api/ptz` trả 200, không trả 403/500 cấu hình |
| 3 — Môi trường | Cài `rtsp-backchannel` trong venv trên Pi | Không còn 503 `MISSING_LIBRARY_MESSAGE` |
| Tất cả | — | Chạy thật: `PtzStatus(pan_tilt=PtzVector(x=-0.008833, y=0.856344), zoom=0.0)` trả về, camera **quay thấy bằng mắt** |

**Đã kiểm chứng ở tầng phần cứng (2026-10-29):** gọi thẳng `PtzController` trên Pi với camera thật đã trả `PtzStatus(pan_tilt=PtzVector(x=-0.008833, y=0.856344), zoom=0.0)` và camera quay. Điều này xác nhận **camera và thư viện đúng** — nghĩa là khi báo "nút PTZ không chạy", lỗi nằm ở lớp 1 và/hoặc lớp 2, **không** phải camera hỏng.

**Ghi vào lộ trình:** việc sửa ba lớp trên thuộc **M12** (giao diện). Tiêu chí hoàn thành M12 phải bao gồm mục 8 của §8.2 chạy được từ giao diện, không chỉ từ `curl`.

---

## 18. Ba điều cố ý **không** đưa vào spec vì thiếu bằng chứng

Ghi lại minh bạch để người đọc biết chỗ nào tài liệu **đang mỏng**, không phải chỗ đã xong.

1. **Ngưỡng cosine `face_match_threshold`** — không có số nào. Không chép ngưỡng của OpenCV hay repo khác, vì ngưỡng phụ thuộc camera, ánh sáng và người thật. Để `null` trong cấu hình mẫu và biến nó thành bước H bắt buộc.
2. **Chất lượng và độ trễ giọng tiếng Việt của `espeak-ng`** — chỉ biết là công cụ **có** trên Pi và tạo được WAV. Chưa nghe, chưa đo độ trễ sinh file, chưa biết người học có hiểu không. Vì vậy spec có đường dự phòng (bíp + chữ trên dashboard) và không cam kết "phát câu tiếng Việt rõ ràng".
3. **FPS và RAM của cấu hình ba model chạy đồng thời** — đã đo riêng lẻ từng model và đo hai model, và đã đo trọn đường ống khuôn mặt (86,1 ms), nhưng **chưa** đo ba thứ chạy cùng nhau trong một tiến trình. Con số 6,04 FPS trong §4.3 là **số học**, không phải số đo, và spec ghi rõ nó không dùng để nghiệm thu. Bước G tồn tại đúng vì thiếu số này.
