# Yêu cầu: sửa lỗi mất skeleton / báo vắng oan + app Expo Go

Tài liệu này chốt **yêu cầu kiểm chứng được** cho hai hạng mục:

- **(A)** Lỗi "vào phiên học thì mất skeleton và hệ thống báo *quay lại bàn học* liên tục dù người vẫn ngồi trong khung".
- **(B)** App React Native chạy bằng **Expo Go trên iOS**, điều khiển và xem dashboard của Pi.

Mọi kết luận đều kèm `file:dòng` của mã nguồn **hiện tại**. Chỗ nào chỉ suy ra từ việc đọc mã thì ghi rõ là **giả thuyết có dẫn chứng**; chỗ nào đã chạy bằng lệnh trong repo thì ghi rõ là **đã đo**. Hai mức này **không được trộn**.

Tài liệu **không sửa mã nguồn**. Nó là đầu vào cho các nhiệm vụ sửa lỗi, làm app, kiểm định và phản biện.

---

## 1. Hiện tượng người dùng báo (phát biểu lại chính xác)

Người dùng mô tả, diễn giải lại thành các sự kiện quan sát được:

1. Ngồi vào bàn, mở dashboard, bấm **"Bắt đầu học"** → phiên học chuyển sang `running`.
2. Người vẫn ngồi trong khung hình, nhưng **khung xương (skeleton) biến mất** khỏi ảnh camera trên dashboard; ảnh vẫn có người, vẫn có hộp khuôn mặt.
3. Loa camera **lặp lại câu "Bạn ơi, quay lại bàn học nhé" khoảng mỗi 2 giây** và không tự dừng dù người không đi đâu.
4. **Nhận diện khuôn mặt vẫn đúng người** trong suốt thời gian đó (dòng "Danh tính" trên dashboard vẫn `MATCH`).

Ba dấu hiệu này **đi cùng nhau** và tách hẳn khỏi nhận diện khuôn mặt. Đây là điểm khoanh vùng quan trọng: khuôn mặt chạy trên một đường riêng, không đi qua `PoseEstimator`.

Bằng chứng cho việc tách đường: vòng lặp gọi `people.observe(frame, people_now)` **vô điều kiện trong phiên** (`src/posture_monitor/__main__.py:1312`), còn pose chỉ được lấy từ `estimator.detect(frame)` (`src/posture_monitor/__main__.py:1200`). Khi `pose is None`, khối người học vẫn chạy, nên **khuôn mặt vẫn đúng người** trong khi skeleton mất — đúng hiện tượng người dùng báo.

**Mức bằng chứng của mục 1:** hiện tượng do người dùng báo; việc "khuôn mặt và pose là hai đường độc lập" là **đã xác nhận bằng đọc mã** (hai dẫn chứng ngay trên).

---

## 2. Chuỗi nhân quả, kèm dẫn chứng

### 2.0. Mức bằng chứng (đọc trước)

| Mắt xích | Mức bằng chứng |
|---|---|
| `PoseEstimator._select` trả `None` khi track id đang khoá không còn trong khung, và giữ nguyên như vậy tới hết `absent_reset_s` | **Đã chạy** — kịch bản ở §2.7 |
| `pose=None` ⇒ không gọi `draw_pose` ⇒ mất skeleton | **Đã xác nhận bằng đọc mã** (`__main__.py:1201-1224`), chưa chụp ảnh so sánh |
| `pose=None` ⇒ `PresenceTracker` đếm 0 keypoint ⇒ `absent_for_s` tăng | **Đã chạy** — bảng ở §2.7 |
| `held["leave_frame"] ≥ 5` và `cooldown_s = 2` ⇒ quyết định cảnh báo lặp mỗi 2 s | **Đã chạy** — bảng ở §2.7 |
| BotSORT **thực tế** đổi track id trong cảnh của người dùng | **Giả thuyết có dẫn chứng** — chưa đo trên Pi/camera thật trong phiên này |

Dòng cuối là mắt xích duy nhất chưa đo. Nó **không** cần đúng để bản sửa có giá trị: chỉ cần một lần track id đổi là lỗi xảy ra và tự kéo dài 120 giây. Nhưng nó cần đúng để giải thích **vì sao** người dùng gặp lỗi.

### 2.1. Khoá track id bị kẹt

`PoseEstimator` bám **một** track id (`src/posture_monitor/pose.py:110`), ghi mốc lần cuối thấy nó (`pose.py:112`), và đọc hạn nhả khoá từ `timing.absent_reset_s` (`pose.py:96`).

Quy tắc chọn người (`pose.py:324-361`):

```python
339:        if self._locked_id is not None and ids is not None:
340:            matches = [i for i, tid in enumerate(ids) if tid == self._locked_id]
341:            if matches:
342:                self._last_seen_ts = now
343:                return matches[0]
344:            if now - self._last_seen_ts < self._absent_reset_s:
345:                return None
```

Đọc đúng dòng 344–345: khi track id **đang khoá** không còn trong danh sách `ids` của khung này, hàm **trả `None`** và **không** xét tới những người khác đang có trong khung. Nhánh chọn "khung bao lớn nhất" (`pose.py:357-360`) chỉ chạy khi đã qua `absent_reset_s` hoặc khi chưa khoá ai. Với `config.yaml:166` (`absent_reset_s: 120`), một lần đổi track id khoá **chặn đứng việc lấy pose trong 120 giây**, dù khung nào cũng có người.

Đây là hành vi **có chủ đích** theo spec: `docs/SPEC_V2.md:349` yêu cầu "chỉ đổi người khi track hiện tại mất quá `absent_reset_s`", `docs/SPEC_V3.md:368` yêu cầu "không dùng hộp bao lớn nhất". Bản thân quy tắc đúng cho mục tiêu "người thứ hai đi ngang qua không cướp người đang học"; lỗi nằm ở chỗ quy tắc đó **không phân biệt** "mất track id" với "mất người".

### 2.2. `pose=None` ⇒ mất skeleton

```python
1200:            pose = estimator.detect(frame) if session_active else None
1201:            if pose is None:
...
1209:                drawn = frame
1210:            else:
...
1218:                drawn = draw_pose(
```

`draw_pose` chỉ được gọi ở nhánh `else` (`__main__.py:1218-1224`). Khi `pose is None`, `drawn` **chính là khung gốc** (`__main__.py:1209`), không có đường nào khác vẽ xương. `draw_pose` cũng tự bỏ qua khi `xy is None` (`src/posture_monitor/overlay.py:113-115`), nên kể cả có gọi thì cũng không có gì để vẽ.

