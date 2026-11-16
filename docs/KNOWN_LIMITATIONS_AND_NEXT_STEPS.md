# Giới hạn đã biết và việc nên làm tiếp

**Trạng thái tài liệu:** bàn giao cuối phiên làm việc. Mọi mục dưới đây là thứ **còn hở thật**, không phải
danh sách cho có. Số dòng đã được đối chiếu lại với mã nguồn tại thời điểm viết, không chép từ báo cáo cũ.

**Bối cảnh:** hai mục tiêu của phiên là (1) app React Native/Expo chạy bằng Expo Go điều khiển & xem dashboard
Pi, và (2) sửa lỗi "vào phiên học thì mất skeleton và loa lặp *quay lại bàn học* dù người vẫn ngồi trong khung".
Cả hai đã đạt theo nghĩa **chạy đúng hợp đồng đã đo được trong môi trường này**. Tài liệu này nói rõ phần
**chưa** đạt tới đâu.

**Điều quan trọng nhất cần đọc:** mục 2.1 và 2.3. Bản sửa lỗi skeleton được thiết kế đúng và đã kiểm bằng test,
nhưng **chưa từng chạy trên iPhone thật và chưa từng chạy trên Pi + camera thật**. Đó là khoảng trống lớn nhất
của toàn bộ bàn giao này, không phải mấy lỗi nhỏ ở mục 1.

---

## 1. Lỗi ĐÃ BIẾT nhưng CHƯA sửa

Bốn mục dưới đây đều đã được phát hiện trong quá trình phản biện, đã ghi thành finding có mã (M1–M3 của app,
P1 của backend), và **được đánh dấu `resolved` vì không chặn bàn giao** — nghĩa là chúng không làm app sai
hợp đồng API và không làm bản sửa lỗi skeleton hỏng. Chúng vẫn là lỗi thật.

Bảng tổng hợp trước, chi tiết ở dưới:

| Mã | Khu vực | Mức | Hậu quả ngắn |
|---|---|---|---|
| **M1** | `apps/mobile/test/ui/env.mjs` | Trung bình | Lỗi React lúc **bấm nút** không bị test bắt; chốt chặn chống hồi quy đang hở |
| **M2** | `apps/mobile/src/screens/VoiceScreen.tsx` | Thấp | Màn Giọng đọc hiện **hai thông báo mâu thuẫn** cùng lúc |
| **M3** | `apps/mobile/src/api/errors.ts` | Thấp | Lỗi 503/400 của `/api/voice` rơi về câu chung, không nhắc tới loa |
| **P1** | `src/posture_monitor/pose.py` | Thấp | Nhiễu nhỏ nhưng **vuông** vẫn lọt ngưỡng chống bám rác |

---

### M1 — Harness test chỉ bắt `console.error` trong lúc mount

**Mô tả.** `mountScreen()` trong harness kiểm thử giao diện ghi đè `console.error` để gom lỗi React vào mảng
`ui.errors`, nhưng **trả lại hàm gốc ngay khi mount xong** (khối `finally`). Mọi lỗi React phát sinh **sau đó**
— đặc biệt trong lúc `ui.click()` và `ui.wait()` — không được ghi vào `ui.errors` nữa.

**Vị trí.**

- `apps/mobile/test/ui/env.mjs:251` — `const originalError = console.error;`
- `apps/mobile/test/ui/env.mjs:252` — ghi đè `console.error` để gom vào `errors`
- `apps/mobile/test/ui/env.mjs:269-271` — khối `finally` trả lại `console.error` **ngay sau mount**
- `apps/mobile/test/ui/env.mjs:286-298` — `click()` chạy `act()` về sau, **không** nằm trong vùng bắt lỗi
- `apps/mobile/test/ui/env.mjs:299-303` — `wait()` cũng vậy

**Vì sao chưa sửa.** Đây là lỗi của **hạ tầng kiểm thử**, không phải lỗi của app. Sửa nó không làm app chạy
đúng hơn cho người dùng, và ở thời điểm phát hiện thì toàn bộ 10 bài verify đều đang xanh thật — tức chưa có
triệu chứng nào cho thấy app đang hỏng mà test bỏ qua. Sửa harness đúng cách cần đổi vòng đời của
`console.error` (gắn vào `unmount()` thay vì `finally`), điều này ảnh hưởng cả 10 bài và cần chạy lại toàn bộ
để chắc không bài nào đỏ vì lý do khác.

