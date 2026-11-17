# Báo cáo đồ án — bộ tệp nộp bài

Thư mục này chứa báo cáo hoàn chỉnh của đồ án **Hệ thống giám sát học tập trên
Raspberry Pi 4**, chia làm năm phần tương ứng năm tầng kỹ thuật của hệ thống.

## Tệp nộp

| Tệp | Nội dung |
|---|---|
| **`BaoCao_DoAn_GiamSatHocTap.docx`** | **Bản nộp chính.** Trang bìa, mục lục tự động, 6 chương + phụ lục, 36 bảng, 10 hình |
| `BAO_CAO_DO_AN.md` | Cùng nội dung ở dạng Markdown (nguồn để sinh .docx) |
| `figures/` | Toàn bộ hình: 8 sơ đồ tự vẽ + 2 ảnh chụp dashboard thật |

## Cấu trúc báo cáo

| Chương | Phần | Nội dung |
|---|---|---|
| 1 | Tổng quan | Bài toán, mục tiêu, phạm vi, kiến trúc bốn tầng, môi trường đo |
| **2** | **Model AI** | YOLO11n-pose, YOLO11n detect (điện thoại), YuNet + SFace, presence, ngân sách FPS |
| **3** | **Web FE / BE** | Flask, `DashboardState`, 22 route, luồng MJPEG, giao diện, phiên học, quyền riêng tư |
| **4** | **Phần cứng** | Camera IP RTSP, Raspberry Pi 4, loa camera (backchannel), PTZ, GPIO, siêu âm, SQLite |
| 5 | Đánh giá | 1.667 bài test, benchmark, đối chiếu nghiệm thu, hạn chế, bài học số liệu |
| **6** | **Ứng dụng di động** | React Native / Expo Go trên iOS: 8 màn hình, 10 route, hai chế độ xem camera, giới hạn chưa kiểm |

## Quy ước số liệu — đọc trước khi trích dẫn

Mọi con số hiệu năng trong báo cáo đều mang một trong ba nhãn, và chỉ số **ĐÃ ĐO**
được dùng làm căn cứ nghiệm thu:

| Nhãn | Nghĩa |
|---|---|
| **ĐÃ ĐO** | Đo thực trên chính Raspberry Pi 4 của dự án, có ngày đo |
| **TÍNH TỪ ĐO** | Suy ra bằng số học từ số ĐÃ ĐO, có ghi công thức |
| **CHƯA ĐO** | Không có bài đo nào — chỉ dùng để lập kế hoạch |

Nguồn gốc của quy ước này là một sự cố số liệu có thật, ghi lại ở chương 5.6.

## Sinh lại báo cáo

Bốn script độc lập, chạy theo thứ tự:

```bash
# 1) Vẽ lại 8 hình sơ đồ (cần matplotlib + font tiếng Việt của Windows)
python BaoCao/make_figures.py

# 2) Sinh .docx từ Markdown (cần python-docx + Pillow)
python BaoCao/make_docx.py

# 3) Kiểm tra tệp .docx: cấu trúc, thứ tự XML, bảng, hình, ký tự lỗi
python BaoCao/verify_docx.py

# 4) Kiểm tra hình có nằm trong vùng in A4 hay không
python BaoCao/check_figures.py
```

`verify_docx.py` không chỉ đếm tiêu đề: nó soát **thứ tự phần tử con của
`w:pPr` / `w:rPr` / `w:tcPr`** theo schema OOXML, vì sai thứ tự là nguyên nhân
phổ biến khiến Word treo hoặc hiện hộp thoại "repair" khi mở tệp.

`check_figures.py` dùng **cùng một quy tắc** với `make_docx.add_image()`: hình
rộng tối đa 16 cm, cao tối đa 22,5 cm. Ảnh dọc vượt chiều cao sẽ được thu theo
chiều cao — nếu không, ảnh chụp màn hình điện thoại (780×1688) rộng 16 cm sẽ
cao 34,6 cm và bị Word cắt mất.

Hai ảnh `figures/09-dashboard-pi.png` và `figures/10-dashboard-phone.png` là ảnh
chụp màn hình thật, không sinh lại bằng script.

## Ghi chú khi mở tệp .docx

- **Mục lục** là trường tự động của Word. Mở tệp rồi nhấn `F9` (hoặc chuột phải →
  *Update Field*) để hiện số trang.
- Font dùng: **Calibri** cho văn bản, **Consolas** cho mã và tên tệp. Cả hai có sẵn
  trong bộ Office chuẩn, không cần cài thêm.
- Khổ A4, lề 2,5 / 2,0 cm; hình rộng tối đa 16 cm.