Khung này là khung được đẩy lên dashboard: `cv2.imencode(".jpg", drawn)` rồi `state.set_frame(...)` (`__main__.py:1606-1609`). Vì vậy dashboard và `/stream` nhận đúng khung **không xương** — không phải lỗi hiển thị của trình duyệt.

### 2.3. `pose=None` ⇒ presence đếm 0 keypoint

```python
1345:                    if presence_tracker is not None:
1346:                        presence_result = presence_tracker.update(pose)
1347:                        held["leave_frame"] = presence_result.absent_for_s
```

`PresenceTracker.update` đếm keypoint thân trên từ chính `pose` đó (`src/posture_monitor/presence.py:210`). Hàm đếm trả `0` khi `pose is None`:

```python
115:    if pose is None:
116:        return 0
```

`0 < DEFAULT_MIN_UPPER_KEYPOINTS = 2` (`presence.py:68`), nên `visible = False` (`presence.py:211`), `_absent_since` được đặt ở lần đầu (`presence.py:219-220`) và `absent_for_s` **tăng tuyến tính theo thời gian thật** (`presence.py:221`). `present` chỉ còn đúng khi `absent_for_s < absent_hold_s` (`presence.py:222`), với `absent_hold_s` lấy từ `presence.absent_grace_s = 3.0` (`config.yaml:202`, đọc tại `__main__.py:984-989`).

Hệ quả: sau **3,0 giây** không có pose, `held["leave_frame"]` = `absent_for_s` ≥ 3,0 và presence chuyển `vang_mat` (`presence.py:57-58`).

### 2.4. Đồng thời, dashboard báo "Không thấy người"

`pose=None` ⇒ `extract(None, None, ...)` cho `person=False` (`src/posture_monitor/features.py:189-190`) ⇒ `classify` trả đúng nhãn `ABSENT` (`src/posture_monitor/classifier.py:143-147`) ⇒ máy trạng thái vào `STATE_ABSENT` (`src/posture_monitor/state.py:261-278`) ⇒ web đổi `state_text` thành **"Không thấy người"** (`src/posture_monitor/web/app.py:81`).

Bộ làm mượt giữ `person=True` thêm `timing.smooth_window_s = 1.0` giây (`state.py:153`, `config.yaml:160`), nên **đo được** độ trễ chuyển trạng thái: từ lúc pose bắt đầu `None`, `ABSENT` xuất hiện sau **1,2 giây** (§2.7, bảng C).

### 2.5. `held` vượt ngưỡng ⇒ cảnh báo lặp mỗi 2 giây

```python
434:        held_s = held.get(kind)
435:        if held_s is None or held_s < kind_settings.hold_s:
436:            continue
437:        last = last_alerts.get(kind)
438:        if last is not None:
439:            elapsed = _seconds_between(now, last)
440:            if elapsed < kind_settings.cooldown_s:
441:                continue
```

Với `config.yaml:329-330` (`cooldown_s: 2`, `hold_s: 5`):

- `held["leave_frame"] < 5` ⇒ **không** cảnh báo (`schedule.py:435-436`).
- `held ≥ 5` và chưa từng báo ⇒ cảnh báo ngay (`schedule.py:437-451`).
- Đã báo cách đây < 2 giây ⇒ im (`schedule.py:438-441`).
- Đã báo cách đây ≥ 2 giây ⇒ **báo lại** (`schedule.py:442-451`).

Vì `held["leave_frame"]` tiếp tục tăng (pose vẫn `None` suốt 120 giây), điều kiện "lỗi còn tiếp diễn" luôn đúng ⇒ loa nhắc lại **đúng mỗi 2 giây**. Đây chính là "lặp mỗi ~2 s" mà người dùng nghe thấy. Thiết kế này là **có chủ đích** (`config.yaml:321-325`), không phải lỗi: nó chỉ sai vì đầu vào `held` sai.

Cooldown được ghi ở `__main__.py:1530-1531`, không bao giờ bị bỏ qua sau một quyết định.

### 2.6. `last_person_count` cũng bị đặt 0

```python
283:        count = len(boxes)
284:        self.last_person_count = count
...
291:        index = self._select(xyxy, ids)
292:        if index is None:  # pragma: no cover - nhánh phòng vệ
293:            self.last_person_count = 0
294:            return None
```

Dòng 283–284 ghi đúng số người thật, rồi dòng 292–294 **ghi đè thành 0** khi chỉ mất track id. Nghĩa là biến mà `docs/SPEC_V3.md:343` dùng "làm đầu vào presence" lại báo "0 người" trong khi model vừa thấy người. Chú thích `# pragma: no cover - nhánh phòng vệ` ở dòng 292 cho thấy nhánh này **chưa từng được coi là đường chạy thật** — nhưng nó chính là đường chạy thật của ca lỗi này.

### 2.7. Kết quả chạy thật (tái lập được)

**(A) `_select` kẹt khoá — khoá track 7, khung có người mang id 9 và 10:**

Gọi trực tiếp `_select` (khoá `_locked_id = 7`, khung có `ids=[9, 10]`):

| Điều kiện | `_select(...)` trả | `_locked_id` sau đó |
|---|---|---|
| Vừa thấy track 7 ở khung trước | **`None`** | `7` (giữ nguyên) |
| Cùng khung, `_last_seen_ts` lùi 121 giây | `1` = index của hộp lớn nhất | `10` |

Gọi qua `detect()` với model giả (khung có 1 người mang id 9, `_locked_id = 7`):

| Điều kiện | `detect()` trả | `last_person_count` |
|---|---|---|
| Track 7 vắng, khung còn 1 người | **`None`** | **`0`** — bị ghi đè ở `pose.py:293`, dù dòng 283–284 vừa ghi `1` |

Đọc đúng cách: **`_select` trả `None` dù khung có 1–2 người**, và lớp `detect()` biến "còn người nhưng mất track id" thành **`pose=None`, `last_person_count=0`** — tức cùng một tín hiệu với "khung trống". Đó là chỗ hai tình huống khác nhau bị gộp làm một.

**(B) Presence + quyết định cảnh báo, cùng một đồng hồ giả, `pose=None` liên tục:**