**Hậu quả thực tế với người dùng.** Đây là mục **nguy hiểm nhất trong bốn mục**, vì nó không làm sai hôm nay
mà làm **hỏng việc phát hiện sai về sau**. Cụ thể:

- **9/10 bài** trong `npm run verify` kết thúc bằng `assert.deepEqual(ui.errors, [])` — đếm chính xác:
  `cameraScreen.test.mjs` dòng 89, 112, 133 và `voiceScreen.test.mjs` dòng 78, 92, 112, 138, 180, 209.
  (Báo cáo vòng t18 của tôi ghi "6/10" — đó là **đếm thiếu**; con số đúng là 9/10. Ghi lại đây để người sau
  không tin số cũ.)
- Nghĩa là: nếu một lần sửa sau này làm React ném lỗi **đúng lúc người dùng bấm nút** (ví dụ bấm "Gửi lại"
  trong banner lỗi, bấm "Chọn Giọng nữ", bấm "Thử lại" ở màn Camera), **test vẫn xanh**. Lỗi chỉ lộ ra khi có
  người mở app trên máy thật và bấm.
- Đây đúng là loại lỗi khó nhất: app vẫn "chạy", màn hình vẫn vẽ, nhưng một tương tác cụ thể không có tác dụng
  hoặc làm trắng màn — mà bộ test tự động nói "không sao".

**Cách sửa gợi ý.**

1. Trong `apps/mobile/test/ui/env.mjs`, **bỏ** khối `finally { console.error = originalError }` ở dòng 269-271.
   Giữ `console.error` đã ghi đè cho tới khi gọi `unmount()`.
2. Trong `unmount()` (dòng 304-309), thêm `console.error = originalError` — trả lại đúng lúc kết thúc bài.
3. Bọc `click()` và `wait()` trong `try/catch`, đẩy exception thật vào `errors` để một lỗi ném ra cũng làm đỏ.
4. **Kiểm chứng việc sửa:** thêm tạm một bài gọi `console.error` **sau** khi click và khẳng định
   `ui.errors.length > 0`; chạy `npm run verify` phải thấy bài đó **xanh** (vì đã bắt được). Sau đó thử làm
   hỏng có chủ ý một nút để chắc bài tương ứng **đỏ**. Xoá bài tạm sau khi xong.

**Mức ưu tiên: TRUNG BÌNH** — không cấp bách cho bản chạy hôm nay, nhưng nên sửa **trước** lần sửa app tiếp
theo, vì để nguyên thì mọi lần sửa sau đều được bảo đảm bằng một chốt chặn bị hở.

---

### M2 — Màn Giọng đọc hiện hai thông báo mâu thuẫn cùng lúc

**Mô tả.** Khối "Còn câu phải mượn giọng khác" chỉ phụ thuộc `data.fallbackCount > 0`, **không** phụ thuộc
`data.available`. Khi phiên chạy chưa nối loa cảnh báo mà server vẫn gửi `fallbacks` khác rỗng, màn hình hiện
**đồng thời** hai khối: "Loa cảnh báo chưa bật" và "Còn câu phải mượn giọng khác".

**Vị trí.**

- `apps/mobile/src/screens/VoiceScreen.tsx:182` — `{data && data.fallbackCount > 0 ? (` ← thiếu điều kiện `available`
- `apps/mobile/src/screens/VoiceScreen.tsx:128-138` — khối "Loa cảnh báo chưa bật"
- `apps/mobile/src/screens/VoiceScreen.tsx:112` — `const unavailable = data ? !data.available : error?.status === 503;`
- `apps/mobile/src/screens/VoiceScreen.tsx:193` — khối chọn giọng thì **đã** có đúng điều kiện `data.available`

**Vì sao chưa sửa.** Mức độ thấp và tổ hợp gây lỗi hiếm: server thật trả `voices: {}` và `fallbacks: {}` khi
`available: false` (xem `src/posture_monitor/web/app.py:664-674`), nên ca này chỉ xảy ra khi payload bị lệch
hình dạng (bản server khác, hoặc proxy sửa thân). Bài kiểm hiện có cho `available: false`
(`voiceScreen.test.mjs:116`) dùng `fallbacks: {}` nên **không phủ** tổ hợp này — đó cũng là lý do nó lọt qua
vòng phản biện đầu.

