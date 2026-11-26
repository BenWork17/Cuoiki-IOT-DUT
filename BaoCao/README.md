# Báo cáo Đồ án — Chuẩn định dạng Khoa CNTT, Trường Đại học Bách Khoa (ĐHĐN)

Thư mục này chứa mã nguồn biên soạn, hình ảnh minh họa và trình xuất tệp Word (`.docx`) cho báo cáo **Hệ thống giám sát học tập trên Raspberry Pi 4 kết hợp Camera IP và Ứng dụng di động**, tuân thủ chuẩn trình bày học thuật của Khoa Công Nghệ Thông Tin — Trường Đại học Bách Khoa, Đại học Đà Nẵng (`<= 30 trang`, tập trung hoàn toàn vào giải pháp tận dụng và cải tiến kỹ thuật thực tế).

## Danh mục tệp chính

| Tệp / Thư mục | Vai trò |
|---|---|
| **`BaoCao_DoAn_GiamSatHocTap.docx`** | **Tệp báo cáo Word nộp chính thức (29 trang).** Gồm trang bìa chuẩn 2 logo (DUT & Khoa CNTT), 3 danh mục tự động (`MỤC LỤC`, `HÌNH ẢNH`, `BẢNG BIỂU`), 7 chương cô đọng, 9 bảng biểu và 5 hình minh họa chữ lớn |
| `BAO_CAO_DO_AN.md` | Văn bản nguồn Markdown tập trung phân tích cách tận dụng và cải tiến 4 mô hình AI, luồng RTSP, loa camera và ứng dụng di động |
| `figures/` | Bộ hình minh họa chữ lớn chuẩn in A4 và 2 logo chính thức (`logo-dut.png`, `logo-cntt.jpg`) |
| `make_figures.py` | Kịch bản sinh tự động sơ đồ kiến trúc, luồng xử lý, ngân sách thời gian và bố cục 7 tab ứng dụng di động |
| `make_docx.py` | Trình biên dịch `BAO_CAO_DO_AN.md` sang `.docx` chuẩn OOXML (`Times New Roman` 13 pt, lề đóng gáy 3,5 cm) |
| `verify_docx.py` | Trình kiểm định cấu trúc XML, lề trang, trường động `TOC`/`SEQ`, 7 chương và mốc số liệu |
| `check_figures.py` | Trình kiểm tra toàn bộ hình ảnh nằm gọn trong vùng in A4 (`15,5 × 19,2 cm`) |

## Cấu trúc 7 chương của báo cáo (≤ 30 trang)

1. **CHƯƠNG 1.** Giới thiệu bài toán và mục tiêu đề tài
2. **CHƯƠNG 2.** Kiến trúc hệ thống và tối ưu luồng dữ liệu biên (9 phân hệ một chiều & tự phục hồi RTSP 60 chu kỳ)
3. **CHƯƠNG 3.** Tận dụng và cải tiến các mô hình AI trên thiết bị biên (`YOLO11n-pose`, `YOLO11n`, `YuNet`, `SFace`)
4. **CHƯƠNG 4.** Tích hợp ngoại vi Camera IP, Web Dashboard và Ứng dụng di động Expo 7 tab (Sáng/Tối, quét mặt 5 bước, Log chi tiết)
5. **CHƯƠNG 5.** Kiểm thử hệ thống (`1.662` bài Python + `201` bài Mobile), đo lường hiệu năng và đánh giá thực địa
6. **CHƯƠNG 6.** Kết luận và hướng phát triển
7. **CHƯƠNG 7.** Tài liệu tham khảo

## Cách cập nhật thông tin Giảng viên hướng dẫn / Sinh viên

Mở tệp `BAO_CAO_DO_AN.md`, chỉnh sửa khối YAML ở đầu tệp (`course_title`, `advisor`, `footer_students`, `students`), sau đó chạy:

```bash
python BaoCao/make_docx.py
python BaoCao/verify_docx.py
python BaoCao/check_figures.py
```
