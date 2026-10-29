# Tệp mô hình — tải ở đâu, kiểm thế nào

Hai tệp mô hình khuôn mặt **không được commit** (`.gitignore` chặn `*.onnx`;
`sface.onnx` nặng 37 MB). Máy mới clone repo sẽ thiếu chúng và tính năng nhận
diện khuôn mặt không chạy được cho tới khi tải về.

## Bảng tệp

| Tệp | Nguồn | Kích thước | SHA-256 |
|---|---|---|---|
| `yunet.onnx` | [opencv_zoo — face_detection_yunet](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx) | 232 589 B (227 KB) | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `sface.onnx` | [opencv_zoo — face_recognition_sface](https://github.com/opencv/opencv_zoo/blob/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx) | 38 696 353 B (36,9 MB) | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |

Đây là cặp mô hình chính thức của OpenCV Zoo, đúng thứ `cv2.FaceDetectorYN_create`
và `cv2.FaceRecognizerSF_create` mong đợi. Lấy từ nhánh `main` của opencv_zoo;
ngày tải: **2026-10-29**. Giấy phép của opencv_zoo: Apache-2.0.

## Tải về

Đặt ở **gốc repo** — đường dẫn trong `config.yaml` (`face.detector`,
`face.recognizer`) là tương đối so với gốc repo:

```bash
cd /path/to/repo
curl -sSL --fail -o yunet.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
curl -sSL --fail -o sface.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
```

## Kiểm chứng

```bash
sha256sum yunet.onnx sface.onnx   # khớp bảng trên
pytest tests/test_models_present.py -v
```

`tests/test_models_present.py` **bỏ qua** khi tệp thiếu (vì tệp không nằm trong
git) và **fail** khi tệp có mặt nhưng OpenCV không parse được — một tệp rác đặt
đúng tên sẽ bị bắt, không lọt qua.

Ghi chú đo được trên cv2 4.13.0: `FaceDetectorYN.detect()` trả `(retval, faces)`
trong đó `retval` là **cờ thành công** (luôn `1`), không phải số khuôn mặt;
không phát hiện được mặt nào thì `faces` là `None`. Vector đặc trưng của
`FaceRecognizerSF.feature()` có **128 chiều** (spec §4.2).