**Hậu quả thực tế với người dùng.** Người dùng thấy hai câu nói ngược nhau trên cùng một màn: trên bảo
"Loa cảnh báo chưa bật" (không có gì đang phát), dưới lại bảo "Còn câu phải mượn giọng khác" (ám chỉ có cái
gì đó đang phát bằng giọng khác). Câu thứ hai vô nghĩa khi không có loa. Người dùng sẽ mất thời gian đi tìm
một cấu hình giọng đọc không tồn tại, thay vì việc thật sự cần làm là nối dây loa.

**Cách sửa gợi ý.** Đổi điều kiện ở dòng 182 thành `{data && data.available && data.fallbackCount > 0 ? (`.
Thêm một bài vào `apps/mobile/test/ui/voiceScreen.test.mjs`: payload
`{ available: false, voice: null, voices: {}, fallbacks: { phone: 'câu' }, message: 'Loa cảnh báo chưa được bật…' }`
⇒ khẳng định văn bản **có** "Loa cảnh báo chưa bật" và **không** có "Còn câu phải mượn giọng khác".

**Mức ưu tiên: THẤP** — hiếm gặp, không mất dữ liệu, không ảnh hưởng tính năng chính.

---

### M3 — `/api/voice` thiếu gợi ý theo ngữ cảnh trong `ROUTE_HINTS`

**Mô tả.** `ROUTE_HINTS` có gợi ý riêng cho `/api/frame`, `/api/session`, `/api/session/start`,
`/api/session/stop`, `/api/signals`, `/api/ptz` — nhưng **không có `/api/voice`**, dù đây là route app mới
thêm trong đợt này. Vì vậy 503 và 400 của route này rơi về câu chung.

**Vị trí.**

- `apps/mobile/src/api/errors.ts:109` — khai báo `ROUTE_HINTS`
- `apps/mobile/src/api/errors.ts:131` — hết object, **không có khoá `/api/voice`**
- `apps/mobile/src/api/errors.ts:141` — `messageForStatus` tra `ROUTE_HINTS[path]?.[status]`

**Đo được.** `messageForStatus(503, null, '/api/voice')` → *"Tính năng này chưa được bật trong lần chạy hiện tại
của máy chủ."*; `messageForStatus(400, null, '/api/voice')` → *"Máy chủ từ chối yêu cầu: dữ liệu gửi lên không
hợp lệ."* Cả hai đều đúng nhưng **không nhắc gì tới loa cảnh báo** — thứ duy nhất người dùng cần biết.

**Vì sao chưa sửa.** Mức độ thấp nhất trong bốn mục: server **luôn** gửi `message` tiếng Việt cho cả 503 và 400
(`src/posture_monitor/web/app.py:684-731`), và `messageForStatus` ưu tiên message của server
(`errors.ts:139-141`). Câu chung chỉ xuất hiện khi server im lặng — proxy chèn lỗi, hoặc dashboard là bản cũ
chưa có route. Hiếm.

**Hậu quả thực tế với người dùng.** Khi gặp ca hiếm đó, người dùng đọc được câu đúng nhưng vô thông tin: "tính
năng này chưa được bật" mà không biết là **loa cảnh báo** chưa nối, nên không biết phải làm gì. Không crash,
không mất dữ liệu.

**Cách sửa gợi ý.** Thêm vào `ROUTE_HINTS` (trước dòng 131):

```ts
'/api/voice': {
  503: 'Loa cảnh báo chưa được nối trong lần chạy này nên chưa đọc/đổi được giọng.',
  400: 'Giọng gửi lên không hợp lệ. Chọn một trong các giọng máy chủ báo có.',
},
```

Thêm test vào `apps/mobile/test/errors.test.mjs` khẳng định `messageForStatus(503, null, '/api/voice')` có nhắc
tới "loa cảnh báo".

**Mức ưu tiên: THẤP** — sửa 4 dòng, làm cùng lúc với M2 là tiện nhất.

---

### P1 — Ngưỡng chống bám rác chỉ xét tỉ lệ khung, nên nhiễu nhỏ nhưng vuông vẫn lọt

**Mô tả.** `_box_is_big_enough()` đòi hộp ứng viên vượt `REACQUIRE_MIN_FRAME_RATIO` trên **cả hai trục** và
không quá dẹt — nhưng **không** xét diện tích tuyệt đối. Hệ quả: một hộp nhiễu **nhỏ nhưng vuông** vẫn qua cổng.

**Vị trí.**