| t (s) | `presence.state` | `absent_for_s` | `held["leave_frame"]` | Quyết định |
|---|---|---|---|---|
| 0,0 | `co_mat` | 0,0 | 0,0 | – |
| 1,0 | `co_mat` | 1,0 | 1,0 | – |
| 2,9 | `co_mat` | 2,9 | 2,9 | – |
| 3,0 | `vang_mat` | 3,0 | 3,0 | – |
| 4,9 | `vang_mat` | 4,9 | 4,9 | – |
| **5,0** | `vang_mat` | 5,0 | 5,0 | **`leave_frame`** |
| 6,9 | `vang_mat` | 6,9 | 6,9 | – |
| **7,0** | `vang_mat` | 7,0 | 7,0 | **`leave_frame`** |
| 8,9 | `vang_mat` | 8,9 | 8,9 | – |
| **9,0** | `vang_mat` | 9,0 | 9,0 | **`leave_frame`** |

Chu kỳ lặp **đúng 2 giây**, khớp `cooldown_s: 2`. Câu đọc ra loa ứng với loại `leave_frame` là `"Bạn ơi, quay lại bàn học nhé"` (`src/posture_monitor/speaker_alert.py:96,113-114`).

**(C) Độ trễ dashboard báo "Không thấy người" (5 FPS, cửa sổ làm mượt 1,0 s):** `state` giữ `GOOD` tới **3,0 s** sau khi pose bắt đầu `None`, chuyển `ABSENT` ở **3,2 s**. Tức trễ quan sát ≈ `smooth_window_s` + một khung.

**(D) Người quay lại:** với `pose` có 7 keypoint thân trên, lần `update` **đầu tiên** trả `absent_for_s = 0.0`, `state = co_mat`, bất kể trước đó đã vắng 119 giây hay 3 giây. `PresenceTracker` **không** có ngưỡng trễ khi quay lại — nó chỉ có ngưỡng trễ khi báo vắng (`presence.py:214-217`). Đây là cơ sở để đòi "về `co_mat` trong ≤ 1 s" ở §3(c): phần còn thiếu nằm ở `PoseEstimator`, không ở `PresenceTracker`.

Lệnh tái lập bảng (B) — chạy được, đã chạy, cho đúng 10 dòng của bảng trên:

```powershell
$env:PYTHONPATH='src'; $env:PYTHONIOENCODING='utf-8'
@'
from datetime import datetime, timedelta
from posture_monitor import schedule as s
from posture_monitor.presence import PresenceTracker
from posture_monitor.config import load_config

cfg = load_config('config.yaml')
t = [0.0]
tr = PresenceTracker(absent_hold_s=cfg.presence.absent_grace_s, clock=lambda: t[0])
last = {}
base = datetime(2026, 11, 12, 19, 30)
for step in [0, 1, 2.9, 3, 4.9, 5, 6.9, 7, 8.9, 9]:
    t[0] = float(step)
    r = tr.update(None)                      # pose=None vi _select tra None
    d = s.should_alert(cfg.schedule, base + timedelta(seconds=float(step)),
                       held={'leave_frame': r.absent_for_s}, last_alert_at=last)
    print(step, r.state, round(r.absent_for_s, 1), d.kind if d else '-')
    if d:
        last[d.kind] = base + timedelta(seconds=float(step))
'@ | python -
```

Bảng (A) dựng bằng `object.__new__(PoseEstimator)` + `_infer` giả (khoá `_locked_id = 7`, `_last_seen_ts = time.monotonic()`, khung có `ids=[9, 10]`, sau đó lùi `_last_seen_ts` 121 giây). Bảng (C) chạy qua `Smoother`/`StateMachine` thật với `pose=None` từ giây 2,0. Bảng (D) chạy `PresenceTracker` thật. Không bảng nào chạm model thật hay camera.

### 2.8. Vì sao "vào phiên học" mới thấy

Ngoài phiên, `pose` **được gán `None` có chủ đích** (`__main__.py:1200`, nhánh `session_active`), nên không có skeleton — nhưng cũng không có cảnh báo: khối cảnh báo chỉ chạy khi `session_active` (`__main__.py:1332-1341`). Vì vậy triệu chứng **chỉ xuất hiện sau khi bấm "Bắt đầu học"**, đúng như người dùng báo. Điều này loại bỏ giả thuyết "camera mất kết nối": mất camera thì `source.read()` trả `None` và vòng lặp **dừng hẳn** (`__main__.py:1100-1104`), khi đó dashboard đứng ở `stale: true` chứ không lặp cảnh báo.

---

## 3. Yêu cầu chức năng cho bản sửa

Bốn yêu cầu dưới đây phát biểu dưới dạng **đo được**. Mỗi yêu cầu có: phát biểu, cách đo, ngưỡng đạt.

### (a) Người còn trong khung ⇒ **phải** có `PoseResult`

- **Phát biểu:** nếu model trả `len(boxes) ≥ 1` **và hộp của người đang theo dõi đủ lớn, không dẹt, và còn liên tục về vị trí** thì `detect()` trả `PoseResult`, **không** được `None` chỉ vì track id đang khoá đã đổi. Track id mới phải được bám ngay trong khung đó.
- **Cách đo:** chạy N = 300 khung liên tiếp trên video có **một** người, với model thật; đếm `sum(1 for f in frames if est.detect(f) is None)` trong khi `est.last_person_count >= 1` **và** hộp lớn nhất vượt `REACQUIRE_MIN_FRAME_RATIO` trên **cả hai** trục, không vượt `REACQUIRE_MAX_ASPECT_RATIO`, và (khi đã có hộp trước) qua cổng liên tục không gian.
- **Ngưỡng đạt:** **0** khung trả `None` khi `last_person_count ≥ 1` **và** hộp lớn nhất đủ lớn (vượt `REACQUIRE_MIN_FRAME_RATIO` trên cả hai trục). Khung chỉ còn hộp rác là **ca loại trừ**, phải trả `None` và đo riêng bằng đếm **"khoá bị cướp" = 0**. Với bản hiện tại, ngưỡng này bị vi phạm ngay khi track id đổi (§2.7 bảng A).
- **Ràng buộc kèm theo (không được phá):** người thứ hai to hơn đi ngang qua **không** được cướp khoá — `tests/test_pose.py::test_detect_keeps_locked_track_when_other_person_bigger` phải tiếp tục xanh.
- **Ràng buộc chống bám rác:** việc bám lại chỉ được xảy ra khi hộp ứng viên đủ lớn **và không dẹt**; hộp rác nhỏ hoặc hộp dẹt (mép bàn 400×4, bóng đổ 500×6, thanh ghế 350×10 trên khung 640×480) không được thay khoá của người đang học. Ngưỡng phải là **hằng số có tên + docstring nêu rõ là ngưỡng mặc định CHƯA đo trên dữ liệu thật**.
- **Ràng buộc chống cướp khoá bởi người khác (bổ sung sau vòng phản biện):** khi track id đang khoá mất mà khung còn **người khác ở chỗ khác hẳn** (IoU = 0, tâm xa), `detect()` phải trả `None` và `_locked_id` **giữ nguyên**. Thiếu ràng buộc này thì người học rời bàn mà còn ai khác trong khung sẽ khiến `presence` **không bao giờ** báo vắng — tức bản sửa phá đúng tính năng nó định cứu, từ chiều ngược lại. Cổng: IoU ≥ `REACQUIRE_MIN_IOU` **hoặc** tâm dịch ≤ `REACQUIRE_MAX_CENTER_SHIFT_RATIO` × cạnh dài hộp trước.
- **Ghi chú cho người đọc test:** trong `tests/test_pose_track_reacquire.py`, các bài `test_tiny_trash_box_does_not_steal_lock`, `test_trash_boxes_detected_by_flatness`, `test_other_person_far_away_does_not_steal_lock` là **ca loại trừ** của tiêu chí (a), **không** phải bằng chứng mã sai. Chúng khẳng định đúng phần "đo riêng bằng đếm khoá bị cướp = 0".

