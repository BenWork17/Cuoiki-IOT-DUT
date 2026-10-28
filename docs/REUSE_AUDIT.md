# Đánh giá tài nguyên tái sử dụng

Tài liệu phụ lục cho spec v2 · Cập nhật 28/10/2026 · Đánh giá những gì có thể tái sử dụng thay vì viết lại từ đầu

## Tiêu chí đánh giá

Một tài nguyên chỉ được đánh **TẠN DỤNG** khi đạt đủ cả ba điều kiện:

1. **Có giấy phép rõ ràng** — xác định được loại giấy phép và điều kiện kèm theo.
2. **Đã chạy thử và ra kết quả đúng** — không chỉ đọc mã nguồn hay đọc README.
3. **Phù hợp phạm vi đề tài** — giải đúng bài toán đang làm, không phải bài toán lân cận.

Không đạt cả ba thì đánh **LOẠI**. Không có mức trung gian: một tài nguyên "có vẻ hay" nhưng chưa chạy thử không được tính là tái sử dụng.

## Nhóm 1 — TẠN DỤNG (đã chạy thử thành công)

| Tài nguyên | Nguồn | Giấy phép | Cách kiểm chứng | Kết luận |
| --- | --- | --- | --- | --- |
| `ultralytics.solutions.solutions.SolutionAnnotator.estimate_pose_angle(a,b,c)` | thư viện ultralytics đã cài | AGPL-3.0 | Gọi trực tiếp với 3 keypoint thật từ model NCNN, trả góc 157,49° cho bộ (tai phải, vai phải, hông phải) | **TẠN DỤNG** cho `neck_angle`/`torso_angle` ở chế độ side. Hàm đã xử lý đúng trường hợp góc > 180. |
| `YOLO.track()` với `botsort.yaml` | ultralytics | AGPL-3.0 | Chạy trên model NCNN, trả track id `[1.0, 2.0, 3.0]` | **TẠN DỤNG** để chọn và bám một người. Phải đo chi phí trong `benchmark`. |
| `ultralytics.solutions.ObjectBlurrer` | ultralytics | AGPL-3.0 | Chạy với model pose NCNN, làm mờ được 3 đối tượng | **TẠN DỤNG** chỉ cho `/stream` tùy chọn, để bảo vệ quyền riêng tư. |
| `gpiozero.pins.mock.MockFactory` | gpiozero 2.0.1.post3 | MIT | Đặt `Device.pin_factory = MockFactory()`, LED bật/tắt đúng, `DistanceSensor` khởi tạo được | **TẠN DỤNG** thay cho `gpio_mock.py` tự viết. Giới hạn: không giả lập được giá trị khoảng cách, phải fake ở tầng `sensors.py`. |
| Chart.js 4.4.1 UMD minified | jsDelivr, `dist/chart.umd.min.js` | MIT | Tải về 205.399 byte, xác nhận chuỗi `Chart.js v4.4.1` trong file, sha256 `d2af8974e95271638772e9e9524db5b9a6f58d6ec2d5d781400447b4a31c681e` | **TẠN DỤNG**, đặt cục bộ trong `static/`, đúng yêu cầu không dùng CDN của §5.10. |
| Trọng số `yolo11n-pose.pt` và `yolov8n-pose.pt` | release asset ultralytics v8.3.0 | AGPL-3.0 | Tải thử HTTP 206, magic bytes `PK\x03\x04` xác nhận là file zip hợp lệ | **TẠN DỤNG**. Model dự phòng theo thang §8 vẫn còn tải được. |
| `yolo11-pose.yaml` (định nghĩa kiến trúc) | ultralytics main branch | AGPL-3.0 | Tải được HTTP 200, scale `n` khai báo 2.905.907 tham số | **TẠN DỤNG**. YOLO11 vẫn được duy trì dù docs đã chuyển sang YOLO26. |

> **Cảnh báo giấy phép:** ultralytics là **AGPL-3.0**. Nếu đồ án chỉ dùng nội bộ và nộp báo cáo thì bình thường, nhưng nếu sau này phát hành sản phẩm thì AGPL bắt buộc mở mã nguồn. Cần nêu trong README.