- `src/posture_monitor/pose.py:165` — `def _box_is_big_enough(box, frame_shape)`
- `src/posture_monitor/pose.py:211` — cổng tỉ lệ khung (`aspect > REACQUIRE_MAX_ASPECT_RATIO`)
- `src/posture_monitor/pose.py:214-217` — điều kiện cuối: `width / frame_w >= RATIO and height / frame_h >= RATIO`
- Các hằng số liên quan: `pose.py:69` (`REACQUIRE_MIN_FRAME_RATIO = 0.05`), `pose.py:79`
  (`REACQUIRE_MAX_ASPECT_RATIO = 4.0`), `pose.py:98` (`REACQUIRE_MAX_CENTER_SHIFT_RATIO = 0.5`),
  `pose.py:111` (`REACQUIRE_MIN_IOU = 0.1`)

**Đo được.** Trên khung 640×480, hộp **40×40** có tỉ lệ `40/640 = 0,0625` và `40/480 = 0,083` — **cả hai đều
vượt** ngưỡng 0,05, nên `_box_is_big_enough` trả `True`. Một hộp nhiễu 40×40 (diện tích 1600 px) vì thế **được
phép bám lại**.

**Vì sao chưa sửa.** Cổng thứ hai — `_box_is_continuous()` — vẫn chặn nếu nhiễu nằm **ở chỗ khác** hộp của người
đang học (đo được: người khác đứng cách tâm quá ~180 px bị chặn). Nhiễu chỉ lọt khi nó xuất hiện **đúng bên
trong hộp người học**, và trong ca đó thì bám vào nhiễu cũng gần như bám vào người. Nói cách khác, xác suất gây
hại thật rất thấp, và siết thêm ngưỡng diện tích tuyệt đối **mà chưa đo trên camera thật** có rủi ro riêng:
chặn oan đúng ca cần cứu (người cúi xuống làm hộp co mạnh).

**Hậu quả thực tế với người dùng.** Trong trường hợp xấu nhất: skeleton nhảy sang một vật nhỏ trong khung thay
vì bám người, hoặc `presence` đếm keypoint từ một hộp nhiễu. Người dùng thấy skeleton vẽ sai chỗ trong một
vài khung. Không crash, không mất cảnh báo rời bàn (vì cổng liên tục vẫn giữ khoá khi người đã đi chỗ khác).
Đây là mục **ít rủi ro nhất** trong bốn mục.

**Cách sửa gợi ý.** Thêm điều kiện diện tích tuyệt đối vào cuối `_box_is_big_enough` (sau dòng 217), ví dụ:

```python
if width * height < REACQUIRE_MIN_BOX_AREA_RATIO * frame_w * frame_h:
    return False
```

với `REACQUIRE_MIN_BOX_AREA_RATIO = 0.01` (≈ 3072 px trên khung 640×480 — đủ chặn 40×40 nhưng cho người bị bàn
che nửa dưới 300×200 = 60 000 px qua rất thoải mái). **Phải đo trên camera thật trước khi chốt số** — xem mục
2.4 và công cụ ở mục 3.

**Mức ưu tiên: THẤP** — và nên sửa **sau** khi có số đo thật, không sửa mò.

---

## 2. CHƯA kiểm chứng được trong phiên này

Đây là phần quan trọng hơn mục 1. Mục 1 là bốn lỗi nhỏ đã biết; mục 2 là **những chỗ chưa ai chạy thử**, nên
không biết là đúng hay sai.

### 2.1. Chưa chạy app trên iPhone / Expo Go thật

**Chưa kiểm gì.** Toàn bộ app `apps/mobile` chưa từng được mở trong Expo Go trên một chiếc iPhone thật.

**Đã kiểm được thay thế (và giới hạn của nó).**

- `npx expo export --platform ios` → Metro bundle thành công 610 module, 1.18 MB. Chứng minh **mọi import,
  JSX và kiểu TypeScript biên dịch được** — nhưng **không** chứng minh app chạy đúng.
- `npm test` → 139/139 bài logic thuần.
- `npm run verify` → 10/10 bài dựng **app React Native thật trong jsdom** và bấm nút. Đây là mức gần nhất với
  "chạy thật" mà môi trường này làm được, nhưng jsdom **không phải** iOS: không có thanh trạng thái, không có
  SafeArea thật, không có `Image` của React Native, không có luồng mạng thật của iOS.

**Muốn kiểm thì cần gì.** Một iPhone, cài **Expo Go** từ App Store, cùng mạng Wi-Fi với máy chạy dashboard, và
`npx expo start` trên máy dev. Quét QR bằng Camera iOS (hoặc nhập `exp://<ip>:8081` trong Expo Go). Cần đăng
nhập **cùng một tài khoản Expo** trên CLI và trên app thì iPhone thật mới mở được project.