### (b) Rời khung thật ⇒ vẫn báo vắng đúng `presence.absent_grace_s`

- **Phát biểu:** khi `len(boxes) == 0`, `detect()` trả `None`, `last_person_count == 0`, và presence chuyển `vang_mat` đúng sau `presence.absent_grace_s` (3,0 s), không sớm hơn, không muộn hơn quá một khung.
- **Cách đo:** băng video người đứng dậy và ra khỏi khung tại mốc `t_leave`; ghi mốc `t_absent` = lần đầu `presence.state == "vang_mat"`.
- **Ngưỡng đạt:** `t_absent - t_leave ∈ [3,0 ; 3,0 + 1/FPS]` giây (tại 5 FPS: **[3,0 ; 3,2] s**). Với `FPS = 5`, sai số cho phép là một khung.
- **Ràng buộc:** cảnh báo loa chỉ được xuất hiện khi `held["leave_frame"] ≥ 5,0`, và lần đầu rơi vào **[5,0 ; 5,2] s** — không sớm hơn.

### (c) Quay lại ⇒ `co_mat` trong ≤ 1 s, **không** phụ thuộc `timing.absent_reset_s`

- **Phát biểu:** ngay khung đầu tiên có người trở lại, `presence.state == "co_mat"` và `absent_for_s == 0.0` — **kể cả** khi lúc rời đi track id đã đổi và `_locked_id` đang trỏ vào id không còn tồn tại.
- **Cách đo:** hai lần chạy cùng một kịch bản, chỉ khác `timing.absent_reset_s` ∈ {0 ; 120}; ghi `t_back` = mốc người vào lại khung, `t_present` = lần đầu `presence.state == "co_mat"`.
- **Ngưỡng đạt:** `t_present - t_back ≤ 1,0 s` ở **cả hai** cấu hình, và hiệu `|t_present(0) - t_present(120)| ≤ 1/FPS`. Nếu chỉ một cấu hình đạt thì yêu cầu **không** đạt — đó chính là lỗi hiện tại.
- **Kiểm chứng ở tầng đơn vị:** `PresenceTracker.update(pose).absent_for_s == 0.0` ngay lần gọi đầu sau một chuỗi `update(None)` dài 119 giây — **đã đạt** ở bản hiện tại (§2.7 bảng D). Vậy khi test này đỏ sau khi sửa thì lỗi mới nằm ở `presence.py`, còn khi tích hợp vẫn đỏ thì lỗi nằm ở `pose.py`.

### (d) `last_person_count` phản ánh số người thật

- **Phát biểu:** sau **mỗi** lần `detect()`, `last_person_count == len(boxes)` của chính khung đó; chỉ bằng `0` khi `len(boxes) == 0` **hoặc khi không đọc được `len(boxes)`** (backend lạ không có `__len__` dùng được). Khi có hộp nhưng thiếu keypoint, `detect()` vẫn trả `None` (hợp đồng `PoseResult` đòi `xy` (17,2) và `conf` (17)) nhưng `last_person_count` **vẫn đúng số người đã thấy**, không bị đặt 0.
- **Cách đo:** với mỗi khung, so `est.last_person_count` với `len(result.boxes)` của model giả; đếm số khung lệch. Chạy thêm một ca `boxes` có 2 người + `keypoints = None`.
- **Ngưỡng đạt:** **0** khung lệch trên 300 khung, gồm cả các khung có track id đổi giữa chừng **và** khung thiếu keypoint.
- **Hiện trạng:** vi phạm — `pose.py:292-294` đặt `0` sau khi đã ghi đúng ở `pose.py:283-284`.
- **Khoá hành vi:** `tests/test_pose.py::test_person_count_correct_when_keypoints_missing`.

### (e) Ràng buộc hồi quy (bắt buộc giữ)

| Hành vi | Nguồn khoá hành vi |
|---|---|
| Khoá track còn trong khung thì người khác to hơn không cướp được | `tests/test_pose.py::test_detect_keeps_locked_track_when_other_person_bigger` |
| Vắng quá `absent_reset_s` thì nhả khoá và chọn người mới (khung 640×480, hộp 3×3 — đi đúng nhánh nhả khoá) | `tests/test_pose.py::test_detect_releases_track_after_absent_reset` |
| Chưa hết `absent_reset_s` thì `None` và khoá giữ nguyên | `tests/test_pose.py::test_detect_keeps_lock_before_absent_reset_elapsed` |
| `tracking` tắt / backend không trả `id` ⇒ dùng khung bao lớn nhất | `tests/test_pose_track_reacquire.py::test_without_ids_still_uses_largest_box` |
| Người khác ở chỗ khác không cướp khoá (cổng liên tục không gian) | `tests/test_pose_track_reacquire.py::test_other_person_far_away_does_not_steal_lock` |
| Hộp dẹt (mép bàn/bóng đổ/thanh ghế) không được bám lại | `tests/test_pose_track_reacquire.py::test_trash_boxes_detected_by_flatness` |
| Hợp đồng `PoseResult(xy (17,2), conf (17), bbox (4,))` | `tests/test_pose.py::test_detect_returns_contract_shapes` |
| Không crash khi model/backend lỗi | `tests/test_pose.py::test_tracking_failure_falls_back_to_predict` |
| `PresenceTracker.reset()` khi bắt đầu/kết thúc phiên | `tests/test_presence.py`, `tests/test_wire_alert_gate.py` |

