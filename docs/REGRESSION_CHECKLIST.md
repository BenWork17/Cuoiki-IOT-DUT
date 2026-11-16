# Checklist hồi quy — chạy trước khi tin một thay đổi

Dùng khi sửa `src/posture_monitor/pose.py`, `presence.py`, `web/app.py`, hoặc `apps/mobile/`.
Mục tiêu: **~10 phút**, biết ngay thay đổi có phá lại lỗi cũ hay không.

Cách dùng: tick từng ô. Ô nào sai kết quả kỳ vọng thì **dừng**, đọc ghi chú cuối mục đó.

> **Quy tắc bắt buộc:** mọi lệnh `pytest` phải có `-p tmpmode` **và** `--basetemp` trỏ vào
> `.scratch/`. Không bao giờ chạy `pytest` trần trên máy Windows này — nó sẽ hỏng vì
> `PermissionError` khi tạo `tmp_path`, và cái hỏng đó **không phải** lỗi sản phẩm.
> Chi tiết + nội dung plugin: [`docs/TESTING_ON_WINDOWS_SANDBOX.md`](TESTING_ON_WINDOWS_SANDBOX.md).

---

## 0. Chuẩn bị (làm một lần mỗi phiên)

- [ ] **0.1** Đứng ở gốc repo (`E:\2026\DUT\IOT\Cuoiki`).
- [ ] **0.2** Nạp biến môi trường — thiếu dòng này `-p tmpmode` báo `No module named 'tmpmode'`:
  ```powershell
  $env:PYTHONPATH = "src;.scratch\plug"
  ```
  - [ ] Kỳ vọng: không có output. Plugin nằm ở `.scratch\plug\tmpmode.py` (bị gitignore, tạo theo
        hướng dẫn ở `TESTING_ON_WINDOWS_SANDBOX.md` §2).

> Mỗi lần chạy dưới đây dùng một `bt<N>` **mới**. `--basetemp` trỏ vào thư mục đã tồn tại với mode sai
> sẽ hỏng lại y như không có `--basetemp`.

---

## A. Kiểm Python (≈6 phút)

- [ ] **A1** Bản sửa bám lại track id — nhóm dễ vỡ nhất:
  ```powershell
  python -m pytest tests/test_pose.py tests/test_presence.py tests/test_pose_track_reacquire.py -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt1"
  ```
  - [ ] Kỳ vọng: **`59 passed, 1 skipped`**.
  - Ghi chú: 1 skip là bài tích hợp cần trọng số YOLO thật — đúng, không phải hỏng.

- [ ] **A2** Route khung ảnh `GET /api/frame`:
  ```powershell
  python -m pytest tests/test_web_frame.py -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt2"
  ```
  - [ ] Kỳ vọng: **`21 passed`**.

- [ ] **A3** Route khung ảnh không làm hỏng dashboard cũ:
  ```powershell
  python -m pytest tests/test_web_frame.py tests/test_web.py -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt3"
  ```
  - [ ] Kỳ vọng: **`69 passed`**.

- [ ] **A4** Toàn bộ test Python (≈2 phút):
  ```powershell
  python -m pytest tests/ -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt4"
  ```
  - [ ] Kỳ vọng: **`1567 passed, 4 skipped`**, **`0 failed`**.
  - Ghi chú: 4 skip là các bài cần trọng số/model thật.
  - **Con số này tăng khi có tệp test mới** — nó đã từng là 1544 trước khi
    `tests/test_calibrate_reacquire.py` (24 test) được thêm vào. Vì vậy điều kiện đúng là
    **`0 failed`**; nếu số `passed` lớn hơn kỳ vọng thì kiểm xem tệp test nào mới, đừng coi là hỏng.
    Nếu số `passed` **nhỏ hơn** → có test bị bỏ sót hoặc tệp không được thu thập.

- [ ] **A5** Không có lỗi nhiễu môi trường lẫn vào:
  - [ ] Kỳ vọng: output **không** chứa `PermissionError`, `WinError 5`, hay `Access is denied`.
  - Nếu có → `--basetemp` đang trỏ vào thư mục cũ, hoặc thiếu `-p tmpmode`. Đổi sang `bt<N>` mới.
- [ ] **A6** Không có bài nào **đỏ chỉ khi chạy cùng nhau** (test isolation):
  - [ ] Nếu A4 có 1 bài failed nhưng chạy riêng tệp đó lại xanh → đó là lỗi rò trạng thái giữa các test,
        **không** phải lỗi sản phẩm, nhưng vẫn phải sửa. Ghi lại tên bài và tệp.
  - Ghi chú: đã gặp đúng kiểu này một lần trong phiên (một bài của `test_calibrate_reacquire.py` đỏ khi
    chạy cả bộ, xanh khi chạy riêng) — lúc đó tệp đang được ghi dở bởi tiến trình khác. Chạy lại A4 một
    lần nữa trước khi kết luận.

