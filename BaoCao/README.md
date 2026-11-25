# Báo cáo Đồ án — Chuẩn định dạng Khoa CNTT, Trường Đại học Bách Khoa (ĐHĐN)

Thư mục này chứa toàn bộ mã nguồn biên soạn, hình ảnh minh họa và trình xuất tệp Word (`.docx`) cho báo cáo **Hệ thống giám sát học tập trên Raspberry Pi 4 kết hợp Camera IP và Ứng dụng di động**, tuân thủ nghiêm ngặt chuẩn trình bày học thuật của Khoa Công Nghệ Thông Tin — Trường Đại học Bách Khoa, Đại học Đà Nẵng (`dut-capstone-report`).

## Danh mục tệp chính

| Tệp / Thư mục | Vai trò |
|---|---|
| **`BaoCao_DoAn_GiamSatHocTap.docx`** | **Tệp báo cáo Word nộp chính thức.** Gồm trang bìa chuẩn 2 logo (DUT & Khoa CNTT), 3 danh mục tự động (`MỤC LỤC`, `HÌNH ẢNH`, `BẢNG BIỂU`), 12 chương nội dung, 35 bảng biểu và 11 hình minh họa |
| `BAO_CAO_DO_AN.md` | Văn bản nguồn Markdown (~33.300 từ) kèm khối cấu hình thông tin trang bìa ở đầu tệp |
| `figures/` | Toàn bộ 11 hình nội dung (`01`..`11`) và 2 logo chính thức (`logo-dut.png`, `logo-cntt.jpg`) |
| `make_figures.py` | Kịch bản sinh tự động 9 sơ đồ kiến trúc, ngân sách thời gian và bố cục ứng dụng di động |
| `make_docx.py` | Trình biên dịch `BAO_CAO_DO_AN.md` sang `.docx` chuẩn OOXML (`Times New Roman` 13 pt, lề đóng gáy 3,5 cm) |
| `verify_docx.py` | Trình kiểm định sâu cấu trúc XML, lề trang, trường động `TOC`/`SEQ`, 12 chương và mốc số liệu |
| `check_figures.py` | Trình kiểm tra toàn bộ hình ảnh nằm gọn trong khung in A4 (`15,0 × 19,0 cm`) |

## Cấu trúc 12 chương của báo cáo

1. **CHƯƠNG 1.** Giới thiệu bài toán và mục tiêu nghiên cứu
2. **CHƯƠNG 2.** Kiến trúc hệ thống và thiết kế kỹ thuật tổng thể (4 tầng & 9 phân hệ một chiều)
3. **CHƯƠNG 3.** Luồng dữ liệu đầu vào, mô hình pretrained và tiền xử lý trên thiết bị biên
4. **CHƯƠNG 4.** Module ước lượng khung xương, hiện diện và bộ luật tư thế (`YOLO11n-pose`)
5. **CHƯƠNG 5.** Module phát hiện sử dụng điện thoại trong phiên học (`YOLO11n` detect)
6. **CHƯƠNG 6.** Module đăng ký và xác thực danh tính người học (`YuNet` và `SFace`)
7. **CHƯƠNG 7.** Triển khai phần cứng Raspberry Pi 4, loa camera backchannel, PTZ và GPIO
8. **CHƯƠNG 8.** Triển khai Web Dashboard, Ứng dụng di động Expo (*Nocturne Telemetry*) và kịch bản vận hành
9. **CHƯƠNG 9.** Kiểm thử hệ thống (`1.662` bài Python + `189` bài Mobile), đo lường hiệu năng và đánh giá tổng hợp
10. **CHƯƠNG 10.** Kết luận và hướng phát triển
11. **CHƯƠNG 11.** Tài liệu tham khảo
12. **CHƯƠNG 12.** Phụ lục (Cây thư mục, thư viện khóa phiên bản, 24 endpoint API, mẫu JSON, cấu hình & lệnh chạy)

## Cách cập nhật thông tin Giảng viên hướng dẫn / Sinh viên trên trang bìa

Mở tệp `BAO_CAO_DO_AN.md`, chỉnh sửa khối YAML ở 15 dòng đầu tiên (`course_title`, `advisor`, `footer_students`, danh sách `students`), sau đó chạy lại quy trình sinh và kiểm định:

```bash
python BaoCao/make_docx.py
python BaoCao/verify_docx.py
python BaoCao/check_figures.py
```

Khi mở tệp `BaoCao_DoAn_GiamSatHocTap.docx` trong Microsoft Word, chọn **Yes** nếu Word hỏi cập nhật trường tự động (hoặc nhấn `Ctrl + A` rồi nhấn `F9` -> chọn *Update entire table*) để Word điền số trang chính xác cho cả ba trang **MỤC LỤC**, **HÌNH ẢNH** và **BẢNG BIỂU**.