Điều kiện đạt: **toàn bộ** `tests/test_pose.py` và `tests/test_presence.py` xanh, không test nào bị xoá hay bị `skip` thêm, trừ khi lý do được nêu rõ trong output của người làm.

---

## 4. Hợp đồng API app điện thoại được phép gọi

Nguồn sự thật duy nhất: `src/posture_monitor/web/app.py`. Bảng dưới đây liệt kê **đúng route có thật**, đúng method, kèm mã lỗi **đã đo** bằng Flask `test_client`.

### 4.1. Chỉnh lại một chi tiết trong đề bài

Đề bài ghi "GET/POST `/api/session`". **Không có** `POST /api/session`: đo được **405** (`text/html`, không phải JSON). Route đúng là `GET /api/session` và hai route hành động riêng `POST /api/session/start`, `POST /api/session/stop`. App **không được** gọi `POST /api/session`.

Hệ quả cho client: mọi xử lý lỗi phải chịu được **body HTML** ở mã 405 (và ở 404 ngoài tiền tố `/api/`), không được gọi `response.json()` vô điều kiện.

### 4.2. Route được phép gọi

| Route | Method | 200 trả gì (trường chính) | Mã lỗi đã đo | Dẫn chứng |
|---|---|---|---|---|
| `/api/status` | GET | `state`, `state_text`, `labels`, `label_texts`, `score`, `sitting_s`, `distance_cm`, `alert`, `message`, `muted`, `data_age_s`, `stale`, `stream_enabled`, `min_distance_cm` | không có nhánh lỗi — luôn **200** | `app.py:423-429` |
| `/api/history?range=today` \| `7d` | GET | `range`, `unit` (`hour`/`day`), `labels`, `good_pct`, `avg_score`, `absent_s`, `distance_cm_avg`, `has_data`, `message` | **400** `range` khác `today`/`7d`; **503** đọc DB lỗi; chưa bật lưu trữ vẫn **200** với `has_data: false` | `app.py:431-455` |
| `/api/session` | GET | `state` (`idle`/`running`/`finished`), `minutes`, `remaining_s`, `elapsed_s`, `ends_in_text`, `finished_message`, `finish_text`, `default_minutes`, `min_minutes`, `max_minutes` | **503** khi phiên chưa bật | `app.py:483-497` |
| `/api/session/start` | POST | như trên + `ok: true`, `message`; thân tuỳ chọn `{"minutes": 60}` | **503** khi phiên chưa bật; **400** khi `minutes` sai (ngoài 1–720, không nguyên, `true/false`) | `app.py:499-522` |
| `/api/session/stop` | POST | như trên + `ok: true`; gọi lúc đang nghỉ vẫn **200** | **503** khi phiên chưa bật | `app.py:524-533` |
| `/api/mute` | POST | `ok`, `muted`, `message`; thân tuỳ chọn `{"muted": true\|false}`, không thân thì đảo trạng thái | không có nhánh lỗi — luôn **200** | `app.py:535-555` |
| `/api/signals` | GET | `presence`/`phone`/`identity`, mỗi mục có `state`, `age_s`, `age_limit_s`, `fresh`; `identity` thêm `name`, `reason`. **Không bao giờ có** `embedding`/`vector` | **503** khi dịch vụ người học chưa bật hoặc gặp sự cố; **400** khi lỗi nghiệp vụ | `app.py:897-909`, `1038-1048` |
| `/api/people` | GET | `{"people": [{"id","name","created_ts"}], "selected": str\|null}` | **503** như trên; **400** lỗi nghiệp vụ | `app.py:795-809` |
| `/api/select` | POST | `ok`, `selected`, `message`; thân `{"person_id": "..."}` hoặc `null` | **400** thiếu `person_id` hoặc sai kiểu; **404** id không tồn tại; **503** dịch vụ chưa bật | `app.py:870-895` |
| `/api/schedule` | GET | `{"ok": true, "schedule": {enabled, windows[], kinds{}}}` | **503** dịch vụ chưa bật | `app.py:911-919` |
| `/api/ptz` | POST | `ok`, `direction`, `duration` (giây **thực tế**), `message`; thân `{"direction": "left"\|"right"\|"up"\|"down", "duration": 0.5}` | **400** thân sai / hướng lạ / `duration` không phải số hoặc âm; **501/502/503** theo `PtzError.status`; **500** lỗi không lường trước | `app.py:688-744` |
| `/api/voice` | GET | `ok`, `available`, `voice`, `volume`, `speed`, `voices{}`, `fallbacks{}`; `available: false` + `message` khi chưa nối loa | **200** cả khi loa tắt (kèm `available: false`); **503** khi đọc báo cáo lỗi | `app.py:618-645` |
| `/api/voice` | POST | `ok`, `available`, `message`, + báo cáo mới; thân `{"voice": "nam"\|"nu"\|"espeak"}` | **503** khi chưa nối loa; **400** thiếu `voice` / giọng lạ | `app.py:647-686` |
| `/stream` | GET | `multipart/x-mixed-replace; boundary=frame` (MJPEG) | **403** khi `web.stream_enabled: false` | `app.py:746-765` |
| **`/api/frame`** | GET | **CẦN THÊM** — một khung JPEG duy nhất, `Content-Type: image/jpeg`, `Cache-Control: no-store` | đề xuất: **403** khi `stream_enabled: false`; **503** khi chưa có khung nào | **chưa tồn tại** — đã kiểm tra: `GET /api/frame` → **404** `{"ok":false,"message":"Không có API này."}` |

**Route ngoài phạm vi app** (app **không** được gọi): `POST /api/calibrate` (`app.py:457`), `POST /api/speak` (`app.py:557`), `GET /api/enroll/<id>` (`app.py:845`), `POST /api/enroll/<id>/cancel` (`app.py:855`), `POST/DELETE /api/people*` ghi/xoá (`app.py:811`, `833`), `PUT /api/schedule` (`app.py:921`), `GET /` (HTML).

