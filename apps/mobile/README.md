# App điện thoại — Giám sát học tập (Expo Go, iOS)

App React Native (TypeScript, Expo SDK 58) điều khiển và xem dashboard của Pi
qua mạng LAN: trạng thái, camera (luồng MJPEG trực tiếp + ảnh tĩnh dự phòng),
phiên học, tín hiệu, điều khiển (tắt tiếng, PTZ), giọng đọc, lịch sử vi phạm
và kết nối.

Chạy bằng **Expo Go**, không build native iOS. Máy dev là Windows nên **không**
có Xcode, không có `xcodebuild`, không có iOS Simulator.

---

## 1. Chạy trong 4 bước

```powershell
cd apps\mobile
npm install          # lần đầu
npx expo start
```

1. Cài **Expo Go** từ App Store trên iPhone.
2. Điện thoại và máy chạy dashboard phải **cùng một mạng Wi-Fi**.
3. Quét QR mà `npx expo start` in ra bằng **Camera** của iOS (iOS 11 trở lên
   nhận QR của Expo Go trực tiếp; không cần app quét riêng). Hoặc mở Expo Go
   rồi nhập URL `exp://<ip-máy-dev>:8081` bằng tay.
4. Lần đầu mở project, Expo Go có thể yêu cầu **đăng nhập tài khoản Expo**.
   Expo CLI và Expo Go phải đăng nhập **cùng một tài khoản** thì iPhone thật
   mới mở được project ([Expo — Start developing](https://docs.expo.dev/get-started/start-developing.md)).

> **Lưu ý về phiên bản Expo Go.** Mỗi bản Expo Go nhúng **đúng một** SDK; lệch
> là lỗi *"Project is incompatible with this version of Expo Go"*. Project này
> khai báo `expo: ~58.0.24` (Expo SDK 58) trong [package.json](package.json).
> Trên iPhone thật **không cài được bản Expo Go cũ hơn**, cũng không tự build
> Expo Go mới nếu không có Apple Developer Program
> ([Expo — Expo Go version mismatch](https://docs.expo.dev/troubleshooting/expo-go-version-mismatch.md)).
> Vì vậy: **bước 0 khi chạy thật là mở Expo Go xem nó đang ở SDK nào**, rồi đặt
> `expo` trong `package.json` đúng số đó. Không đoán.

Sau khi sửa phiên bản, kiểm tra và đồng bộ:

```powershell
npx expo install --fix
npx expo-doctor@latest
```

---

## 2. Nhập địa chỉ máy chủ (bắt buộc, lần đầu)

App **không hardcode IP nào**. Mở tab **Kết nối**, nhập địa chỉ gốc của máy
chạy dashboard rồi bấm **Lưu địa chỉ** và **Kiểm tra kết nối**:

```
http://192.168.x.x:8000
```

- Lấy IP LAN: `ipconfig` trên Windows (mục *IPv4 Address* của card Wi-Fi),
  `hostname -I` trên Pi.
- Cổng mặc định là `8000` (`config.yaml` → `web.port`). Đổi cổng trong
  `config.yaml` thì nhập cổng mới ở đây — app không có cổng dự phòng nào.
- Địa chỉ được lưu bằng AsyncStorage, mở lại app vẫn còn.

### Vì sao tuyệt đối không dùng `localhost`

Trên iPhone, `localhost` / `127.0.0.1` trỏ vào **chính chiếc điện thoại**, không
phải máy chạy dashboard → mọi request hỏng ngay. App vẫn cho nhập (để dùng được
với iOS Simulator chạy cùng máy) nhưng hiện cảnh báo vàng ngay dưới ô nhập.

Một cái bẫy nữa: khi chạy, dashboard in ra `http://127.0.0.1:8000/` — địa chỉ đó
**không** phải địa chỉ nhập vào app, vì `web.host: 0.0.0.0` được đổi thành
`127.0.0.1` chỉ để hiển thị.

---

## 3. ATS và `http://` trên iOS — **chưa kiểm chứng**

App Transport Security (ATS) chặn tải `http://` không mã hoá, và `fetch` của
React Native trên iOS đi qua URL loading system nên **chịu** ATS.

**Quan trọng:** khi chạy trong **Expo Go**, `Info.plist` là của **Expo Go**,
không phải của project. `ios.infoPlist` trong [app.json](app.json) (đang đặt
`NSAllowsLocalNetworking: true`) **không có tác dụng trong Expo Go** — nó chỉ có
tác dụng khi prebuild / dev build. Vì vậy:

- **Mức độ chắc chắn: CHƯA KIỂM CHỨNG.** Phiên làm việc này không có iPhone
  thật, nên không thể nói `http://<ip-lan>:8000` bị chặn hay được cho qua.
- Cách xử lý theo thứ tự:
  1. Thử luôn từ app. Nhiều bản iOS cho qua tải trong mạng nội bộ.
  2. Nếu bị chặn: dựng HTTPS cho dashboard trong LAN (reverse proxy có chứng
     chỉ tin được trên thiết bị) rồi nhập `https://…`. **Đây là phương án khả
     thi duy nhất** trong ràng buộc hiện tại, vì dev build iOS không làm được
     trên Windows.
  3. Nếu buộc phải `http://` và ATS chặn: cần **development build** để
     `app.json` → `ios.infoPlist` → `NSAppTransportSecurity` →
     `NSAllowsLocalNetworking: true` có hiệu lực. Không làm được trên máy
     Windows này.
- Kể cả khi ATS cho qua, iOS vẫn có thể hỏi quyền **"Local Network"** cho kết
  nối trong LAN — cần bấm **Cho phép**. Đó là hành vi của hệ điều hành, không
  phải lỗi app.

---

## 4. Vì sao giao diện trông như vậy

Ba quyết định có chủ đích (bảng màu và kiểu chữ nằm ở
[src/theme.ts](src/theme.ts)):

1. **Hệ thống giao diện kép Sáng & Tối (`dark` / `light`).** Chế độ Tối (*Nocturne Telemetry*, `#0F141A`) dịu mắt cho bàn học buổi tối; chế độ Sáng (*Daylight Studio*, `#F0F2F5` + thẻ trắng `#FFFFFF` + xanh `#1877F2`) đồng bộ trực tiếp với bảng điều khiển Web Dashboard, dễ nhìn ban ngày. Chuyển đổi tức thì từ nút gạt nhanh góc trên mọi màn hình hoặc ở tab **Kết nối**, lưu bền vững qua `AsyncStorage`.
2. **Ba màu trạng thái đồng bộ ngữ nghĩa với dashboard web** — xanh lục = đang ổn, hổ phách = cần chú ý, đỏ san hô = sai/vắng — với độ tương phản đạt chuẩn đọc rõ trên cả nền tối lẫn nền sáng. Mỗi màu luôn đi kèm nhãn chữ, không bao giờ chỉ dùng màu làm kênh duy nhất.
3. **Số liệu dùng font mono + `tabular-nums` cỡ lớn trong lưới Bento 2×2.** Điện thoại đặt trên bàn nên phải đọc được từ xa, và chữ số không được nhảy bề rộng mỗi lần làm mới 2 giây.

Điều hướng là **thanh tab tự viết** ([src/navigation/TabNavigator.tsx](src/navigation/TabNavigator.tsx)),
không dùng `@react-navigation/bottom-tabs`. Lý do: app chỉ có **6 tab cố định**
(gộp trọn **Camera + 3 Tín hiệu người học + Trạng thái tư thế** ngay trên tab đầu
tiên), không tham số route;
react-navigation kéo thêm `react-native-screens`, `@react-navigation/elements`… —
mỗi gói là một chỗ có thể lệch phiên bản với Expo Go, mà lệch phiên bản trong
Expo Go là lỗi cài đặt chứ không phải lỗi mã. Thêm nữa, chỉ màn đang hiện được
mount nên vòng tự làm mới của màn khác **dừng hẳn** khi chuyển tab.

---

## 5. Các màn hình và route tương ứng

Hợp đồng API đầy đủ: [docs/REQUIREMENTS_MOBILE_AND_PRESENCE_FIX.md](../../docs/REQUIREMENTS_MOBILE_AND_PRESENCE_FIX.md) §4.2.

| Tab | Route dùng | Ghi chú |
|---|---|---|
| **Camera** *(gộp 3 Tín hiệu & Trạng thái)* | `GET /stream`, `GET /api/frame`, `GET /api/signals`, `GET /api/status`, `POST /api/mute` | Màn chính gộp: (1) Khung Camera 4:3 (MJPEG trực tiếp + tự lùi sang `GET /api/frame` mỗi **300 ms** khi `stream_enabled = false` hoặc WebView lỗi), (2) Cụm **3 Tín hiệu người học** đặt ngay dưới khung Camera (`Có mặt`, `Điện thoại`, `Người đang học / Danh tính` kèm lối tắt **Đổi / Thêm ›**), (3) **Trạng thái tư thế & lưới Bento 2×2** (điểm **thang 100**, đã ngồi, khoảng cách, công tắc bật/tắt tiếng nhanh) |
| **Người học** | `GET/POST /api/people`, `DELETE /api/people/<id>`, `POST /api/select`, `GET /api/enroll/<id>`, `POST /api/enroll/<id>/cancel` | Chọn / bỏ chọn người đang học, xoá hồ sơ xác nhận 2 bước, và thêm người mới bằng **quét khuôn mặt 5 bước kiểu Face ID** (có luồng camera trực tiếp + vòng tròn căn mặt + tiến độ mẫu; bấm **Quét lại** mở phiên mới; rời tab khi đang quét tự gửi `/cancel`) |
| **Phiên học** | `GET /api/session`, `POST /api/session/start\|stop` | 503 ⇒ hiện câu server, **khoá nút**, không crash. 400 ⇒ hiện đúng `message` của server |
| **Điều khiển** *(Âm thanh, PTZ & Giọng đọc)* | `GET /api/status`, `POST /api/mute`, `POST /api/ptz`, `GET/POST /api/voice` | Tắt/bật tiếng cảnh báo, 4 nút xoay PTZ (`{"direction","duration":0.5}`, khoá đồng thời khi đang xoay) và chọn giọng đọc cảnh báo (`nam`/`nu`/`espeak`, đọc `missing`/`ready` từng giọng và hiện nguyên câu `fallbacks` của server) |
| **Vi phạm** | `GET /api/violations?limit=200` | Lịch sử rời bàn, dùng điện thoại, sai người học từ bảng `events`. Chỉ tải khi mở tab hoặc bấm **Làm mới** (**không** poll định kỳ). Nhãn `kind_text` lấy thẳng từ server |
| **Kết nối** | `GET /api/status` | Chọn chế độ **Giao diện Sáng / Tối**, nhập/lưu địa chỉ máy chủ LAN, kiểm tra kết nối |

**Không có `POST /api/session`.** Gọi vào đó sẽ nhận **405** kèm thân **HTML**
(đã đo bằng Flask `test_client`). App dùng đúng `GET` + `/start` + `/stop`.

Dashboard **đã có** `GET /api/frame` ([`web/app.py`](../../src/posture_monitor/web/app.py))
— route trả một khung JPEG mới nhất trong bộ nhớ. Nếu app nhận **404**, nghĩa là
bản dashboard **đang chạy** cũ hơn mã nguồn hiện tại: cập nhật rồi khởi động lại
rồi thử lại. Màn Camera xử lý đúng ca đó bằng thông điệp "Máy chủ chưa có route
ảnh", không crash, không làm hỏng các màn khác.

### Màn Giọng đọc đọc `missing`/`ready` và hiện nguyên câu server

`GET /api/voice` trả hai thứ **khác nhau**, và app không được lẫn:

- `voices[ma].missing` (danh sách loại câu còn thiếu) và `voices[ma].ready`
  (cờ tổng hợp) nói **giọng đó** thiếu bản thu gì. App đọc đúng hai trường này
  để hiện chip "Thiếu bản thu" và dòng "Thiếu bản thu cho: …" **dưới từng
  giọng** — không suy từ `fallbacks`.
- `fallbacks` là `{loại_cảnh_báo: "<câu tiếng Việt>"}`
  ([`speaker_alert.py`](../../src/posture_monitor/speaker_alert.py) gán
  `_fallback_notes[kind] = "Chưa có bản thu … nên tạm dùng giọng máy."`), tức
  **value là câu giải thích, không phải mã giọng**. App hiện **nguyên văn**
  câu đó trong khối "Còn câu phải mượn giọng khác" và dùng key để đếm số câu.

Đọc value của `fallbacks` như thể nó là mã giọng là lỗi đã từng có trong bản
trước: nó in ra câu app tự ghép "đang phát bằng espeak" — sai cả nghĩa lẫn
nguồn. Các bài kiểm trong
[`test/ui/voiceScreen.test.mjs`](test/ui/voiceScreen.test.mjs) khoá lại điều
này.

### Một lớp gọi mạng duy nhất

Mọi lời gọi đi qua [src/api/client.ts](src/api/client.ts):

- **Timeout** bằng `AbortController` — 5 s cho JSON, 10 s cho ảnh.
- **Trả cả mã HTTP**, vì UI cần phân biệt 403 / 404 / 503.
- **Không bao giờ gọi `response.json()` vô điều kiện**: 405 và 404 ngoài tiền tố
  `/api/` là HTML, nên client đọc `text()` trước rồi mới thử `JSON.parse`.
- **Mọi lỗi thành câu tiếng Việt** ([src/api/errors.ts](src/api/errors.ts));
  `message` của server được ưu tiên hiện thẳng.

---

## 6. Kiểm thử không cần cài `node_modules` của app

Phần logic thuần (**không import `react-native`**) nằm ở:

- [src/api/url.ts](src/api/url.ts) — chuẩn hoá địa chỉ, dựng URL
- [src/api/errors.ts](src/api/errors.ts) — mã lỗi → câu tiếng Việt + gợi ý theo route
- [src/api/format.ts](src/api/format.ts) — định dạng số thập phân, thời lượng, đồng hồ đếm ngược, mốc giờ `HH:MM:SS`
- [src/api/payload.ts](src/api/payload.ts) — chuẩn hoá `/api/status`, `/api/session`, `/api/signals`, `/api/voice`, `/api/violations`
- [src/api/framePolicy.ts](src/api/framePolicy.ts) — chính sách thử lại ảnh camera
- [src/api/client.ts](src/api/client.ts) — lớp gọi mạng (nhận `fetch` tiêm được)

Test chạy bằng **node thuần**, không Metro, không máy ảo, không build:

```powershell
cd apps\mobile
npm test            # 160 bài: logic thuần, KHÔNG cần npm install
npm run verify      # 29 bài: giao diện thật trong jsdom (CẦN npm install)
npm run verify:all  # cả hai (189 bài)
```

Cần **Node ≥ 22.18** — đây là điều kiện cứng, vì `test/register-ts.mjs` dùng
`module.registerHooks` để nạp TypeScript không cần build. `npm test` tự kiểm
tra và báo bằng câu tiếng Việt nếu Node cũ hơn. Không cần
`--experimental-strip-types`: tính năng bóc kiểu đã bật mặc định ở các bản Node
đó.

**Hai tầng kiểm thử, và lý do tách:**

| Lệnh | Nội dung | Cần `npm install`? |
|---|---|---|
| `npm test` | Logic thuần trong `test/`: chuẩn hoá payload, định dạng, mã lỗi → tiếng Việt, dựng URL, chính sách thử lại ảnh | **Không** — không import gói nào từ `node_modules` |
| `npm run verify` | Dựng **app React Native thật** trong jsdom rồi bấm nút: đổi giọng + "Gửi lại", đồng bộ tắt tiếng, tự lùi từ `/stream` sang ảnh tĩnh, huỷ request khi rời màn, giữ khung ảnh cuối | **Có** — cần `jsdom`, `react-dom`, `react-native-web`, Babel (đã khai trong `devDependencies`) |

Tách như vậy để `npm test` vẫn chạy được ở môi trường tối thiểu, còn các bài
kiểm giao diện thì **thuộc bản bàn giao** và chạy lại được bằng một lệnh —
không phải kịch bản dùng một lần nằm ngoài repo.

Kiểm tra kiểu:

```powershell
npx tsc --noEmit
```

---

## 7. Giới hạn của môi trường này

- **Máy dev Windows không build native iOS.** Không `npx expo run:ios`, không
  tạo được `.ipa`, không có iOS Simulator. App chỉ chạy trong **Expo Go**.
- Mọi thư viện cần **native module không có trong Expo Go** đều bị loại. Bộ
  thư viện hiện dùng (`react-native-safe-area-context`,
  `@react-native-async-storage/async-storage`, `react-native-webview`,
  `expo-status-bar`) đều có sẵn trong Expo Go.
- Nếu sau này cần một SDK cũ hơn bản Expo Go đang cài, hoặc cần `Info.plist`
  của riêng project (ví dụ để xử lý ATS), thì **phải dùng development build** —
  và việc đó **không làm được trên Windows** (cần macOS/Xcode hoặc EAS Build
  trên cloud).
- `npx expo start --tunnel` chỉ giúp **Metro** tới được điện thoại; nó **không**
  làm Pi trở nên truy cập được. Địa chỉ API vẫn phải là IP LAN.

---

## 8. Cấu trúc

```
apps/mobile/
├── App.tsx                       # SafeArea + AppProvider + thanh tab
├── index.ts                      # registerRootComponent
├── app.json                      # name/slug/scheme/icon/ios.supportsTablet
├── assets/                       # icon, splash, adaptive-icon, favicon
├── src/
│   ├── api/                      # logic thuần, formatters + lớp client duy nhất
│   ├── components/
│   │   ├── ui.tsx                    # khối giao diện dùng chung
│   │   ├── LearnerSignalsSection.tsx # cụm 3 Tín hiệu người học trực tiếp (Bento 2+1)
│   │   └── PostureStatusSection.tsx  # cụm Trạng thái + Bento 2×2 (Stitch)
│   ├── context/AppContext.tsx    # địa chỉ máy chủ + client
│   ├── hooks/
│   │   ├── usePoll.ts            # tự làm mới tuần tự + toPollFetcher
│   │   └── useAsyncAction.ts     # huỷ lệnh trước & chặn setState sau unmount
│   ├── navigation/               # thanh tab tự viết (6 tab, mở mặc định Camera gộp)
│   ├── screens/                  # các màn hình (CameraScreen gộp 3 Tín hiệu + Trạng thái)
│   ├── storage/baseUrl.ts        # AsyncStorage
│   └── theme.ts                  # bảng màu Nocturne Telemetry, khoảng cách, kiểu chữ
└── test/                         # test thuần + test/ui chạy trong jsdom
```

## 9. Lỗi thường gặp

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| "Project is incompatible with this version of Expo Go" | `expo` trong `package.json` khác SDK của Expo Go | Xem SDK trong Expo Go, đặt `expo` đúng số đó, `npx expo install --fix` |
| "Không kết nối được tới máy chủ" | Khác LAN, sai IP, dashboard tắt, tường lửa | Mở `http://<ip>:8000/api/status` bằng Safari **trên chính iPhone**. Được thì lỗi ở app (địa chỉ/ATS); không được thì lỗi ở mạng |
| "Máy chủ chưa có route ảnh" (404) | Bản dashboard **đang chạy** chưa có `GET /api/frame` — mã nguồn đã có route này, nhưng tiến trình đang phục vụ là bản cũ | Cập nhật dashboard lên bản có route đó, khởi động lại tiến trình rồi bấm Thử lại |
| "Xem trực tiếp đang tắt" (403) | `web.stream_enabled: false` | Bật trong `config.yaml` rồi khởi động lại dashboard |
| "Phiên học chưa bật" (503) | Dashboard chạy không có `StudySession` | Chạy dashboard đúng cách; app không gọi sai route |
| Ảnh đứng yên | Camera không đẩy khung mới | Kiểm tra log dashboard; ở chế độ Ảnh tĩnh app vẫn tải lại mỗi 300 ms, ở chế độ Trực tiếp luồng đọc từ `/stream` |