**Rủi ro nếu bỏ qua.** Đây là rủi ro **cao nhất của cả bàn giao**. Ba thứ chỉ có thể sai trên máy thật:
(1) ATS chặn `http://` (mục 2.2); (2) quyền "Local Network" của iOS bị từ chối, mọi kết nối LAN hỏng ngay;
(3) một thư viện native không có trong Expo Go làm app trắng màn ngay khi mở. Cả ba đều **không** thể hiện
trong jsdom hay trong bundle Metro — và cả ba đều làm app **không dùng được**, chứ không phải dùng kém.

Ngoài ra: nếu Expo Go đang cài là SDK khác SDK 54 mà project ghim, app sẽ báo
*"Project is incompatible with this version of Expo Go"* và không mở được. **Bước 0 khi chạy thật là mở Expo Go
xem nó đang ở SDK nào**, rồi đặt `expo` trong `package.json` đúng số đó — không đoán.

### 2.2. Chưa kiểm chứng ATS với `http://`, và `ios.infoPlist` **vô hiệu trong Expo Go**

**Chưa kiểm gì.** Dashboard phục vụ `http://` trong LAN (không TLS). App Transport Security của iOS chặn tải
`http://` không mã hoá, và `fetch` của React Native trên iOS **đi qua** URL loading system nên **chịu** ATS.
Chưa biết iOS có cho qua tải tới IP LAN hay không.

**Điểm dễ hiểu sai nhất — cần nói rõ.** `apps/mobile/app.json:19-23` có khai:

```json
"infoPlist": {
  "NSAppTransportSecurity": { "NSAllowsLocalNetworking": true }
}
```

**Khoá này KHÔNG có tác dụng khi chạy trong Expo Go.** `Info.plist` khi chạy Expo Go là **của Expo Go**, không
phải của project. `ios.infoPlist` chỉ có hiệu lực khi prebuild / dev build. Vì vậy **tuyệt đối không** được
đọc dòng cấu hình đó rồi kết luận "đã xử lý ATS".

**Muốn kiểm thì cần gì.** Một iPhone + Expo Go + dashboard chạy trong LAN. Mở Safari **trên chính iPhone** tới
`http://<ip-lan>:8000/api/status` trước: nếu Safari mở được thì lỗi (nếu có) nằm ở app/ATS, không phải mạng.
Rồi thử trong app.

**Rủi ro nếu bỏ qua.** Nếu ATS chặn, **mọi** lời gọi mạng của app đều hỏng ngay lập tức và app chỉ hiện câu
"Không kết nối được tới máy chủ" — người dùng sẽ tưởng sai IP hoặc dashboard tắt, và đi sửa đúng chỗ không
hỏng. Đường xử lý theo thứ tự: (1) thử luôn, nhiều bản iOS cho qua mạng nội bộ; (2) nếu bị chặn, dựng HTTPS cho
dashboard trong LAN (reverse proxy có chứng chỉ tin được trên thiết bị) rồi nhập `https://…` — đây là phương án
**khả thi duy nhất** trong ràng buộc hiện tại; (3) dev build để `NSAllowsLocalNetworking` có hiệu lực thì
**không làm được trên Windows** (cần macOS/Xcode hoặc EAS Build trên cloud).

Kể cả khi ATS cho qua, iOS vẫn có thể hỏi quyền **"Local Network"** cho kết nối LAN — phải bấm **Cho phép**.
Đó là hành vi của hệ điều hành, không phải lỗi app.

### 2.3. Chưa chạy trên Pi + camera thật

**Chưa kiểm gì.** Chưa có phép đo nào trên Raspberry Pi 4 với camera IP thật.

**Giả thuyết chưa được xác nhận.** Nguyên nhân gốc của lỗi mất skeleton là **BotSORT đổi track id** khi người
cúi xuống / rời nửa khung / ánh sáng đổi. Đây là **giả thuyết có dẫn chứng** — chuỗi nhân quả từ "mất track id"
tới "mất skeleton + loa báo oan" đã được **chạy và đo** trên PC với model giả, nhưng việc BotSORT **thật sự**
đổi id trong cảnh của người dùng thì **chưa đo**.

Điều này **không** làm bản sửa mất giá trị: chỉ cần một lần track id đổi là lỗi cũ xảy ra và tự kéo dài 120
giây (`timing.absent_reset_s`, `config.yaml:166`). Bản sửa xử lý đúng ca đó. Nhưng nếu nguyên nhân thật lại là
thứ khác (ví dụ camera rung, hoặc model bỏ sót người khi cúi), thì bản sửa **không** giải quyết được, và người
dùng vẫn thấy lỗi.