### 4.3. Vì sao bắt buộc thêm `GET /api/frame`

`/stream` trả `multipart/x-mixed-replace` (`app.py:762-765`). Đây là định dạng để **trình duyệt** tự nối lại nhiều phần ảnh vào một thẻ `<img>`. React Native trên iOS **không** render được MIME này trong `<Image>`: component ảnh của React Native nhận một URL và một lần tải, không đọc luồng multipart vô hạn. Không có route ảnh tĩnh, app hoặc phải cắm WebView (mang theo toàn bộ dashboard HTML), hoặc không có ảnh camera.

Yêu cầu cho route mới:

1. Trả đúng khung JPEG **mới nhất trong RAM** (`DashboardState.latest_frame`, `app.py:221-224`).
2. Tôn trọng `web.stream_enabled` (`app.py:346`) và **dùng lại đúng thông điệp** đang có ở `/stream` (`app.py:756-761`) — không viết câu thứ hai.
3. Chưa có khung ⇒ **503** JSON tiếng Việt, **không** trả 200 rỗng (app phải phân biệt "chưa có ảnh" với "ảnh hỏng").
4. Có `Cache-Control: no-store`: không có nó, iOS có thể dùng lại ảnh cũ và app hiện khung đứng yên.
5. Read-only: không chạm camera, không ghi đĩa. Spec cấm lưu ảnh (`docs/WEB_DASHBOARD.md` §2.3 ghi rõ khung chỉ đi qua bộ nhớ; `README.md:403` "Không lưu, không truyền ảnh").
6. Không đổi hành vi `/stream`.

**Điều kiện `stream_enabled`:** `app.py:346` đọc `config.web.stream_enabled`, mặc định `False` ở `WebConfig` (`src/posture_monitor/config.py:384-387`); `config.yaml:297` đang đặt `true`. Giá trị này được **công bố** trong `/api/status` (`app.py:427`), nên app đọc `stream_enabled` từ `/api/status` để quyết định hiện màn ảnh hay hiện hướng dẫn bật.

### 4.4. Hình dạng lỗi thống nhất

Mọi lỗi do route tự trả đều có dạng `{"ok": false, "message": "<câu tiếng Việt>"}` (`app.py:1051-1055`), kể cả 404 cho tiền tố `/api/` (`app.py:936-940`). App được phép hiện thẳng `message`. Ngoại lệ **bắt buộc xử lý**: 405 và 404 **ngoài** `/api/` là HTML, không có `message`.

---

## 5. Ma trận màn hình app (Expo Go, iOS)

Nhãn tiếng Việt phải **khớp dashboard web**, không tự đặt câu khác. Nguồn nhãn: `app.py:77-97` và `src/posture_monitor/web/static/app.js:102-124`.

### 5.1. Bảng màn hình

| # | Màn hình | Route dùng | Nội dung bắt buộc | Tiêu chí đạt (quan sát được) |
|---|---|---|---|---|
| 1 | **Trạng thái** | `GET /api/status` | `state_text`; `score` (1 chữ số thập phân); `label_texts`; dấu hiệu dữ liệu cũ theo `data_age_s` / `stale` | Mở màn: trong **≤ 2,5 s** có dữ liệu thật (không phải placeholder). Khi server trả `stale: true` hoặc `data_age_s > 10`: hiện **"Không nhận được dữ liệu mới"** + tuổi dữ liệu, **không** hiện `state_text` như kết luận mới. Khi `state == "PAUSED"`: hiện **"Chưa bắt đầu phiên học"** (`app.py:84`), **không** hiện "Không thấy người". `label_texts` rỗng ⇒ không vẽ chip rỗng. |
| 2 | **Ảnh camera** | `GET /api/frame` (mới) + `stream_enabled` từ `/api/status` | Ảnh JPEG mới nhất, tự tải lại; giờ cập nhật | Trong **≤ 1 s** sau khi mở, ảnh hiện và có ít nhất **1** lần tải lại thành công trong 5 s. `stream_enabled: false` ⇒ hiện hướng dẫn bật `web.stream_enabled: true`, **không** hiện ô ảnh trống. Nhận **503** ⇒ hiện "Chưa có khung hình từ camera", tự thử lại — **không** crash, không màn hình trắng. Khi người ngồi trong khung và đang trong phiên: ảnh **có** xương (đếm pixel màu `EDGE_COLOR` = BGR `(0,255,0)` — `src/posture_monitor/overlay.py:73` — trên ảnh tải về phải **> 0**). |
| 3 | **Phiên học** | `GET /api/session`, `POST /api/session/start`, `POST /api/session/stop` | `state`; ô số phút (1–720); nút **Bắt đầu học** / **Dừng học**; `ends_in_text` / `remaining_s`; `finish_text` | Sau khi bấm Bắt đầu: **≤ 2 s** trạng thái hiện `running` và có số phút còn lại giảm dần (đọc lại mỗi 2 s, chênh lệch giữa hai lần đọc ≥ 1 s). Bấm Dừng ⇒ **≤ 2 s** về `idle`. Server trả **503** ⇒ hiện đúng câu tiếng Việt của server, nút bị vô hiệu, **không** crash. Nhập 0 hoặc 721 phút ⇒ server **400**, app hiện `message` của server, **không** tự đoán. `finish_text` khác `null` ⇒ hiện câu **"Đã hết giờ học. Nghỉ ngơi nhé."** (`src/posture_monitor/study_session.py:80`) — không tự bịa câu khác (`study_session.py:359-366`). |
| 4 | **Tín hiệu** | `GET /api/signals` | 3 dòng: **Có mặt** / **Điện thoại** / **Danh tính**, mỗi dòng kèm tuổi tín hiệu (`age_s`) và trạng thái mới/cũ (`fresh`) | Nhãn phải là: `co_mat` → "Đang trong khung hình"; `vang_mat` → "Không thấy ai"; `dung` → "Đang dùng"; `khong_dung` → "Không dùng"; `MATCH` → "Đúng người"; `MISMATCH` → "Khác người"; `UNKNOWN` → "Chưa nhận ra" (`app.js:102-120`). `fresh: false` ⇒ dòng đó **phải** hiện **"Chưa có dữ liệu mới"** + "–" cho tuổi (`app.js:124,147-148`), **tuyệt đối không** lặp lại `state` cũ. Ngưỡng tuổi: presence/phone **3,0 s**, identity **10,0 s** (`src/posture_monitor/people_service.py:157-159`) — app hiển thị theo `age_limit_s` server gửi, không hardcode. Nhận **503** ⇒ hiện câu của server, không crash. |
| 5 | **Giọng đọc** | `GET /api/voice`, `POST /api/voice` | Giọng đang dùng; danh sách giọng kèm nhãn; cảnh báo giọng nào còn phải mượn (`fallbacks`) | `available: false` ⇒ hiện `message` của server (`app.py:627-637`), **không** hiện nút bấm được. Đổi giọng thành công ⇒ **≤ 2 s** nhãn giọng đang dùng đổi theo phản hồi server, và đọc lại `GET /api/voice` cho cùng giá trị. Giọng lạ ⇒ server **400**, app hiện `message` (danh sách giọng hợp lệ nằm trong câu lỗi). Nhận **503** ⇒ hiện câu của server. |
| 6 | **Điều khiển (PTZ)** | `POST /api/ptz` | 4 nút: lên / xuống / trái / phải; thông điệp phản hồi | Mỗi lần bấm gửi đúng `{"direction": "left"|"right"|"up"|"down", "duration": 0.5}`. Thành công ⇒ hiện `message` server ("Đã xoay camera sang trái.") trong **≤ 2 s**. Lỗi ⇒ hiện **đúng** `message` tiếng Việt của server (ví dụ "Camera không hỗ trợ PTZ."), **không** hiện "Lỗi" chung. Bấm liên tiếp **không** tạo quá 1 request đồng thời. Xử lý được **400/501/502/503** mà không crash. |
| 7 | **Kết nối** (bắt buộc, ngoài 6 màn trên) | `GET /api/status` | Ô nhập địa chỉ máy chủ + nút **Kiểm tra kết nối** | Địa chỉ **lưu lại** qua lần khởi động sau; **không** có IP/cổng nào hardcode trong mã nguồn. Nhập sai địa chỉ ⇒ hiện câu tiếng Việt nêu nguyên nhân (sai địa chỉ / quá hạn chờ / không phải JSON), có nút thử lại. Kiểm tra kết nối thành công khi nhận **200** từ `/api/status`. |