---

## B. Kiểm app Expo (≈3 phút)

- [ ] **B1** Cài + test logic thuần (tầng này **không** cần `node_modules`):
  ```powershell
  cd apps\mobile
  npm install
  npm test
  ```
  - [ ] Kỳ vọng: **`pass 139`**, `fail 0`.

- [ ] **B2** Test giao diện thật trong jsdom:
  ```powershell
  npm run verify
  ```
  - [ ] Kỳ vọng: **`pass 10`**, `fail 0` (4 bài Camera + 6 bài Giọng đọc).

- [ ] **B3** Kiểu TypeScript:
  ```powershell
  npx tsc --noEmit
  ```
  - [ ] Kỳ vọng: **không có output**, exit code **0**.

- [ ] **B4** Đóng gói được cho iOS:
  ```powershell
  npx expo export --platform ios --output-dir .scratch-export --no-bytecode
  ```
  - [ ] Kỳ vọng: `iOS Bundled …` và bundle **~1,18 MB**, exit code **0**.
  - Ghi chú: `--no-bytecode` là bắt buộc trên máy này — bước tạo bytecode Hermes cần `spawn`, sandbox chặn.
  - [ ] Dọn sau khi xong: `Remove-Item -Recurse -Force .scratch-export`, rồi `cd ..\..`.

---

## C. Kiểm hành vi hai chiều của bản sửa track (≈5 phút, cần Pi + camera)

Đây là phần **dễ vỡ nhất** và đã từng bị phá đúng ở đây. Test tự động khoá được phần lớn, nhưng
chỉ cảnh thật mới xác nhận giả thuyết "BotSORT đổi track id".

Chuẩn bị: dashboard chạy trên Pi, điện thoại cùng Wi-Fi, app đã nhập địa chỉ LAN và **Kiểm tra kết nối** thấy "Kết nối tốt".

- [ ] **C1** **Ngồi yên trong khung, đang trong phiên học**
  - [ ] `/api/status` có `state` **khác** `ABSENT` (thường `GOOD`/`WARN`).
  - [ ] Khung hình có **skeleton** vẽ trên người.

- [ ] **C2** **Cúi gập xuống bàn vài giây rồi ngồi thẳng lại** (động tác làm BotSORT đổi track id)
  - [ ] Skeleton **vẫn còn** — được phép nhảy nhẹ một khung rồi bám lại, **không** được mất hẳn.
  - Nếu mất rồi chỉ hiện lại sau rất lâu → bản sửa **chưa** hiệu lực trên cảnh này.

- [ ] **C3** **Đứng dậy, rời khỏi khung**
  - [ ] Sau **~3–5 s** `presence` chuyển `vang_mat`.
  - [ ] Sau đó loa báo *"Bạn ơi, quay lại bàn học nhé"*.
  - Con số: `presence.absent_grace_s = 3.0` (`config.yaml:202`) + `schedule.kinds.leave_frame.hold_s = 5` (`config.yaml:330`).
  - **Không** báo → bản sửa đang bám nhầm người. Đây là lỗi nghiêm trọng, xem mục D.

- [ ] **C4** **Rời bàn NHƯNG còn người khác trong khung** ← chiều quan trọng nhất
  - [ ] **VẪN phải báo vắng.**
  - Nếu im lặng → cổng liên tục đang bám nhầm sang người kia. Đúng loại lỗi mà bản sửa này sinh ra
    nếu đặt ngưỡng quá lỏng — xem mục D.

- [ ] **C5** **Ngồi lại vào khung**
  - [ ] Loa **im** trong ~1 s (không lặp lại "quay lại bàn học").
  - [ ] Skeleton hiện lại.

> Qua C1–C5 → bản sửa đúng trên máy thật. Hỏng C1/C2 → chưa sửa được lỗi gốc. Hỏng C3/C4 → bản sửa
> **phá** tính năng báo rời bàn; nguyên nhân nhiều khả năng ở các hằng số mục D.

---

## D. Bốn hằng số `REACQUIRE_*` — **CHƯA hiệu chuẩn trên dữ liệu thật**

Đọc trước khi chỉnh bất kỳ hằng số nào trong nhóm này:

| Hằng số | Giá trị | Vị trí | Vai trò |
|---|---|---|---|
| `REACQUIRE_MIN_FRAME_RATIO` | `0.05` | `pose.py:69` | Hộp phải rộng **và** cao ≥ 5% cạnh khung |
| `REACQUIRE_MAX_ASPECT_RATIO` | `4.0` | `pose.py:79` | Loại hộp quá dẹt (mép bàn, bóng đổ) |
| `REACQUIRE_MAX_CENTER_SHIFT_RATIO` | `0.5` | `pose.py:98` | Tâm không lệch quá 0,5 × cạnh dài hộp trước |
| `REACQUIRE_MIN_IOU` | `0.1` | `pose.py:111` | IoU tối thiểu để coi là cùng người |

- [ ] **D1** Hiểu rằng cả bốn là **lựa chọn có lý do, không phải kết quả đo**. Docstring từng hằng số đã ghi
      "CHƯA đo trên dữ liệu thật". Đừng trích chúng như thể đã kiểm.
- [ ] **D2** Muốn có số đo thật thì chạy công cụ hiệu chuẩn (đã có trong repo):
  ```powershell
  python scripts/calibrate_reacquire.py --frames 300
  python scripts/calibrate_reacquire.py --source file:buoi_hoc.mp4 --frames 600
  ```
  - [ ] Kỳ vọng: in ra phân bố IoU / khoảng cách tâm giữa hai hộp liên tiếp, để chọn ngưỡng có căn cứ.
  - Script chạy **đúng `PoseEstimator` và `config.yaml`** như lúc chạy thật, không phải bản mô phỏng.
- [ ] **D3** Biết **bán kính lọt đã đo: ~180 px**. Người khác đi ngang trong bán kính đó có thể bị coi là
      cùng người → khoá nhảy sang họ → **chính là ca C4 hỏng**. Đây là giới hạn đã biết, không phải suy đoán.
- [ ] **D4** Nếu chỉnh một hằng số: chạy lại **A1** và **C1–C5** trước khi tin. Ngưỡng quá chặt làm người
      cúi xuống mất skeleton (lỗi cũ quay lại); quá lỏng làm C4 hỏng.

---

## E. Ba việc **CHƯA** kiểm được — đừng tuyên bố là đã xong

Cả ba đã được ghi chi tiết ở [`docs/KNOWN_LIMITATIONS_AND_NEXT_STEPS.md`](KNOWN_LIMITATIONS_AND_NEXT_STEPS.md) §2.

- [ ] **E1** **Chưa chạy trên iPhone / Expo Go thật.** Chưa có thiết bị. `npm run verify` mô phỏng iOS
      bằng jsdom + react-native-web: chứng minh logic và luồng UI, **không** chứng minh layout/typography.
      → `KNOWN_LIMITATIONS…` §2.1.
- [ ] **E2** **Chưa chạy trên Pi + camera thật.** Toàn bộ số đo của bản sửa là trên PC với model giả;
      việc BotSORT thật sự đổi track id vẫn là **giả thuyết có dẫn chứng**. Bước C là cách xác nhận.
      → `KNOWN_LIMITATIONS…` §2.3.
- [ ] **E3** **Chưa kiểm chứng ATS với `http://`.** `ios.infoPlist` **vô hiệu trong Expo Go** (Info.plist là
      của Expo Go, không phải của project). → `KNOWN_LIMITATIONS…` §2.2.

---

## Khi có ô đỏ

| Ô đỏ | Nghĩa là | Làm gì |
|---|---|---|
| A1 | Bản sửa bám track id bị phá | Đọc `tests/test_pose_track_reacquire.py`, sửa `pose.py` |
| A2/A3 | Route `/api/frame` bị phá | Đọc `tests/test_web_frame.py` |
| A4 kèm `PermissionError` | Môi trường, **không** phải sản phẩm | Dùng `--basetemp` mới + `-p tmpmode` |
| B1/B2 | Logic app hoặc luồng UI bị phá | `npm test` / `npm run verify` chỉ đúng bài đỏ |
| B3 | Lỗi kiểu TypeScript | `npx tsc --noEmit` chỉ đúng tệp |
| C2 | **Chưa** sửa được lỗi gốc trên cảnh thật | §2.3 — cần Pi + camera |
| C3/C4 | Bản sửa **phá** báo rời bàn | Mục D — ngưỡng `REACQUIRE_*` quá lỏng |

**Không** sửa test để nó xanh. Nếu một test khoá hành vi mà bạn cho là sai, sửa **cả** test **và** giải thích
trong commit — đó là cách duy nhất để lần sau còn biết vì sao.