**Muốn kiểm thì cần gì.** Pi 4 + camera IP + chạy `posture_monitor run` với `tracking.enabled: true`, bật log
`INFO` để thấy dòng "Track id … mất khỏi khung nhưng còn người: bám lại track id …" (in ở `pose.py:620-625`).
Nếu dòng đó xuất hiện đúng lúc người dùng cúi xuống → giả thuyết đúng. Nếu không bao giờ xuất hiện mà vẫn mất
skeleton → nguyên nhân nằm ở chỗ khác, cần điều tra lại từ đầu.

**Rủi ro nếu bỏ qua.** Bản sửa có thể **không giải quyết** lỗi mà người dùng thật sự gặp, trong khi mọi test
vẫn xanh. Đây là khoảng trống lớn thứ hai sau mục 2.1.

### 2.4. Bốn hằng số `REACQUIRE_*` và `FRAME_WAIT_S` chưa được hiệu chuẩn

**Chưa kiểm gì.** Năm hằng số dưới đây là **lựa chọn có lý do**, không phải kết quả của phép đo nào. Docstring
của từng hằng số đã ghi rõ "CHƯA đo trên dữ liệu thật":

| Hằng số | Giá trị | Vị trí | Vai trò |
|---|---|---|---|
| `REACQUIRE_MIN_FRAME_RATIO` | `0.05` | `src/posture_monitor/pose.py:69` | Hộp phải rộng **và** cao ≥ 5% cạnh khung tương ứng |
| `REACQUIRE_MAX_ASPECT_RATIO` | `4.0` | `src/posture_monitor/pose.py:79` | Loại hộp quá dẹt (mép bàn, bóng đổ) |
| `REACQUIRE_MAX_CENTER_SHIFT_RATIO` | `0.5` | `src/posture_monitor/pose.py:98` | Tâm không được lệch quá 0,5 × cạnh dài hộp trước |
| `REACQUIRE_MIN_IOU` | `0.1` | `src/posture_monitor/pose.py:111` | IoU tối thiểu để coi là cùng người |
| `FRAME_WAIT_S` | `0.5` | `src/posture_monitor/web/app.py:139` | Chờ khung tối đa cho `GET /api/frame` (giây) |

**Muốn kiểm thì cần gì.** Quay một video ngắn cảnh người học thật (cúi xuống, xê dịch ghế, đứng dậy, có người
khác đi qua), rồi đo phân bố IoU và khoảng cách tâm giữa hai hộp liên tiếp. Công cụ cho việc này **đang được
làm song song ở t20** (`scripts/calibrate_reacquire.py`) — xem mục 3.

**Rủi ro nếu bỏ qua.** Hai chiều, và chúng đối nghịch nhau:

- **Ngưỡng quá chặt:** người cúi xuống làm hộp co mạnh → cổng liên tục chặn → `detect()` trả `None` → **lỗi cũ
  quay lại** (mất skeleton, báo "quay lại bàn học" oan). Đây là kịch bản tệ nhất vì nó đúng là lỗi người dùng
  đã phàn nàn, và nó chỉ xảy ra trên cảnh thật.
- **Ngưỡng quá lỏng:** người khác đi ngang qua trong bán kính ~180 px bị coi là cùng người → khoá nhảy sang
  người kia → người học rời bàn mà hệ thống vẫn báo "có mặt".

Cả hai chiều đều **không thể phát hiện bằng test hiện có** (test dùng hộp giả do người viết đặt), nên chỉ đo
trên dữ liệu thật mới biết.

---

## 3. Việc nên làm tiếp, theo thứ tự

Thứ tự dưới đây xếp theo **cái gì chặn cái gì** và **cái gì rủi ro cao nhất nếu bỏ** — không theo độ dễ.

### 1. Chạy thử trên iPhone / Expo Go thật (mục 2.1 + 2.2) — **làm trước tiên**

**Vì sao đứng đầu:** mọi thứ khác đều phụ thuộc vào việc app có mở được không. Nếu ATS chặn hoặc Expo Go lệch
SDK, app **không dùng được** và mọi việc khác trở nên vô nghĩa. Đây cũng là việc **rẻ nhất** — cần một chiếc
iPhone và vài phút, không cần viết mã.