### 5.2. Quy tắc chung bắt buộc cho app

1. **Một lớp client duy nhất** cho mọi lời gọi mạng; mọi lời gọi có timeout (≤ 5 s cho JSON, ≤ 10 s cho ảnh) bằng `AbortController`.
2. **Không nuốt lỗi:** mỗi lỗi phải hiện được lý do + nút thử lại.
3. **Không đọc JSON vô điều kiện:** 405 và 404 ngoài `/api/` là HTML (§4.1). Đọc `message` phải phòng `message` vắng mặt.
4. **Không setState sau unmount**; rời màn thì huỷ request đang chờ và dừng vòng tự làm mới.
5. **Không chồng request:** mỗi màn tự làm mới **tuần tự**, bỏ qua nhịp nếu request trước chưa xong. Nhịp tham chiếu: dashboard web hỏi `/api/status` và `/api/signals` mỗi **1 000 ms** (`src/posture_monitor/web/static/app.js:21,1708-1709`) và `/api/session` mỗi 1 000 ms (`app.js:608,794`). App được phép chậm hơn (**2 000 ms**) để tiết kiệm pin, nhưng **không** được nhanh hơn 1 000 ms.
6. **Không suy diễn trạng thái từ rỗng:** thiếu trường ⇒ hiện "Chưa rõ", không coi là `ABSENT`/`MATCH`.

---

## 6. Điều kiện môi trường (ràng buộc cứng)

### 6.1. Máy dev Windows **không** build native iOS

- Không có Xcode, không có `xcodebuild`, không có iOS Simulator trên Windows. Vì vậy **không** chạy được `npx expo run:ios`; **không** tạo được dev build `.ipa`.
- Kết luận bắt buộc: app phải chạy **trong Expo Go** (JS + thư viện đã có sẵn trong Expo Go). Mọi thư viện cần native module **không** nằm trong Expo Go đều **bị loại**.
- Không được tuyên bố "đã kiểm thử trên iPhone" nếu chưa thực sự quét QR trên máy thật. Trong phiên làm việc này **chưa** có iPhone và **chưa** cài `node_modules`, nên phần app chỉ có thể kiểm bằng đọc mã + test chạy bằng Node.

### 6.2. Expo Go trên iOS: **một bản Expo Go = một SDK**