## Nhóm 2 — LOẠI (đã kiểm tra và không đạt)

| Tài nguyên | Số sao | Lý do loại |
| --- | --- | --- |
| `Harmolsingh/YOLO-MediaPipe-LiftVision` | 57 | Không có giấy phép. Trùng lặp đáng ngờ: tồn tại bản thứ hai `herlinesosejosisaac-spec/YOLO-MediaPipe-LiftVision` với mô tả giống hệt, cùng ngày tạo 21/09/2026, cùng 0 fork. Dấu hiệu tài khoản farm sao, không đáng tin. |
| `herlinesosejosisaac-spec/YOLO-MediaPipe-LiftVision` | 56 | Cùng lý do trên. |
| `SuriyaaVijay/Posture-Recognition-using-Opencv-and-Mediapipe` | 12 | Giấy phép MIT tốt, nhưng cây file chỉ có 4 mục: 2 ảnh PNG, LICENSE, README. **Không có mã nguồn nào.** Không có gì để tái sử dụng. |
| `PSLeon24/AI_Exercise_Pose_Feedback` | 24 | Không có giấy phép, dung lượng 329 MB, là notebook phân tích động tác cử tạ không cùng bài toán, kèm model `.pkl` không rõ nguồn. Rủi ro giấy phép và sai miền ứng dụng. |
| `Prabuddhi-05/human` | 7 | Không có giấy phép, lần đẩy cuối 19/09/2023, đã cũ. |
| `rlraj/Smart-Factory-AI-based-Ergonomic-Risk-Assessment-Tool-using-REBA-RULA-and-NIOSH` | 1 | Không có giấy phép, quá ít tín hiệu chất lượng. Chỉ nên đọc để tham khảo ý tưởng thang điểm REBA/RULA, không lấy code. |

**Kết luận nhóm 2:** không có repo GitHub nào đáng lấy code. Giá trị thật nằm ở chính framework Ultralytics (đã kiểm chứng chạy được), không phải ở các repo ứng dụng.

## Nhóm 3 — THAM KHẢO Ý TƯỞNG, chưa kiểm chứng

REBA và RULA là hai phương pháp chấm điểm ergonomic chuẩn trong công thái học lao động. Có thể tham khảo cấu trúc chấm điểm của chúng để làm công thức điểm 0–100 ở §5.5 thay vì trừ điểm tuyến tính.

**Chưa kiểm chứng implementation nào**, nên chỉ ghi là ý tưởng, không cam kết dùng.

## Nhóm 4 — Ghi chú về các thư viện thay thế (đã kiểm tra wheel aarch64)

| Package | Phiên bản | Có wheel aarch64 cho cp311 | Ghi chú |
| --- | --- | --- | --- |
| `ncnn` | 1.0.20261020 | có (cp39–cp315) | |
| `pnnx` | 20261020 | có (manylinux2014\_aarch64, 24,7 MB) | |
| `torch` | 2.7.1 | có (manylinux\_2\_28\_aarch64) | không dùng 2.6.0, xem §2b |
| `torchvision` | 0.22.1 | có | pin `torch==2.7.1` |
| `opencv-python` | 4.12.0.88 | có (cp37-abi3) | không dùng 4.13.0.90 |
| `numpy` | 2.4.6 | có cho cp311 | 2.5.4 chỉ từ Python 3.12 |
| `lgpio` | 0.2.2.0 | chỉ cp39–cp312, **không có cp313** | trên Trixie (Python 3.13) phải dùng `apt install python3-lgpio` |
| `gpiozero` | 2.0.1.post3 | pure python | |
| `flask` | 3.1.3 | pure python | |
| `picamera2` | 0.3.38 | pure python | nhưng trên Pi nên cài bằng `sudo apt install python3-picamera2` |
| `mediapipe` | 1.2.0 | có (py3-none-manylinux\_2\_28\_aarch64, 40,1 MB) | dùng làm phương án dự phòng cuối theo §8 |
| `onnxruntime` | 1.31.1 | có (cp311/cp313 aarch64) | dùng cho đường fallback ONNX |
| `waitress` | 3.0.2 | pure python | cân nhắc thay Flask dev server khi chạy thật |