**Việc cụ thể:** mở Expo Go xem SDK đang cài → đặt `expo` trong `package.json` đúng số đó → `npx expo start` →
quét QR → làm theo mục 4 dưới đây để biết app có hoạt động không.

**Chặn việc gì:** chặn mọi đánh giá về app. Chưa qua bước này thì không được nói "app đã chạy".

### 2. Chạy trên Pi + camera thật (mục 2.3) — **rủi ro cao nhất về đúng/sai của bản sửa**

**Vì sao đứng thứ hai:** đây là bước duy nhất xác nhận được bản sửa lỗi skeleton **thật sự** giải quyết lỗi
người dùng gặp. Tất cả bằng chứng hiện có đều là model giả trên PC. Nếu giả thuyết BotSORT sai, cả bản sửa là
công cốc — và chỉ bước này mới phát hiện được.

**Việc cụ thể:** chạy `posture_monitor run` với log `INFO`, quan sát dòng "bám lại track id" có xuất hiện đúng
lúc người dùng cúi xuống hay không; đồng thời xác nhận skeleton **có** hiện và **không** bị mất.

**Chặn việc gì:** chặn việc tuyên bố "đã sửa xong lỗi mất skeleton". Chặn cả việc chốt các hằng số ở mục 2.4.

### 3. Hiệu chuẩn bốn hằng số `REACQUIRE_*` (mục 2.4) — **t20 đang làm song song**

**Vì sao đứng thứ ba:** phụ thuộc vào bước 2 (cần dữ liệu thật mới đo được), nhưng **đang được giải quyết dứt
điểm** bởi công cụ `scripts/calibrate_reacquire.py` trong task **t20** (đang chạy song song, cùng lúc với tài
liệu này). Công cụ đó sẽ:

- đo IoU và khoảng cách tâm giữa hai hộp liên tiếp từ camera `usb:N` hoặc từ file video;
- in **phân bố** giá trị để người dùng tự chọn ngưỡng, kèm bảng gợi ý cho `REACQUIRE_MIN_IOU` và
  `REACQUIRE_MAX_CENTER_SHIFT_RATIO`;
- **không tự sửa** `pose.py` — mọi thay đổi ngưỡng vẫn là quyết định của người dùng sau khi đọc số đo;
- ghi kết quả ra JSON, không ghi vào `data/`.

Vì vậy **không cần làm lại việc đo bằng tay**: chờ t20 xong, chạy công cụ trên video thật, đọc bảng, rồi quyết
định có đổi ngưỡng hay không. Nếu t20 chưa xong khi cần, có thể đo tạm bằng tay theo mục 2.4.

**Lưu ý:** `FRAME_WAIT_S = 0.5` (`app.py:139`) **không** nằm trong phạm vi t20 (công cụ đo hộp, không đo độ trễ
ảnh). Muốn hiệu chuẩn nó cần đo thời gian thật từ lúc `set_frame` tới lúc app nhận ảnh — việc riêng, ưu tiên
thấp vì 0,5 s đã ngắn hơn `STREAM_WAIT_S` 2,0 s và có test chặn việc nâng lên.

### 4. Sửa M1 (harness test) — trước lần sửa app tiếp theo

**Vì sao đứng thứ tư:** không cấp bách cho bản hôm nay, nhưng **phải xong trước khi có người sửa app lần nữa**.
Để nguyên thì mọi lần sửa sau đều được bảo đảm bằng một chốt chặn bị hở (9/10 bài verify không bắt được lỗi
lúc bấm nút).

### 5. Sửa M2 + M3 cùng một lượt — dọn dẹp nhỏ

**Vì sao đứng cuối:** cả hai đều thấp, sửa vài dòng, nên làm cùng lúc cho gọn. Không chặn gì.

### 6. P1 — chỉ sửa **sau** khi có số đo từ bước 3

**Vì sao đứng cuối và vì sao không sửa sớm:** siết ngưỡng diện tích tuyệt đối mà chưa đo trên camera thật có
rủi ro **chặn oan** đúng ca cần cứu (người cúi xuống làm hộp co mạnh). Sửa mò ở đây nguy hiểm hơn để nguyên.

---

## 4. Cách tự xác nhận nhanh trên máy thật

Sáu bước, làm một lần, khoảng 3–5 phút. Mục đích: biết **bản sửa có hiệu lực** hay không, không cần đọc log.