- Mỗi bản Expo Go nhúng **đúng một** phiên bản Expo SDK. SDK của project do phiên bản gói `expo` trong `package.json` quyết định. Lệch nhau ⇒ lỗi **"Project is incompatible with this version of Expo Go"** ([Expo — Expo Go version mismatch](https://docs.expo.dev/troubleshooting/expo-go-version-mismatch.md)).
- Trên **App Store**, Expo Go dừng ở **SDK 54**; SDK 55 trở lên **không** có trên App Store. Bản Google Play cũng có thể chậm hơn lần phát hành SDK mới (cùng nguồn).
- Với **iPhone thật**, không cài được bản Expo Go cũ: "you cannot install an older version of Expo Go on a physical iOS device" (cùng nguồn). Muốn SDK mới hơn bản có trên máy, phải tự build Expo Go qua `npx eas-cli@latest go` và phân phối bằng TestFlight, cần **Apple Developer Program** ([Expo — Set up your environment](https://docs.expo.dev/get-started/set-up-your-environment.md)).
- Trên **iPhone thật**, Expo Go chỉ mở project khi Expo CLI và Expo Go **đăng nhập cùng một tài khoản Expo** (`npx expo login` + đăng nhập trong app) ([Expo — Start developing](https://docs.expo.dev/get-started/start-developing.md)).
- **Hệ quả cho yêu cầu:** phải chốt **một** phiên bản SDK và ghi nó ở **một** nơi (`package.json` → `expo`), không đặt `sdkVersion` trong `app.json` trừ khi nó khớp (cùng nguồn). Kiểm tra bằng `npx expo-doctor@latest` và `npx expo install --fix`.
- **Điểm chưa chắc chắn, phải ghi đúng mức độ:** tài liệu nói App Store dừng ở SDK 54, nhưng bản Expo Go đang cài trên máy người dùng có thể mới hơn hoặc cũ hơn. Vì vậy **bước 0** khi chạy thật là đọc số SDK mà Expo Go hiện tại hỗ trợ, rồi đặt `expo` đúng số đó. Không được giả định.

### 6.3. Điện thoại và máy chạy dashboard phải cùng LAN

- Dashboard chỉ phục vụ trong LAN: `web.host: 0.0.0.0` (`config.yaml:291`), cổng `8000` (`config.yaml:292`); `run_server` ghi log đúng địa chỉ và ghi rõ "chỉ trong LAN" (`src/posture_monitor/web/app.py:1085-1100`). `README.md:413` cấm NAT/forward ra Internet; `app.py:21-22` nhắc lại.
- Điều kiện đạt: từ iPhone, `GET http://<ip-lan>:8000/api/status` trả **200** JSON. Nếu trình duyệt Safari mở được mà app không gọi được, lỗi nằm ở app (địa chỉ/ATS), không phải mạng.
- Nếu router chặn thiết bị-tới-thiết bị (mạng công cộng, "AP isolation"): dùng `npx expo start --tunnel` cho **Metro**, nhưng **tunnel không** làm Pi trở nên truy cập được — địa chỉ API vẫn phải là IP LAN. Đây là hai đường khác nhau, không được lẫn.

### 6.4. Địa chỉ phải là **IP LAN của máy/Pi** — tuyệt đối không `localhost`

- `localhost` / `127.0.0.1` trên iPhone trỏ vào **chính iPhone**, không phải máy chạy dashboard. Triệu chứng: mọi request báo lỗi mạng ngay lập tức.
- Với `web.host: 0.0.0.0`, log in ra `http://127.0.0.1:8000/` (mã nguồn đổi `0.0.0.0` thành `127.0.0.1` khi in — `app.py:1095-1098`). **Đây là bẫy thật**: địa chỉ trong log **không** phải địa chỉ nhập vào app. Phải lấy IP LAN của máy/Pi (ví dụ `ipconfig` trên Windows, `hostname -I` trên Pi).
- Không hardcode IP trong mã app; địa chỉ nhập trong app và lưu lại (§5 hàng 7).

### 6.5. Rủi ro ATS với `http://` trên iOS

- App Transport Security (ATS) chặn tải `http://` không mã hoá. React Native `fetch` trên iOS đi qua URL loading system, nên **chịu** ATS.
- Khóa được tài liệu hoá cho ca này là **`NSAllowsLocalNetworking`** (cho phép tải tài nguyên trong mạng nội bộ mà không tắt ATS cho toàn app) — [Apple — NSAllowsLocalNetworking](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking), cùng khung [Preventing Insecure Network Connections](https://developer.apple.com/documentation/security/preventing-insecure-network-connections).
- **Ràng buộc quan trọng:** khi chạy trong **Expo Go**, `Info.plist` là của **Expo Go**, không phải của project — `ios.infoPlist` trong `app.json` **không** có tác dụng trong Expo Go (nó chỉ có tác dụng khi prebuild/dev build). Vì vậy:
  - **Không được** hứa "đã xử lý ATS bằng app.json" khi app chạy bằng Expo Go.
  - **Mức độ chắc chắn:** chưa kiểm chứng trên máy thật trong phiên này. Phải ghi rõ là **chưa kiểm chứng**.
  - **Cách xử lý theo thứ tự:** (1) thử `http://<ip-lan>:8000/api/status` từ Expo Go trước; (2) nếu bị chặn, dựng HTTPS cho dashboard trong LAN (reverse proxy có chứng chỉ tin được trên thiết bị) rồi dùng `https://`; (3) nếu buộc phải dùng `http://` và ATS chặn, phải chuyển sang **dev build** để `app.json` → `ios.infoPlist` → `NSAppTransportSecurity` → `NSAllowsLocalNetworking: true` có hiệu lực — nhưng dev build iOS **không làm được trên Windows** (§6.1). Vì vậy phương án (2) là phương án khả thi duy nhất trong ràng buộc hiện tại.
- Ghi chú kèm theo: kể cả khi ATS cho qua, iOS vẫn có thể hỏi quyền "Local Network" cho kết nối trong LAN; cần bấm **Cho phép**. Đây là hành vi của hệ điều hành, không phải lỗi app.

---

## 7. Truy vết yêu cầu → nhiệm vụ

| Yêu cầu | Nơi phải sửa | Cách nghiệm thu |
|---|---|---|
| §3(a)(b)(d)(e) | `src/posture_monitor/pose.py` | `tests/test_pose.py` + test mới cho ca "mất track id nhưng còn người"; bảng A của §2.7 đổi thành `PoseResult` |
| §3(c) và ràng buộc "không phụ thuộc `absent_reset_s`" | `src/posture_monitor/pose.py` (nguồn gây lỗi), `presence.py` chỉ khi test đơn vị đỏ | Chạy kịch bản (c) với `absent_reset_s` ∈ {0 ; 120} |
| §4 `/api/frame` | `src/posture_monitor/web/app.py` | Test Flask: 200 + `image/jpeg` + đúng byte; 403 khi tắt stream; 503 khi chưa có khung |
| §5 ma trận màn hình | `apps/mobile/` | Đối chiếu từng route với §4.2; không có route nào ngoài bảng |
| §6 môi trường | `apps/mobile/README.md` + `docs/` | README phải nêu: cùng LAN, IP LAN (không `localhost`), Expo Go một-SDK, Windows không build iOS, ATS **chưa kiểm chứng** |

---

## 8. Giới hạn của tài liệu này

1. **Chưa chạy trên Pi/camera thật.** Toàn bộ số đo ở §2.7 là chạy trên PC với model giả hoặc đồng hồ giả. Việc BotSORT đổi track id trong cảnh thật của người dùng vẫn là **giả thuyết có dẫn chứng**.
2. **Chưa chạy app trên iPhone.** Chưa có thiết bị, chưa cài `node_modules`. Mọi tiêu chí ở §5/§6 là tiêu chí để người làm và người kiểm định đo, không phải kết quả đã đo.
3. **Chưa kiểm chứng ATS.** Không khẳng định `http://` tới IP LAN bị chặn hay được cho qua từ Expo Go; chỉ nêu rủi ro và đường xử lý theo thứ tự ưu tiên.
4. **Một số test Python dùng fixture `tmp_path` bị `PermissionError` do sandbox của máy** — hạn chế môi trường, không phải lỗi sản phẩm. Test không dùng `tmp_path` chạy bình thường (`tests/test_pose.py`: **11 passed, 1 skipped**).
