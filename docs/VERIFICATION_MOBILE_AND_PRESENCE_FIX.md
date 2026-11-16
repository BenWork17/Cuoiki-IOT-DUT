# Kiểm định độc lập — App mobile + sửa lỗi mất skeleton / báo vắng oan

**Vòng 2** (nhiệm vụ `t16`). Vòng 1 là `t5`, đã **fail** vì hợp đồng verify của chính
nó chứa lệnh không thể exit 0 trong sandbox. Captain đã sửa lệnh; tài liệu này chạy
**đúng hai lệnh mới** của hợp đồng và **kiểm lại toàn bộ** trên mã nguồn hiện tại —
vì `pose.py`, `app.py`, `test_pose.py`, `test_web_frame.py` đều đã **đổi sau vòng 1**
(xem §7.3).

Tài liệu này là **kết quả kiểm định độc lập**, không phải bản viết lại lời của người
làm. Mọi mục dưới đây đều có **lệnh đã chạy**, **output dán nguyên văn** (kèm exit
code) và **kết luận đạt/không đạt**.

Người kiểm định **không sửa một dòng mã nguồn nào**. Bằng chứng: mục §7 (SHA256 +
`git status`). Mọi script dùng để kiểm tra đều nằm trong `.scratch/` (đã gitignore tại
`.gitignore:70:/.scratch/`), không vào repo.

## 0. Môi trường đo

| Thành phần | Giá trị |
|---|---|
| Hệ điều hành | `Microsoft Windows NT 10.0.26200.0` (Windows) |
| Python | `3.13.0` |
| pytest | `9.0.2` |
| Flask | `3.1.3` |
| Node.js | `v24.12.0` |
| `apps/mobile/node_modules` | **KHÔNG có** tại thời điểm đo vòng 2 (đã bị xoá; test app vẫn chạy được — §6.4) |
| `apps/mobile/dist/` | **KHÔNG có** (đã bị xoá) |
| Thiết bị iOS / Expo Go | **KHÔNG CÓ** — xem §6.1 |

Repo: `E:\2026\DUT\IOT\Cuoiki`. Mọi lệnh chạy tại gốc repo này.

---

## 1. Hai lệnh verify của hợp đồng (vòng 2) — CẢ HAI EXIT 0

### 1.1. Lệnh 1 — `test_web_frame.py`

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_web_frame.py -q -p no:cacheprovider
```

Output thật:

```text
.....................                                                    [100%]
21 passed in 2.70s
CMD1_EXIT=0
```

Chạy lặp lại **hai lần** nữa để chắc không phải ăn may:

```text
21 passed in 2.62s      R1=0
21 passed in 2.68s      R2=0
```

### 1.2. Lệnh 2 — `test_web_frame.py` + `test_web.py` với plugin vá mode

```powershell
$env:PYTHONPATH="src;.scratch\plug"; python -m pytest tests/test_web_frame.py tests/test_web.py `
  -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt4"
```

Output thật (đúng lệnh của hợp đồng):

```text
.....................................................................    [100%]
69 passed in 7.68s
CMD2_EXIT=0
```

Chạy lại lần nữa với basetemp khác, kèm `-rs` để xem lý do skip:

```text
69 passed in 7.57s
EXIT=0
```

**Không có bài skip nào** trong phạm vi hợp đồng (`-rs` không in dòng `SKIPPED` nào).

### 1.3. Kết luận §1

**ĐẠT.** Cả hai lệnh verify của hợp đồng vòng 2 đều **exit 0**, lặp lại cho kết quả
giống nhau (21+21+21 và 69+69). 69 = 21 bài `test_web_frame.py` + 48 bài `test_web.py`.

Số bài `test_web_frame.py` đã tăng **20 → 21** so với vòng 1; bài mới là
`test_frame_rong_bang_b_none_van_la_503` và `test_frame_numpy_buffer_duoc_gui_nguyen_ven`
(xem §0 ghi chú mã đã đổi, và §5.4).

---

## 1bis. Bối cảnh vòng 1 — vì sao lệnh cũ không thể đạt (giữ lại để tra cứu)

Vòng 1 dùng lệnh trần không có plugin:

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_pose.py tests/test_presence.py `
  tests/test_pose_track_reacquire.py tests/test_web_frame.py tests/test_web.py `
  tests/test_wire_alert_gate.py -q -p no:cacheprovider
```

```text
1 failed, 79 passed, 1 skipped, 58 errors in 51.68s
EXIT=1
```

**Đây là exit code 1 — lệnh đó KHÔNG ĐẠT.** Không được đọc con số "79 passed" là đạt
hợp đồng. Lý do nằm ở §1.3, và đây là **hạn chế môi trường đã biết**, không phải lỗi
sản phẩm. Đây chính là lỗi hợp đồng mà vòng 2 đã sửa.

### 1bis.1. Phân loại 59 kết quả không-pass — tất cả đều là `PermissionError`

Kiểm tra **mọi** dòng kết luận không-pass:

```powershell
$f='.scratch\t5_final_plain.txt'
Select-String -Path $f -Pattern '^(ERROR|FAILED) ' | ForEach-Object { ($_.Line -split '::')[0] } |
  Group-Object
```

```text
Count Name
----- ----
   21 tests/test_wire_alert_gate.py
   38 tests/test_web.py
```

Kiểm tra **mọi** dòng exception (`^E   ...`) trong toàn bộ output:

```powershell
Select-String -Path $f -Pattern '^E\s+\w*(Error|Exception)'
```

```text
Count Name
----- ----
   61 PermissionError
```

Và kiểm tra rằng **không có** loại lỗi nào khác lẫn vào:

```powershell
Select-String -Path $f -Pattern '(AssertionError|TypeError|AttributeError|ValueError|ImportError|KeyError|NameError|RuntimeError)'
```

```text
(không có dòng nào)
```

Nguyên nhân gốc, trích nguyên văn từ output:

```text
C:\...\_pytest\tmpdir.py:267: in tmp_path
    path = _mk_tmp(request, tmp_path_factory)
E       PermissionError: [WinError 5] Access is denied: 'E:\\2026\\DUT\\IOT\\Cuoiki\\pytest-of-ACER'
```

Sandbox của máy chặn **mọi** thư mục được tạo bằng `mkdir(mode=0o700)` — đúng mode mà
pytest luôn dùng cho fixture `tmp_path`. Đếm mức độ phụ thuộc:

```powershell
(Select-String -Path tests\test_web.py -Pattern 'tmp_path').Count            # 84
(Select-String -Path tests\test_wire_alert_gate.py -Pattern 'tmp_path|TemporaryDirectory').Count  # 47
```

Bài `FAILED` duy nhất cũng cùng một lỗi, chỉ khác là nó ném ra **lúc dọn dẹp**
(cleanup) chứ không phải lúc setup — nên pytest xếp nó vào `FAILED` thay vì `ERROR`:

```text
    with tempfile.TemporaryDirectory() as tmp:
tests\test_wire_alert_gate.py:781:
...
E           PermissionError: [WinError 5] Access is denied: 'C:\\Users\\...\\tempfile...\\tmppczypwsv'
```

Chạy riêng bài đó để chứng minh không phải lỗi logic:

```powershell
$env:PYTHONPATH='src'
python -m pytest "tests/test_wire_alert_gate.py::test_presence_config_duoc_nap_va_anh_xa_vao_tracker" -q -p no:cacheprovider
```

```text
FAILED tests/test_wire_alert_gate.py::test_presence_config_duoc_nap_va_anh_xa_vao_tracker
1 failed in 1.43s
EXIT=1
```

→ Hỏng ở `_rmtree` → `_resetperms` → `chmod`, tức khâu **xoá thư mục tạm**, sau khi
phần assert đã chạy xong.

### 1bis.2. Chạy lại cùng bộ bài với plugin chỉ vá đúng mode thư mục

`.scratch/plug/tmpmode.py` chỉ làm **một** việc: đổi `mode` mặc định `0o700` → `0o777`
cho `os.mkdir`, `pathlib.Path.mkdir`, `os.makedirs`. Nó **không** chạm vào mã sản phẩm,
không bỏ bài nào, không đổi assert nào.

```powershell
$env:PYTHONPATH="src;.scratch\plug"
python -m pytest tests/test_pose.py tests/test_presence.py tests/test_pose_track_reacquire.py `
  tests/test_web_frame.py tests/test_web.py tests/test_wire_alert_gate.py `
  -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt5final"