**Chuẩn bị trước:** dashboard đã chạy trên Pi (`posture_monitor run`), điện thoại và Pi **cùng một mạng Wi-Fi**,
app đã nhập địa chỉ LAN trong tab **Kết nối** và bấm **Kiểm tra kết nối** thấy "Kết nối tốt".

1. **Bật dashboard, rồi mở app.** Vào tab **Kết nối**, nhập `http://<ip-lan>:8000`, bấm **Lưu địa chỉ** rồi
   **Kiểm tra kết nối**. Phải thấy chữ **"Kết nối tốt"** kèm trạng thái tư thế. Nếu thấy "Không kết nối được
   tới máy chủ" → dừng ở đây, xem mục 2.2 (ATS) trước khi đi sửa gì khác.

2. **Mở tab Camera.** Trong vòng ~1 giây phải thấy **một khung ảnh** (không phải ô trống). Ảnh tự tải lại mỗi
   2 giây — nhìn đồng hồ "cập nhật …" ở góc phải để chắc nó đổi. Nếu báo "Chưa cấu hình máy chủ" dù đã lưu →
   quay lại bước 1.

3. **Bấm Bắt đầu học trong tab Phiên học, rồi quay lại tab Camera.** Ngồi đúng trong khung. **Skeleton phải
   hiện** — các đường nối màu xanh lá vẽ trên người bạn. Đây là điểm mấu chốt của toàn bộ bản sửa: trước khi
   sửa, bước này có thể mất skeleton suốt 120 giây dù bạn vẫn ngồi đó.

4. **Cúi gập xuống bàn vài giây (động tác làm BotSORT đổi track id), rồi ngồi thẳng lại.** Skeleton **phải
   tiếp tục hiện** — có thể nhảy nhẹ một khung rồi bám lại, nhưng **không được mất hẳn**. Nếu mất skeleton và
   chỉ hiện lại sau rất lâu → bản sửa chưa hiệu lực trên cảnh của bạn, xem mục 2.3.

5. **Đứng dậy, đi ra khỏi khung.** Sau khoảng **3–5 giây** loa phải báo *"Bạn ơi, quay lại bàn học nhé"*.
   (Con số: `presence.absent_grace_s` = 3,0 s ở `config.yaml:202`, cộng `schedule.kinds.leave_frame.hold_s`
   = 5 s ở `config.yaml:330`.) Đây là chiều **ngược lại** và quan trọng không kém: bản sửa không được phá tính
   năng báo rời bàn. Nếu **không** báo → bản sửa đang bám nhầm người, xem mục 2.4.

6. **Ngồi lại vào khung.** Loa phải **im** trong vòng ~1 giây (không lặp lại "quay lại bàn học"). Rồi thử ca
   cuối: nhờ **một người khác** đi ngang qua khung hoặc ngồi vào ghế bên cạnh. Skeleton phải **vẫn bám bạn**,
   không nhảy sang người kia.

**Cách đọc kết quả:**

- Qua được **cả 6 bước** → bản sửa hoạt động đúng trên máy thật của bạn.
- Hỏng ở bước 1–2 → vấn đề kết nối/ATS, **không phải** bản sửa lỗi skeleton. Xem mục 2.2.
- Hỏng ở bước 3–4 → bản sửa **chưa** giải quyết lỗi trên cảnh của bạn. Xem mục 2.3, và nếu có log hãy tìm dòng
  "bám lại track id" để biết giả thuyết BotSORT có đúng không.
- Hỏng ở bước 5 → bản sửa **phá** tính năng báo rời bàn. Đây là lỗi nghiêm trọng, cần báo lại ngay; nguyên
  nhân nhiều khả năng nằm ở các hằng số `REACQUIRE_*` (mục 2.4).

---

## Ghi chú về mức độ tin cậy của tài liệu này

- **Số dòng** trong tài liệu được đối chiếu trực tiếp với mã nguồn tại thời điểm viết bằng cách grep từng tệp,
  không chép từ báo cáo phản biện cũ. Riêng con số "6/10 bài verify" trong báo cáo t18 là **đếm thiếu**; tài
  liệu này ghi **9/10** (đã đếm lại từng bài).
- **Mục 1** (bốn lỗi M1–M3, P1) là những thứ **đã đo được** bằng cách chạy mã, không phải suy đoán.
- **Mục 2** là những thứ **chưa đo được** vì thiếu thiết bị. Không có kết luận nào ở mục 2 được trình bày như
  đã kiểm chứng.
- Tài liệu này **không sửa một dòng mã nguồn nào**. Mọi gợi ý sửa ở mục 1 đều ở dạng đề xuất.