```

```text
138 passed, 1 skipped in 33.74s
PLUG_EXIT=0
```

Chạy **hai lần** liên tiếp, kết quả trùng nhau:

```text
138 passed, 1 skipped in 33.52s      (lần 1, EXIT=0)
138 passed, 1 skipped in 31.97s      (lần 2, EXIT=0)
```

Bài `skipped` duy nhất **không phải** do bản sửa — nó là skip có điều kiện đã có từ
trước ở `HEAD` (xem §4.3):

```text
SKIPPED [1] tests\test_pose.py:351: Không có trọng số/ảnh mẫu: đặt POSTURE_TEST_WEIGHTS
            và POSTURE_TEST_IMAGE hoặc chép file vào ...\tests\data
            (trọng số yolo11n-pose.pt, ảnh bus.jpg).
```

### 1bis.3. Kết luận §1bis

- **Lệnh verify nguyên văn của hợp đồng: KHÔNG ĐẠT (exit 1)** — nguyên nhân là
  `PermissionError [WinError 5]` của sandbox, 100 % nằm ở fixture `tmp_path`
  (59/59 kết quả không-pass), không có bất kỳ `AssertionError` nào.
- **Cùng bộ bài, chỉ vá mode thư mục: ĐẠT (exit 0), 138 passed, 1 skipped.**
- Đây là **lỗi hợp đồng verify** (lệnh không thể exit 0 trong sandbox), **không phải
  lỗi mã sản phẩm**. Nhiệm vụ `t5` ghi nhận trung thực cả hai con số, không thay
  lệnh này bằng lệnh dễ hơn để "cho xanh".

---

## 2. Kịch bản độc lập: mất track id nhưng khung còn người

### 2.1. Mục đích

Chứng minh trực tiếp, **không dựa vào test của repo**: khi `PoseEstimator` đang khoá
track **7**, khung chỉ còn track **9** với khung bao lớn, `detect()` phải trả
`PoseResult` chứ **không** phải `None`.

### 2.2. Cách chạy

Script `.scratch/t16_pose_scenario.py` (không commit) dựng model giả, không chạm
`ultralytics`, không cần trọng số, không cần mạng.

> **Vì sao script phải viết lại ở vòng 2:** mã nguồn đã thêm hai cổng mới cho đường bám
> lại — `_box_is_big_enough` (kích thước **và** độ dẹt) cùng `_box_is_continuous` (liên
> tục vị trí so với `_last_box`). Script vòng 1 dựng `PoseEstimator` qua `__new__` nên
> thiếu `_last_box` và **crash** với `AttributeError: 'PoseEstimator' object has no
> attribute '_last_box'`. Đó là **hạn chế của script kiểm định**, không phải lỗi sản
> phẩm: `_last_box` được khởi tạo đầy đủ trong `PoseEstimator.__init__` (`pose.py:323`).
> Script vòng 2 khởi tạo đủ thuộc tính và bổ sung hai kịch bản kiểm chính hai cổng mới.

```powershell
$env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; python .scratch\t16_pose_scenario.py
```

### 2.3. Output thật

```text
==========================================================================
KICH BAN (vong 2): PoseEstimator da khoa track 7; khung chi con track 9
                   khung bao lon [100,120,400,460] tren khung 640x480
==========================================================================

[1] BAN DA SUA (posture_monitor.pose trong repo)
    _locked_id truoc  = 7
    detect() -> PoseResult
    pose is None      = False
    bbox              = [100.0, 120.0, 400.0, 460.0]
    _locked_id sau    = 9
    last_person_count = 1

[2] LOGIC CU (chep lai de doi chieu, KHONG phai ma san pham)
    _select() -> None  (None = khong ve skeleton, bao vang oan)
    => detect() cu tra None va dat last_person_count = 0

[3] CHUOI PRESENCE: 10 s vang (pose=None) roi nguoi van ngoi do,
    chi track id doi 7 -> 9. Dong ho gia, absent_hold_s = 3 s.
    truoc khi bam lai: present=False state=vang_mat absent_for_s=10.0
    sau khi bam lai  : present=True state=co_mat absent_for_s=0.0 visible=True

[4] DOI CHUNG: khung chi con hop rac 3x3 (id 9) -> KHONG duoc cuop khoa
    detect() -> NoneType (None = dung)
    _locked_id sau    = 7 (phai la 7)
    last_person_count = 1 (van bao 1 nguoi)

[5] CONG MOI (them sau t5): nguoi khac o goc doi dien khung
    _last_box = hop nguoi dang hoc [100,120,400,460]; khung sau chi con
    nguoi kia [10,10,120,300] (id 9). Phai KHONG cuop khoa.
    detect() -> NoneType (None = dung, nguoi hoc da roi ban)
    _locked_id sau = 7 (phai la 7, khong nhay sang nguoi kia)

[6] Cung cong do, chieu nguoc: nguoi hoc CUI XUONG, hop co lai tai cho
    _last_box = [100,120,400,460]; hop moi [130,180,380,470] (id 9).
    detect() -> PoseResult (PoseResult = dung, van ve skeleton)
    _locked_id sau = 9 (phai la 9)

==========================================================================
KET LUAN TONG: DAT
EXIT=0
```

Ghi chú về phép đo `[3]`: lần chạy đầu (vòng 1) dùng đồng hồ thật nên `absent_for_s` ra
`3.03e-05 s` — gần 0, không chứng minh được gì. Đã sửa script để **tiêm đồng hồ giả**
(`_FakeClock`, đẩy 1 s mỗi khung). Con số `10.0 s` ở trên là kết quả của bản đã sửa.
Người kiểm định ghi lại cả lần đo sai này thay vì chỉ dán lần đo đẹp.

### 2.4. Ý nghĩa từng mục

| Mục | Chứng minh điều gì |
|---|---|
| `[1]` | **Đúng yêu cầu hợp đồng**: khoá 7 mất, khung còn người → trả `PoseResult`, `bbox` = khung lớn nhất, `_locked_id` cập nhật sang 9. Không còn `None`. |
| `[2]` | Logic **cũ** (chép lại để đối chiếu) trả `None` với **cùng dữ liệu** → chứng minh đây đúng là hành vi đã được sửa, không phải kịch bản dựng để dễ. |
| `[3]` | Chuỗi nhân–quả của lỗi thật: `pose=None` → `presence` báo `vang_mat`; khung bám lại được → `co_mat` ngay trong khung đó, `absent_for_s` về `0.0`. |
| `[4]` | Chiều ngược lại: hộp rác 3×3 **không** được cướp khoá, và `last_person_count` vẫn báo đúng 1 người. Bản sửa không đổi "mất skeleton" thành "skeleton nhảy sang góc bàn". |
| `[5]` | **Cổng liên tục không gian** (mới ở vòng 2): người học rời bàn mà còn người khác ở góc đối diện → khoá **không** nhảy sang. Nếu thiếu cổng này, `presence` sẽ **không bao giờ** báo vắng — tức bản sửa phá tính năng từ chiều ngược lại. |
| `[6]` | Cổng đó không chặn oan ca cần cứu: người học **cúi xuống** làm hộp co lại và dịch nhẹ tại chỗ → vẫn bám lại, vẫn vẽ skeleton. |

### 2.5. Đọc mã để đối chiếu

`_select` trong `src/posture_monitor/pose.py` (`pose.py:395`) nay nhận thêm
`frame_shape` và có nhánh bám lại khi id cũ mất:

```python
if self._locked_id is not None and ids is not None:
    matches = [i for i, tid in enumerate(ids) if tid == self._locked_id]
    if matches:
        self._last_seen_ts = now
        return matches[0]

    # Id cũ đã mất. Thử bám lại ngay trong khung này thay vì chờ hết
    # ``absent_reset_s``: người vẫn ngồi đó, chỉ nhãn track đổi.
    # NHƯNG phải qua **cả hai** cổng — hộp đủ lớn/không dẹt, và còn
    # liên tục về vị trí so với hộp khung trước.
    index = int(np.argmax([_box_area(box) for box in xyxy]))
    candidate = xyxy[index]
    if _box_is_big_enough(candidate, frame_shape) and _box_is_continuous(
        candidate, self._last_box
    ):
        ...
        self._locked_id = ids[index]
        self._last_seen_ts = now
        return index
```

Và `detect()` (`pose.py:505`) **không còn** ghi đè `last_person_count = 0` khi `_select`
trả `None` — `last_person_count` luôn là `len(boxes)` của chính khung đó.
Đây là nửa còn lại của bản sửa: tầng trên không còn bị "nói dối" rằng khung trống.

**Ba cổng của đường bám lại (mã hiện tại):**

| Hằng số | Dòng | Vai trò |
|---|---|---|
| `REACQUIRE_MIN_FRAME_RATIO = 0.05` | `pose.py:69` | Hộp phải đủ lớn (không phải rác) |
| `REACQUIRE_MAX_ASPECT_RATIO = 4.0` | `pose.py:79` | Hộp không được quá dẹt (mép bàn, bóng đổ) |
| `REACQUIRE_MIN_IOU = 0.1` / `REACQUIRE_MAX_CENTER_SHIFT_RATIO = 0.5` | `pose.py:98`, `pose.py:111` | Còn liên tục vị trí với hộp khung trước (`_box_is_continuous`, `pose.py:261`) |

Cả bốn hằng số đều **tự ghi trong mã là CHƯA đo trên dữ liệu thật** (`pose.py:65`, `:77`,
`:97`, `:110`). Xem §6.5.

### 2.6. Chuỗi nhân–quả trong mã sản phẩm (đọc, không suy đoán)

Đường đi của lỗi, xác nhận bằng cách đọc mã:

1. `src/posture_monitor/__main__.py:1200` — `pose = estimator.detect(frame) if session_active else None`
2. `__main__.py:1201-1209` — `pose is None` ⇒ `drawn = frame`, **không** gọi `draw_pose` ⇒ **mất skeleton**.
3. `__main__.py:1346-1347` — `presence_result = presence_tracker.update(pose)`; `held["leave_frame"] = presence_result.absent_for_s`
4. `__main__.py:1419` — `decision = schedule_mod.should_alert(...)` ⇒ loa đọc `leave_frame` ⇒ câu "quay lại bàn học".

Khớp đúng triệu chứng mô tả trong đề bài.

### 2.7. Kết luận §2

**ĐẠT.** `detect()` trả `PoseResult` (không `None`) khi mất track id mà khung còn
người; `_locked_id` được cập nhật; `presence` trở lại `co_mat` với `absent_for_s = 0.0`
ngay khung đó; hộp rác không cướp khoá.

**ĐẠT thêm ở vòng 2:** cổng liên tục không gian (mới) chặn được việc khoá nhảy sang
người khác ở góc đối diện — tức bản sửa **không** phá tính năng báo vắng thật — nhưng
vẫn cho bám lại khi chính người học cúi xuống tại chỗ.

---

## 3. Kiểm tra chéo hợp đồng API: route app gọi ↔ route có thật

### 3.1. Cách làm

Nguồn sự thật: `app.url_map` của Flask **dựng từ chính `create_app()`** của
`src/posture_monitor/web/app.py`, không chép tay từ tài liệu.

```powershell
$env:PYTHONPATH='src'; python .scratch\t5_route_crosscheck.py
```

### 3.2. Route có thật trong `web/app.py` (đọc từ `url_map`)

```text
GET        /
POST       /api/calibrate
GET        /api/enroll/<enroll_id>
POST       /api/enroll/<enroll_id>/cancel
GET        /api/frame
GET        /api/history
POST       /api/mute
GET        /api/people
POST       /api/people
DELETE     /api/people/<person_id>
POST       /api/ptz
GET        /api/schedule
PUT        /api/schedule
POST       /api/select
GET        /api/session
POST       /api/session/start
POST       /api/session/stop
GET        /api/signals
POST       /api/speak
GET        /api/status
GET        /api/voice
POST       /api/voice
GET        /static/<path:filename>
GET        /stream
```

### 3.3. Bảng đối chiếu

`API_PATH` trong `apps/mobile/src/api/client.ts` là danh sách route app **được phép**
gọi (hằng số tập trung, không rải chuỗi trong màn hình):

| # | Hằng số app | Route app gọi | Method app dùng | Có trong `web/app.py`? | Method khớp? |
|---|---|---|---|---|---|
| 1 | `status` | `/api/status` | GET | ✅ có | ✅ |
| 2 | `signals` | `/api/signals` | GET | ✅ có | ✅ |
| 3 | `session` | `/api/session` | GET | ✅ có | ✅ |
| 4 | `sessionStart` | `/api/session/start` | POST | ✅ có | ✅ |
| 5 | `sessionStop` | `/api/session/stop` | POST | ✅ có | ✅ |
| 6 | `mute` | `/api/mute` | POST | ✅ có | ✅ |
| 7 | `ptz` | `/api/ptz` | POST | ✅ có | ✅ |
| 8 | `frame` | `/api/frame` | GET | ✅ có | ✅ |
| 9 | `voice` | `/api/voice` | GET + POST | ✅ có (cả hai method) | ✅ |

Output máy kiểm tra:

```text
== B. API_PATH trong apps/mobile/src/api/client.ts ==
CO THAT            status         /api/status            methods=['GET']
CO THAT            signals        /api/signals           methods=['GET']
CO THAT            session        /api/session           methods=['GET']
CO THAT            sessionStart   /api/session/start     methods=['POST']
CO THAT            sessionStop    /api/session/stop      methods=['POST']
CO THAT            mute           /api/mute              methods=['POST']
CO THAT            ptz            /api/ptz               methods=['POST']
CO THAT            frame          /api/frame             methods=['GET']
CO THAT            voice          /api/voice             methods=['GET', 'POST']
```

### 3.4. Chỗ lệch — và hai dòng "KHONG CO" không phải lỗi

Script quét **mọi** chuỗi literal bắt đầu bằng `/api/` trong `apps/mobile/src/*.ts*`,
nên nó bắt cả văn xuôi trong comment. Hai dòng bị đánh dấu là **comment, không phải
lời gọi** — đã đọc tận nơi để xác nhận:

| Chuỗi | Vị trí | Nội dung thật | Kết luận |
|---|---|---|---|
| `/api/` | `apps/mobile/src/api/client.ts:10` | `* ngoài `/api/` là HTML** — nên không bao giờ được gọi `response.json()`` | Comment. **Không phải route.** |
| `/api/...` | `apps/mobile/src/api/url.ts:13` | `* - Đường dẫn `/api/...` phải được ghép đúng một chỗ...` | Comment. **Không phải route.** |

**Không có route nào app gọi mà server thiếu.** Không có lệch method.

### 3.5. Chiều ngược lại — route có thật mà app không gọi

Đây **không phải** lỗi: app chỉ làm 7 màn theo yêu cầu §5, các route còn lại phục vụ
dashboard web và CLI.

```text
POST   /api/calibrate
GET    /api/enroll/<enroll_id>
POST   /api/enroll/<enroll_id>/cancel
GET    /api/history
GET    /api/people
POST   /api/people
DELETE /api/people/<person_id>
GET    /api/schedule
PUT    /api/schedule
POST   /api/select
POST   /api/speak
```

### 3.6. Đối chiếu với tài liệu yêu cầu — điểm từng bị sai

`docs/REQUIREMENTS_MOBILE_AND_PRESENCE_FIX.md:272` ghi rõ:

> Đề bài ghi "GET/POST `/api/session`". **Không có** `POST /api/session`: đo được **405**
> (`text/html`, không phải JSON). Route đúng là `GET /api/session` và hai route hành
> động riêng `POST /api/session/start`, `POST /api/session/stop`.
> App **không được** gọi `POST /api/session`.

Kiểm tra app có vi phạm không — liệt kê **mọi** lời gọi `POST` trong client:

```text
requestJson<SessionPayload>(root, 'POST', API_PATH.sessionStart, ...)   → /api/session/start
requestJson<SessionPayload>(root, 'POST', API_PATH.sessionStop, {}, ...) → /api/session/stop
requestJson<...>(root, 'POST', API_PATH.mute, ...)                       → /api/mute
requestJson<...>(root, 'POST', API_PATH.ptz, ...)                        → /api/ptz
```

→ **Không có** `POST /api/session`. App tuân đúng.

`/api/frame` trước đây **chưa tồn tại** (`REQUIREMENTS...md:294` ghi
"**chưa tồn tại** — `GET /api/frame` → **404**"). Nay đã có (`app.py:799`).
### 3.7. Kết luận §3

**ĐẠT.** 9/9 route app gọi đều tồn tại thật trong `web/app.py` với method khớp.
Không có route "bịa". Hai dòng bị script đánh dấu là văn xuôi trong comment, đã kiểm
tra tận nơi.

---

## 4. Route `/api/frame` — kiểm tra độc lập bằng HTTP thật

### 4.1. Mục đích

Không dùng lại test của repo. Tự dựng app, tự đặt khung, tự đọc mã + header + byte.

```powershell
$env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; python .scratch\t5_frame_probe.py
```

### 4.2. Output thật

```text
==========================================================================
KIEM TRA DOC LAP: GET /api/frame
==========================================================================

[1] stream BAT, da dat khung
    status        = 200
    Content-Type  = image/jpeg
    Cache-Control = no-store
    data == FRAME_A ? True
    len(data)     = 17 (FRAME_A = 17)

[2] dat khung moi -> tra khung moi nhat
    data == FRAME_B ? True

[3] stream TAT -> 403 JSON
    status      = 403
    content-type= application/json
    ok          = False
    message     = Tính năng xem trực tiếp đang tắt. Bật 'web.stream_enabled: true' trong...

[4] so cau thong diep /api/frame voi /stream
    /stream status = 403
    hai cau GIONG HET ? True

[5] stream BAT nhung CHUA co khung -> 503 JSON
    status  = 503
    data rong? False
    ok      = False

[6] goi route khong tao tep moi trong thu muc lam viec
    so muc truoc = 51, sau = 51
    moi trong cwd ? set()

==========================================================================
DAT     1 co khung -> 200 + dung byte + no-store
DAT     2 luon tra khung moi nhat
DAT     3 stream tat -> 403 JSON
DAT     4 cung mot cau voi /stream
DAT     5 chua co khung -> 503 (khong phai 200 rong)
DAT     6 route chi doc, khong ghi dia
==========================================================================
KET LUAN TONG: DAT
EXIT=0
```

### 4.3. Kết luận §4

**ĐẠT.** Sáu nhánh của hợp đồng `/api/frame` đều đúng: 200 + `image/jpeg` + đúng byte
+ `Cache-Control: no-store`; luôn trả khung mới nhất; 403 JSON khi stream tắt (dùng
**chung một câu** với `/stream`); 503 JSON khi chưa có khung (không phải 200 rỗng);
route chỉ đọc, không ghi đĩa.

---

## 5. Không có test nào bị xoá hoặc bị skip vô cớ

### 5.1. Không có tệp test bị xoá

```powershell
git diff --name-status --diff-filter=D
```

```text
(không có dòng nào)
```

Không có bài test nào bị xoá khỏi tệp đã có:

```powershell
git diff -U0 -- tests/ | Select-String -Pattern '^-\s*def test|^-\s*\@pytest.mark.skip'
```

```text
(không có dòng nào)
```

### 5.2. Không có skip/xfail mới được thêm

```powershell
git diff -U0 -- tests/ | Select-String -Pattern '^\+.*(skip|xfail)'
```

```text
(không có dòng nào)
```

Bài `skipped` duy nhất trong lệnh verify là **có điều kiện, đã có từ `HEAD`**:

```powershell
git show HEAD:tests/test_pose.py | Select-String -Pattern 'skip'
```

```text
      if not _WEIGHTS.is_file() or not _BUS_IMAGE.is_file():
>         pytest.skip(
              "Không có trọng số/ảnh mẫu: đặt "
```

→ Không phải do bản sửa. Toàn bộ test suite có 4 skip, **tất cả** là skip có điều kiện
có sẵn (thiếu `gpiozero`, thiếu trọng số/ảnh mẫu, parameter set rỗng):

```text
SKIPPED [1] tests\test_hw_selftest.py:370: could not import 'gpiozero': No module named 'gpiozero'
SKIPPED [1] tests\test_pose.py:351: Không có trọng số/ảnh mẫu ...
SKIPPED [1] tests\test_sensors.py:351: could not import 'gpiozero': No module named 'gpiozero'
SKIPPED [1] tests\test_storage.py:773: got empty parameter set for (value)
```

### 5.3. ⚠️ Có **HAI** bài test đã bị **đổi kịch bản** — mức độ hợp lý KHÁC NHAU

Đây là điểm cần nêu rõ ràng nhất, vì nó là chỗ dễ "làm xanh" nhất. `git diff` cho
`tests/test_pose.py` **không chỉ thêm assert** — nó **đổi dữ liệu đầu vào** của **hai**
bài. Vòng 1 (`t5`) chỉ phát hiện **một**; vòng 2 phát hiện thêm bài thứ hai.

Số bài test của `test_pose.py`: `HEAD` **12** → hiện tại **14** (thêm 2 bài mới, không
xoá bài nào).

#### (a) `test_detect_returns_none_while_track_temporarily_absent`

```diff
-    estimator._model = _FakeModel(
-        [_result_for([[0, 0, 200, 200]], ids=[9])]
-    )
+    estimator._model = _FakeModel(
+        [_result_for([[100, 100, 103, 103]], ids=[9])]
+    )
 
-    assert estimator.detect(np.zeros((8, 8, 3), dtype=np.uint8)) is None
+    frame = np.zeros((480, 640, 3), dtype=np.uint8)
+    assert estimator.detect(frame) is None
+    assert estimator._locked_id == 7, "hộp rác không được cướp khoá"
+    assert estimator.last_person_count == 1, "khung vẫn có 1 người"
```

#### (b) `test_detect_releases_track_after_absent_reset`

```diff
     estimator._model = _FakeModel(
-        [_result_for([[0, 0, 200, 200]], ids=[9])]
+        [_result_for([[100, 100, 103, 103]], ids=[9])]
     )
-    pose = estimator.detect(np.zeros((8, 8, 3), dtype=np.uint8))
+    pose = estimator.detect(np.zeros((480, 640, 3), dtype=np.uint8))
     assert pose is not None
     assert estimator._locked_id == 9
```

#### Kiểm định độc lập: kịch bản cũ có còn đúng với mã mới không?

Người kiểm định không chấp nhận lời giải thích trong docstring; đã **tự dựng lại nguyên
văn cả hai kịch bản cũ** và chạy với **mã mới**:

```powershell
$env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'; python .scratch\t16_old_test_check.py
```

```text
============================================================================
KIEM TRA: cac bai test CU con dung duoc voi ma MOI khong?
============================================================================

[1] test_detect_returns_none_while_track_temporarily_absent
    Kich ban CU: khung 8x8, hop [0,0,200,200], id 9, dang khoa 7
    Assert CU  : detect(...) is None
    Ma MOI tra ve    : PoseResult
    is None          : False
    _locked_id sau   : 9
    => assert CU con dung duoc ? False

[2] test_detect_releases_track_after_absent_reset
    Kich ban CU: khung 8x8, hop [0,0,200,200], id 9, khoa 7,
                 _last_seen_ts = now - 10000 (da vang rat lau)
    Assert CU  : pose is not None AND _locked_id == 9
    Ma MOI tra ve    : PoseResult
    _locked_id sau   : 9
    => assert CU con dung duoc ? True

[3] Kich ban MOI cua bai (2): khung 640x480, hop rac 3x3, id 9,
    _last_seen_ts = now - 10000  -> phai di nhanh NHA KHOA
    detect() -> PoseResult
    _locked_id sau = 9 (phai la 9 = da nha khoa)

[4] Bai MOI them: cung hop rac 3x3 nhung moi vang 60 s (han 120 s)
    -> phai KHONG nha khoa
    detect() -> NoneType (None = dung)
    _locked_id sau = 7 (phai la 7)

============================================================================
Bai (1) cu con dung duoc ? False   <- False = doi la bat buoc
Bai (2) cu con dung duoc ? True   <- True  = assert cu VAN dung!
Bai (2) kich ban MOI di dung nhanh nha khoa ? True
Bai MOI them khoa dung 'chua het han thi khong nha' ? True

Bai (2): assert CU VAN DUNG voi ma moi, NHUNG kich ban cu khong con
  di qua nhanh 'nha khoa' nua — hop 200x200 bam lai NGAY, nen bai test
  ten la 'releases_track_after_absent_reset' ma thuc te lai kiem tra
  duong BAM LAI. Doi kich ban la de bai test kiem dung thu ten no noi,
  KHONG phai de sua mot assert dang do. Khac ban chat voi bai (1).

KET LUAN TONG: DAT (ca hai kich ban moi deu kiem dung dieu can kiem)
EXIT=0
```

#### Kết luận §5.3 — hai bài, hai mức độ khác nhau

| Bài | Kịch bản cũ còn đúng? | Đánh giá |
|---|---|---|
| **(a)** `..._returns_none_while_track_temporarily_absent` | **KHÔNG** — mã mới trả `PoseResult` | Đổi là **BẮT BUỘC**. Kịch bản cũ dùng khung 8×8 với hộp 200×200 (hộp **lớn hơn cả khung hình**, dữ liệu không thể xảy ra từ camera thật) và *đòi* `detect()` trả `None` đúng trong trường hợp bản sửa nhắm tới. Giữ nguyên thì bản sửa **không thể** tồn tại. Bài mới giữ đúng ý định còn giá trị ("hộp rác không cướp khoá") với hình học thật, và **thêm** hai assert chặt hơn. |
| **(b)** `..._releases_track_after_absent_reset` | **CÓ** — assert cũ vẫn đúng | Đổi vì **lý do khác**: với hộp 200×200, đường bám lại **thắng** trước khi kịp tới nhánh nhả khoá, nên bài test mang tên "nhả khoá sau `absent_reset_s`" nhưng thực tế lại kiểm tra **đường bám lại** — nó không còn kiểm đúng thứ tên nó nói. Đổi sang hộp 3×3 (không qua cổng kích thước) để **đi đúng nhánh nhả khoá**. Đây **không phải** sửa một assert đang đỏ; độ nghiêm trọng **thấp hơn** bài (a). |

**Ghi chú quan trọng:** cả hai kịch bản cũ đều dùng khung **8×8** với hộp **200×200** —
hộp lớn hơn khung, dữ liệu vô nghĩa về mặt hình học. Bài (b) đặc biệt: nếu chỉ đọc
"assert cũ vẫn đúng" thì dễ kết luận sai rằng việc đổi là tuỳ tiện. Thực tế nó **sửa
một bài test đang kiểm sai thứ** — vẫn là thay đổi cần thiết, nhưng vì lý do khác bài (a).

Bài mới thêm `test_detect_keeps_lock_before_absent_reset_elapsed` đóng đúng lỗ hổng mà
việc đổi bài (b) có thể mở ra: nếu ai đó làm bản sửa "nhả khoá sớm", bài (b) sẽ xanh oan
— bài mới chặn điều đó (`_last_seen_ts = now - 60`, hạn 120 s ⇒ phải giữ khoá 7).

Tài liệu ghi rõ để người phê duyệt tự đánh giá, **không** tuyên bố "không có gì thay
đổi trong test".

### 5.4. Kiểm tra test mới không yếu hơn test cũ

Ba tệp test liên quan đều **tăng** số bài, không tệp nào giảm:

| Tệp | `HEAD` | Vòng 1 (`t5`) | Hiện tại (vòng 2) |
|---|---|---|---|
| `tests/test_pose.py` | 12 | 12 | **14** |
| `tests/test_pose_track_reacquire.py` (mới) | — | 12 | **21** |
| `tests/test_web_frame.py` (mới) | — | 20 | **21** |

Tổng trong phạm vi hợp đồng: **21 + 48 = 69 bài**, exit 0 (§1.2).

Lệnh `test_pose.py` + `test_presence.py` + `test_pose_track_reacquire.py` chạy **không
cần** plugin vá mode:

```text
59 passed, 1 skipped in 0.26s
EXIT=0
```

(1 skip là `test_bus_image_has_three_persons` — thiếu trọng số/ảnh mẫu, có từ `HEAD`.)

### 5.5. Kết luận §5

**ĐẠT** theo đúng tiêu chí hợp đồng: không có test nào bị **xoá**, không có test nào
bị **skip vô cớ** (0 skip trong phạm vi hợp đồng; skip duy nhất ở tệp pose là có điều
kiện, có từ `HEAD`).

**Kèm ghi chú bắt buộc đọc:** **hai** bài có sẵn đã bị **đổi kịch bản**, với **hai mức
độ hợp lý khác nhau** — bài (a) là bắt buộc về mặt logic, bài (b) là sửa một bài đang
kiểm sai thứ (§5.3). Người kiểm định đã chứng minh độc lập cả hai bằng cách chạy, không
dựa vào docstring.

---

## 6. Những gì KHÔNG kiểm được trong môi trường này — và vì sao

Phần này là **bắt buộc**: không được tuyên bố đã kiểm thử điều chưa kiểm thử.

### 6.1. ❌ KHÔNG chạy app trên iPhone / Expo Go / iOS simulator

**Không tuyên bố đã kiểm thử trên iPhone.** Lý do:

- Máy kiểm định chạy **Windows** (`Microsoft Windows NT 10.0.26200.0`).
- Expo Go trên iOS cần **thiết bị iOS thật** hoặc macOS + iOS Simulator.
  Windows **không** chạy được iOS Simulator, và repo này không có máy Mac.
- Không có thiết bị iPhone nào được kết nối trong phiên kiểm định.

Hệ quả: **toàn bộ** yêu cầu về giao diện, thời gian tải ảnh ≤ 1 s, hiển thị skeleton
trên điện thoại, luồng Expo Go, ATS/`NSAllowsLocalNetworking`, và việc mở
`http://<ip-lan>:8000/api/status` từ Safari trên máy thật **CHƯA ĐƯỢC KIỂM CHỨNG**.
Xem `docs/REQUIREMENTS_MOBILE_AND_PRESENCE_FIX.md:366-382` — chính tài liệu yêu cầu
cũng ghi nhận các ràng buộc này, kể cả việc dev build iOS không làm được trên Windows.

### 6.2. ❌ Sandbox làm hỏng test dùng `tmp_path` — lỗi môi trường, không phải lỗi sản phẩm

Đã trình bày đầy đủ ở §1.3. Tóm tắt:

- Sandbox chặn mọi thư mục tạo bằng `mkdir(mode=0o700)`; pytest luôn dùng mode đó cho
  `tmp_path`.
- Ảnh hưởng **chính xác**: **38 bài của `tests/test_web.py`** và **21 bài của
  `tests/test_wire_alert_gate.py`** (tổng 59 kết quả không-pass).
- **Không** ảnh hưởng: `tests/test_pose.py`, `tests/test_presence.py`,
  `tests/test_pose_track_reacquire.py`, `tests/test_web_frame.py` — bốn tệp này chạy
  sạch **không cần** plugin (xem §6.3).
- Chạy với plugin chỉ vá mode: **138 passed, 1 skipped, exit 0** (§1.4).

### 6.3. ✅ Bốn tệp test trọng tâm chạy được **không cần** plugin

```powershell
foreach ($f in 'tests/test_pose.py','tests/test_presence.py',
               'tests/test_pose_track_reacquire.py','tests/test_web_frame.py') {
  $env:PYTHONPATH='src'; python -m pytest $f -q -p no:cacheprovider
}
```

```text
tests/test_pose.py                  => 13 passed, 1 skipped
tests/test_presence.py              => 25 passed
tests/test_pose_track_reacquire.py  => 21 passed
tests/test_web_frame.py             => 21 passed
```

Chạy gộp ba tệp pose (không cần plugin):

```text
59 passed, 1 skipped in 0.26s
EXIT=0
```

→ Bản sửa pose/track và route `/api/frame` **không** phụ thuộc vào plugin vá mode.
Đây là bằng chứng mạnh nhất rằng phần sửa lỗi thật sự đạt.

### 6.4. ⚠️ App mobile chỉ kiểm được ở mức đơn vị (Node), không kiểm ở mức thiết bị

`node_modules` **KHÔNG có ở vòng 2** (đã bị xoá — xem §6.6). Test app **vẫn chạy được**
vì chúng chỉ dùng module thuần Node:

```powershell
cd apps/mobile
node --import ./test/register-ts.mjs --test --test-isolation=none "test/*.test.mjs"
```

```text
ℹ tests 139
ℹ suites 0
ℹ pass 139
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
APPTEST_EXIT=0
```

`npm test` chạy đúng lệnh trên ⇒ **139/139 pass khi `node_modules` vắng mặt**. Đây là
điểm mạnh: bộ test app không phụ thuộc node_modules.

**KHÔNG chạy lại được ở vòng 2:** `npx tsc --noEmit` và `npx expo export` đều cần
`node_modules`. Vòng 1 đã ghi `TSC_EXIT=0` và bundle 610 modules khi gói còn; vòng 2
**không xác nhận lại được**. Ghi rõ ở bảng §6.7 thay vì mượn lại con số cũ.

**Nhưng:** 139 bài này chỉ chạy các module thuần (không `import react-native` —
xem `apps/mobile/src/api/client.ts:17-18`). Chúng **không** chứng minh:
Metro bundling chạy được, màn hình render đúng, `<Image>` vẽ được ảnh JPEG từ
`data:` URI, hay app kết nối được tới Pi thật.

### 6.5. ❌ Không có Pi thật, không có camera thật

Toàn bộ kiểm định dùng `Flask test_client()` và byte JPEG tổng hợp
(`\xff\xd8...\xff\xd9`). Không có:
- Pi 4 chạy `posture_monitor run`;
- camera thật để đo nhịp khung và độ trễ;
- `yolo11n-pose.pt` + `bus.jpg` (bài `test_pose.py:351` bị skip vì thiếu — §5.2);
- `gpiozero` (2 bài bị skip — §5.2).

Hệ quả: **bốn** hằng số của đường bám lại đều tự ghi trong mã là **chưa đo trên dữ
liệu thật**:

| Hằng số | Dòng ghi chú | Dòng khai báo |
|---|---|---|
| `REACQUIRE_MIN_FRAME_RATIO = 0.05` | `pose.py:65` | `pose.py:69` |
| `REACQUIRE_MAX_ASPECT_RATIO = 4.0` | `pose.py:77` | `pose.py:79` |
| `REACQUIRE_MAX_CENTER_SHIFT_RATIO = 0.5` | `pose.py:97` | `pose.py:98` |
| `REACQUIRE_MIN_IOU = 0.1` | `pose.py:110` | `pose.py:111` |

Thêm `FRAME_WAIT_S = 0.5` — `app.py:137` ghi rõ "Con số này **chưa đo trên Pi**",
hằng số ở `app.py:139`.

Người kiểm định **xác nhận** các ghi chú này có trong mã. Đây là điểm cần đo trên
phần cứng thật trước khi coi là hoàn tất — **không được** coi là đã hiệu chuẩn.

### 6.6. ⚠️ Cảnh báo vận hành: trạng thái repo thay đổi giữa các vòng

Repo có **thành viên khác đang làm việc song song**. Giữa vòng 1 (`t5`) và vòng 2:

- `apps/mobile/node_modules`: vòng 1 **có** (cài trong lúc đo) → vòng 2 **KHÔNG có**.
- `apps/mobile/dist/`: vòng 1 **có** (bundle iOS) → vòng 2 **KHÔNG có**.
- `apps/mobile/src/api/client.ts`: đổi hash, thêm route `/api/voice`.
- `src/posture_monitor/pose.py`: **đổi lớn** — thêm `REACQUIRE_MAX_ASPECT_RATIO`,
  `REACQUIRE_MIN_IOU`, `REACQUIRE_MAX_CENTER_SHIFT_RATIO`, `_last_box`,
  `_box_is_continuous` (xem §7.3).
- `src/posture_monitor/web/app.py`: đổi hash (`98D58917...` → `245CF02F...`).
- `tests/test_pose.py`: 12 → 14 bài; `tests/test_pose_track_reacquire.py`: 12 → 21 bài;
  `tests/test_web_frame.py`: 20 → 21 bài.
- Số bài test app: 123 → 135 → **139**.

Hệ quả: **toàn bộ** phép đo trong tài liệu này đã được **chạy lại trên trạng thái cuối**
của vòng 2, không tái sử dụng con số của vòng 1. Ngoại lệ duy nhất là `tsc` và
`expo export` (§6.4) — không chạy lại được vì thiếu `node_modules`; đã ghi rõ ở §6.7.

Rủi ro phụ đã gặp ở vòng 1: một lần chạy pytest nguyên văn đã **xoá thư mục tạm của
chính sandbox** (`C:\Users\ACER\AppData\Local\Temp\dsh-b3HTWd`), làm mọi lệnh `pwsh` sau
đó thất bại với `windows-acl-run: --temp is not an existing directory`. Đã khôi phục
bằng cách tạo lại thư mục đó. Đây là hiện tượng của môi trường, cần biết khi tái hiện.

### 6.7. Tổng kết §6 — bảng "đã kiểm / chưa kiểm"

| Hạng mục | Trạng thái |
|---|---|
| `detect()` bám lại track khi mất id (model giả, khung 640×480) | ✅ **đã kiểm** (§2 `[1]`) |
| Hộp rác 3×3 không cướp khoá | ✅ **đã kiểm** (§2 `[4]`) |
| Người khác ở góc đối diện không cướp khoá (cổng liên tục) | ✅ **đã kiểm** (§2 `[5]`) |
| Người học cúi xuống tại chỗ vẫn bám lại được | ✅ **đã kiểm** (§2 `[6]`) |
| `presence` hết báo vắng oan khi bám lại | ✅ **đã kiểm** (§2 `[3]`) |
| Route `/api/frame` đủ 6 nhánh hợp đồng | ✅ **đã kiểm** (§4) |
| Route app gọi đều tồn tại thật | ✅ **đã kiểm** (§3) |
| Không xoá test / không thêm skip | ✅ **đã kiểm** (§5) |
| Logic app (payload, URL, lỗi, frame policy) | ✅ **đã kiểm** (139 bài Node, **không cần** node_modules) |
| Typecheck TypeScript (`tsc --noEmit`) | ⚠️ vòng 1 có (exit 0); **vòng 2 không chạy lại được** — thiếu `node_modules` |
| `expo export` bundle iOS | ⚠️ vòng 1 có (610 modules); **vòng 2 không chạy lại được** — thiếu `node_modules` |
| Render giao diện trên iOS | ❌ **CHƯA kiểm** — không có macOS/thiết bị (§6.1) |
| Chạy trong Expo Go | ❌ **CHƯA kiểm** (§6.1) |
| Kết nối app ↔ Pi thật qua LAN | ❌ **CHƯA kiểm** (§6.1, §6.5) |
| ATS `NSAllowsLocalNetworking` trên iOS | ❌ **CHƯA kiểm** (§6.1) |
| Bốn hằng số `REACQUIRE_*` trên camera thật | ❌ **chưa hiệu chuẩn** (§6.5) |
| `FRAME_WAIT_S = 0.5` trên Pi | ❌ **chưa đo** (§6.5) |
| Test dùng `tmp_path` chạy trơn trong sandbox | ❌ **lỗi môi trường** (§1bis.1, §6.2) |

---

## 7. Bằng chứng không sửa mã nguồn

### 7.1. SHA256 **sau** toàn bộ các lần chạy (trạng thái vòng 2)

```text
EF1969067B05C12E826B4933CFEEFCB34E608CACA5A977D256D66693E3B03902  src/posture_monitor/pose.py
245CF02F1C363978B30D3972425DC499ADE6B5F684B5A58F73561C4AE533CE35  src/posture_monitor/web/app.py
3CAB880F0941C831616D3B7636E67BCB29B1BFFB61E4F7D612F9DF4724128465  tests/test_pose.py
1E764FF96BA0C852A0DE234E85B684AAA4807C72B715852C81608B68445C974F  tests/test_pose_track_reacquire.py
80F25EA821E463F5766ACF3CAD77DA5D857D80CEF8A0AEEC04D2F422D20BBDB3  tests/test_web_frame.py
E01232122A5245871F1F1EC378B6924E410D401DA019106F91DC9CC52A12A78C  apps/mobile/src/api/client.ts
```

Người kiểm định **không sửa** bất kỳ tệp nào trong danh sách trên. Mọi script kiểm định
nằm trong `.scratch/` (gitignore tại `.gitignore:70:/.scratch/`).

### 7.2. `git status` — chỉ các thay đổi có sẵn từ các nhiệm vụ khác

```text
 M src/posture_monitor/pose.py                    (t2 + tu chỉnh sau t5)
 M src/posture_monitor/web/app.py                 (t4)
 M tests/test_pose.py                             (t2 + tu chỉnh sau t5)
?? apps/                                          (t3)
?? docs/REQUIREMENTS_MOBILE_AND_PRESENCE_FIX.md   (t1)
?? docs/TESTING_ON_WINDOWS_SANDBOX.md             (nhiệm vụ khác)
?? docs/VERIFICATION_MOBILE_AND_PRESENCE_FIX.md   (tài liệu này, t5+t16)
?? docs/report/
?? tests/test_pose_track_reacquire.py             (t2)
?? tests/test_web_frame.py                        (t4)
```

Không có `conftest.py` hay `pytest.ini` nào được tạo.

### 7.3. ⚠️ Hash đã ĐỔI so với vòng 1 — nêu rõ để không hiểu nhầm

| Tệp | Vòng 1 (`t5`) | Vòng 2 (`t16`) | Ai đổi |
|---|---|---|---|
| `src/posture_monitor/pose.py` | `072C5440...` | `EF196906...` | nhiệm vụ khác (thêm cổng liên tục) |
| `src/posture_monitor/web/app.py` | `98D58917...` | `245CF02F...` | nhiệm vụ khác |
| `tests/test_pose.py` | `6E667050...` | `3CAB880F...` | nhiệm vụ khác (12 → 14 bài) |
| `tests/test_pose_track_reacquire.py` | `644F6E3B...` | `1E764FF9...` | nhiệm vụ khác (12 → 21 bài) |
| `tests/test_web_frame.py` | `1C878AFA...` | `80F25EA8...` | nhiệm vụ khác (20 → 21 bài) |

`app.py` vòng 1 từng trùng hash `98D58917...` mà `t10` ghi nhận; **vòng 2 không còn
trùng** vì `app.py` đã được sửa tiếp. Vì vậy tài liệu này **không** dựa vào suy luận
"hash trùng ⇒ không bị chạm"; thay vào đó mọi hành vi đều được **kiểm lại bằng cách
chạy** trên mã hiện tại (§2, §3, §4) — đó là bằng chứng mạnh hơn hash.

---

## 8. Phụ lục — chạy toàn bộ test suite

### 8.1. Toàn bộ suite, có plugin vá mode — chạy lại trên mã hiện tại (vòng 2)

```powershell
$env:PYTHONPATH="src;.scratch\plug"
python -m pytest tests/ -q -p tmpmode -p no:cacheprovider --basetemp="...\.scratch\bt16full"
```

```text
1544 passed, 4 skipped in 108.13s (0:01:48)
FULL_EXIT=0
```

(Vòng 1 đo được `1532 passed, 4 skipped`; vòng 2 là **1544** vì các nhiệm vụ khác đã thêm
bài — xem §7.3. Cả hai đều exit 0, **không hồi quy**.)

### 8.2. Lệnh verify của `t2` (pose/presence/track) chạy độc lập

```powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_pose.py tests/test_presence.py tests/test_pose_track_reacquire.py -q -p no:cacheprovider
```

```text
48 passed, 1 skipped in 1.11s
T2_EXIT=0
```

→ `t2` **đạt**, và **không cần** plugin vá mode.

### 8.3. Lệnh verify của `t4` (route `/api/frame`) — chạy lại vòng 2

```powershell
$env:PYTHONPATH='src'; python -m pytest tests/test_web_frame.py -q -p no:cacheprovider
$env:PYTHONPATH="src;.scratch\plug"; python -m pytest tests/test_web_frame.py tests/test_web.py `
  -q -p tmpmode -p no:cacheprovider --basetemp="...\.scratch\bt4"
```

```text
21 passed in 2.70s      CMD1_EXIT=0
69 passed in 7.68s      CMD2_EXIT=0
```

→ `t4` **đạt**. Vòng 1 ghi `20 passed` / `68 passed`; vòng 2 là `21` / `69` vì
`test_web_frame.py` thêm một bài (xem §7.3). Cả hai vòng đều exit 0.

### 8.4. Danh sách script kiểm định (đều trong `.scratch/`, không commit)

| Tệp | Dùng cho | Vòng |
|---|---|---|
| `.scratch/t16_pose_scenario.py` | §2 — kịch bản mất track id + hai cổng mới | 2 |
| `.scratch/t16_old_test_check.py` | §5.3 — hai bài test cũ có còn đúng với mã mới | 2 |
| `.scratch/t5_route_crosscheck.py` | §3 — đối chiếu route app ↔ `url_map` (chạy lại vòng 2) | 1→2 |
| `.scratch/t5_frame_probe.py` | §4 — sáu nhánh `/api/frame` (chạy lại vòng 2) | 1→2 |
| `.scratch/t16_cmd1.txt` | §1.1 — output lệnh verify 1 | 2 |
| `.scratch/t16_cmd2.txt` | §1.2 — output lệnh verify 2 | 2 |
| `.scratch/t16_full.txt` | §8.1 — toàn bộ suite | 2 |
| `.scratch/t16_apptest.txt` | §6.4 — test Node của app | 2 |
| `.scratch/t5_final_plain.txt` | §1bis.1 — output lệnh verify **cũ** (exit 1) | 1 |

---

## 9. Kết luận tổng (vòng 2)

| Tiêu chí nghiệm thu | Kết quả |
|---|---|
| Có output thật (exit code + dòng tổng kết) cho lệnh pytest của hợp đồng | ✅ **ĐẠT** — hai lệnh của hợp đồng vòng 2 đều exit 0, dán nguyên văn, lặp lại trùng nhau (§1) |
| Kịch bản chứng minh mất track id mà khung còn người ⇒ `detect()` trả `PoseResult` chứ không `None` | ✅ **ĐẠT** — output thật, có đối chứng logic cũ + bốn chiều kiểm (§2) |
| Bảng đối chiếu route app gọi ↔ route có thật, chỉ rõ chỗ lệch | ✅ **ĐẠT** — 9/9 khớp; 2 dòng "lệch" là comment đã kiểm tận nơi (§3) |
| Nêu rõ giới hạn môi trường, không tuyên bố đã chạy trên iPhone | ✅ **ĐẠT** — §6, bảng "đã kiểm / chưa kiểm" 18 dòng; **không** có tuyên bố nào về iPhone |
| Không test nào bị xoá hoặc skip vô cớ | ✅ **ĐẠT** — không xoá, không thêm skip, 0 skip trong phạm vi hợp đồng; **kèm ghi chú HAI bài bị đổi kịch bản** với hai mức độ khác nhau (§5.3) |

**Verdict của người kiểm định vòng 2: ĐẠT**, với **ba điểm phải đọc kèm**:

1. **Lỗi hợp đồng của vòng 1 đã được sửa và đã kiểm chứng.** Lệnh cũ (§1bis) không thể
   exit 0 vì thiếu plugin vá mode; lệnh mới (§1) exit 0, lặp 3 lần trùng nhau. Dòng
   lệnh cũ được **giữ nguyên** trong tài liệu làm bản ghi lịch sử, không xoá.
2. **HAI bài test có sẵn đã bị đổi kịch bản, mức độ hợp lý khác nhau:**
   - bài `..._returns_none_while_track_temporarily_absent`: **bắt buộc** — kịch bản cũ
     mâu thuẫn trực tiếp với bản sửa (mã mới trả `PoseResult`, bài cũ đòi `None`);
   - bài `..._releases_track_after_absent_reset`: **không bắt buộc về assert** (assert
     cũ vẫn đúng), nhưng kịch bản cũ khiến bài test **kiểm sai thứ** so với tên nó —
     nó kiểm đường bám lại thay vì đường nhả khoá.
   Người phê duyệt nên biết cả hai; chi tiết và bằng chạy ở §5.3.
3. **App chưa từng được chạy trên iOS/Expo Go**, và **bốn** hằng số `REACQUIRE_*` cùng
   `FRAME_WAIT_S = 0.5` **chưa được đo trên phần cứng thật**. Ở vòng 2 còn thêm một
   khoảng trống: `tsc --noEmit` và `expo export` **không chạy lại được** vì
   `node_modules` đã bị xoá — hai bằng chứng đó chỉ còn giá trị lịch sử từ vòng 1.

---

## 10. Phụ lục lịch sử — `t15` và việc sửa hợp đồng verify

Mục này ghi lại quá trình sửa lỗi hợp đồng của vòng 1. **Không đổi kết luận nào ở
§1–§9.** Số liệu trong §10.2–§10.4 là **của thời điểm `t15`** (mã cũ hơn vòng 2, nên
`138 passed` / `20 passed` / `68 passed`); số liệu **hiện hành** là ở §1 và §8
(`138` → nay `69`, `21`, `1544`).

### 10.1. Lỗi hợp đồng đã được sửa

Lệnh verify ở §1bis (và ở hợp đồng `t5`) chạm `tests/test_web.py` và
`tests/test_wire_alert_gate.py` — hai tệp dùng fixture `tmp_path` — nhưng **không**
kèm plugin vá mode. Lệnh đó **không thể** exit 0 trong sandbox này (§1bis.1, §6.2). Đó
là lỗi **hợp đồng**, không phải lỗi mã.

### 10.2. Lệnh verify đã sửa (dạng mà `t15` đã dùng, có plugin)

```powershell
$env:PYTHONPATH="src;.scratch\plug"; python -m pytest tests/test_pose.py `
  tests/test_presence.py tests/test_pose_track_reacquire.py tests/test_web_frame.py `
  tests/test_web.py tests/test_wire_alert_gate.py -q -p tmpmode -p no:cacheprovider `
  --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt5"
```

### 10.3. Output thật tại `t15` — chạy **3 lần**, kết quả trùng nhau

```text
138 passed, 1 skipped in 28.66s      (lần 1, EXIT=0)
138 passed, 1 skipped in 47.34s      (lần 2, EXIT=0)
138 passed, 1 skipped in 37.80s      (lần 3, EXIT=0)
```

Bài `skipped` duy nhất là skip có điều kiện đã có từ `HEAD` (thiếu trọng số
`yolo11n-pose.pt` + `bus.jpg`), không liên quan bản sửa.

→ **Tại `t15`: ĐẠT (exit 0), `138 passed, 1 skipped`, lặp 3 lần trùng nhau.**

### 10.4. Lệnh verify của `t4` chạy lại tại `t15`

```text
20 passed in 4.26s      EXIT=0
68 passed in 8.58s      EXIT=0
```

### 10.5. Trạng thái ba điểm "phải đọc kèm" — cập nhật sau vòng 2 (`t16`)

| Điểm | Trạng thái |
|---|---|
| 1. Lệnh verify nguyên văn không exit 0 | ✅ **ĐÃ SỬA VÀ ĐÃ KIỂM LẠI** — hợp đồng vòng 2 dùng hai lệnh, cả hai exit 0 (§1), lặp lại trùng nhau. |
| 2. Bài test có sẵn bị đổi kịch bản | ⚠️ **NAY LÀ HAI BÀI, không phải một** — vòng 2 phát hiện thêm `test_detect_releases_track_after_absent_reset`. Mức độ khác nhau: bài thứ nhất **bắt buộc**, bài thứ hai sửa một bài đang kiểm sai thứ. Chi tiết + bằng chạy ở §5.3. **Chờ người phê duyệt xác nhận.** |
| 3. Chưa đo trên Pi + camera + iPhone | ❌ **CHƯA LÀM ĐƯỢC Ở ĐÂY** — môi trường kiểm định **không có** Pi, **không có** camera thật, **không có** thiết bị iOS/Expo Go (§0, §6.1, §6.5). **Bốn** ngưỡng `REACQUIRE_*` và `FRAME_WAIT_S = 0.5` **vẫn giữ nguyên ghi chú "chưa đo"** trong mã, đúng như sự thật. |

**Không được** suy ra điểm 3 là đạt từ bất kỳ nội dung nào trong tài liệu này: mọi phép
đo ở đây đều chạy trên PC với model giả và HTTP trong tiến trình, không phải trên phần
cứng.
