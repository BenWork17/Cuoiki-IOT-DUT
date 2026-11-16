# Tích hợp: chạy dashboard + app Expo Go trên iPhone

> **Trạng thái tài liệu (đọc trước).** Đây là hướng dẫn *vận hành* cho bản mã
> hiện tại. Mọi lệnh đã được chạy trên **Windows PowerShell 5.1** của máy dự án;
> mọi route đã được đối chiếu với `src/posture_monitor/web/app.py` bằng cách
> dump `url_map` từ chính `create_app()`.
>
> **Chưa có bước nào dưới đây được chạy trên iPhone thật.** App mới chỉ được
> kiểm bằng test logic Node (139 bài), test giao diện trong jsdom (10 bài),
> typecheck, và build bundle iOS; bản sửa lỗi "quay lại bàn học" mới được kiểm
> bằng model giả, chưa bằng camera + model thật. Danh sách đầy đủ ở mục
> [§9 Điều CHƯA kiểm chứng](#9-điều-chưa-kiểm-chứng).

---

## 0. Sơ đồ hai máy

```
iPhone (Expo Go)  ──Wi-Fi cùng LAN──►  Pi 4 / PC chạy dashboard
   │  HTTP tới http://<ip-lan>:8000/api/*        │
   │  Metro bundle từ máy dev (cổng 8081)        │  camera IP (RTSP) → pose → loa
```

Hai đường **khác nhau**, đừng lẫn:

| Đường | Ai phục vụ | Địa chỉ |
|---|---|---|
| Bundle JavaScript của app | máy dev chạy `npx expo start` (Metro) | `exp://<ip-máy-dev>:8081` |
| API dashboard (dữ liệu thật) | Pi/máy chạy `posture_monitor run` | `http://<ip-lan>:8000` |

`npx expo start --tunnel` chỉ giúp **Metro** tới được điện thoại. Nó **không**
làm Pi trở nên truy cập được: địa chỉ API vẫn phải là IP LAN.

---

## 1. Chạy dashboard (trên Pi hoặc trên PC)

### 1.1. Lệnh

Trên Pi (có GPIO thật):

```bash
cd ~/posture-monitor
source venv/bin/activate
export PYTHONPATH=src
python -m posture_monitor run --config config.yaml
```

Trên PC Windows (không có GPIO):

```powershell
cd E:\2026\DUT\IOT\Cuoiki
$env:PYTHONPATH = 'src'
python -m posture_monitor run --config config.yaml --no-gpio
```

Cần thử nhanh mà không đụng cấu hình đã commit: chép `config.yaml` thành
`config.local.yaml` (đã bị `.gitignore` chặn) rồi `--config config.local.yaml`.

`run` **cần một nguồn ảnh**. Không có camera thì `run` dừng ngay với câu
*Không mở được nguồn ảnh '…' nên không thể suy luận pose* và mã thoát 1. Trên
PC không có camera IP, dùng webcam USB (`camera.source: usb:0`) hoặc một video
(`camera.source: file:duong_dan.mp4`).

Kiểm tra CLI có đúng bản không:

```powershell
$env:PYTHONPATH = 'src'
python -m posture_monitor --version
python -m posture_monitor run --help
```

Đo được trên máy dự án: `posture_monitor 0.1.0`, và `run --help` liệt kê đúng
`--config`, `--no-gpio`, `--view`, `--save-overlay`, `--fps`, `--preview`,
`--no-preview`, `--log-level`.

### 1.2. Cổng và địa chỉ

| Khóa trong `config.yaml` | Giá trị mặc định | Ý nghĩa |
|---|---|---|
| `web.host` | `0.0.0.0` | nghe trên mọi card mạng — cần cho điện thoại trong LAN |
| `web.port` | `8000` | cổng dashboard và API |
| `web.stream_enabled` | `true` | bật ảnh camera (`/stream`, `/api/frame`) |

**Cái bẫy thật:** khi chạy, log in ra `Dashboard chạy tại http://127.0.0.1:8000/`.
Đó là địa chỉ **để hiển thị** (mã đổi `0.0.0.0` → `127.0.0.1` cho dễ đọc),
**không** phải địa chỉ nhập vào app.

Lấy IP LAN của máy chạy dashboard:

```powershell
ipconfig | Select-String -Pattern 'IPv4'
```

Trên Pi:

```bash
hostname -I
```

Chọn địa chỉ thuộc dải của router Wi-Fi bạn đang dùng (ví dụ `192.168.1.50` —
dải `192.168.1.x`, không phải `172.x` của card ảo hay `192.168.117.1` của
VMware/Hyper-V). Trong tài liệu này mọi địa chỉ đều là **giả định**.

### 1.3. Kiểm tra dashboard trước khi mở app

Gọi thẳng API từ máy dev (không cần điện thoại):

```powershell
$ip = '192.168.1.50'      # ← thay bằng IP LAN thật
$port = 8000

(Invoke-RestMethod -Uri "http://${ip}:${port}/api/status" -TimeoutSec 5) |
  Select-Object state, state_text, stream_enabled, data_age_s | Format-List

curl.exe -s -o NUL -w "frame: %{http_code} %{content_type}`n" `
  "http://${ip}:${port}/api/frame"

curl.exe -s -o NUL -w "stream: %{http_code}`n" "http://${ip}:${port}/stream"
```

Kết quả mong đợi: `/api/status` trả JSON có `"state"`, `"muted"`,
`"stream_enabled": true`; `/api/frame` trả `200 image/jpeg`; `/stream` trả
`200 multipart/x-mixed-replace`.

> Máy dự án là **Windows PowerShell 5.1** (không phải pwsh 7). Bản 5.1 có thể
> đòi engine IE cho `Invoke-WebRequest`; nếu lệnh đó báo lỗi kiểu
> *"NonInteractive mode"*, dùng `curl.exe` (Windows 10/11 có sẵn) như trên,
> hoặc thêm `-UseBasicParsing`.

**Tường lửa** — quên bước này là triệu chứng phổ biến nhất của "app không kết
nối được":

```powershell
# Chạy PowerShell với quyền Administrator
New-NetFirewallRule -DisplayName "Posture dashboard 8000" -Direction Inbound `
  -LocalPort 8000 -Protocol TCP -Action Allow
```

Không có quyền admin: mở Windows Defender Firewall → Advanced settings →
Inbound Rules → New Rule → Port → TCP 8000. Trên Pi có `ufw`: `sudo ufw allow 8000/tcp`.

### 1.4. Ghi lại log để tra sự cố

Log của `posture_monitor run` đi ra **stderr** (`logging_setup.py` gắn
`StreamHandler(stream=sys.stderr)`), và **không có cờ `--log-file`**. Muốn có
tệp log để grep:

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
python -m posture_monitor run --config config.yaml --no-gpio 2>&1 |
  Tee-Object -FilePath run.log
```

`Tee-Object` ghi tệp UTF-16LE có BOM; `Select-String -Path run.log -Pattern …`
đọc được bình thường (đã đo). Nếu bạn dùng `cmd /c "… 2> run.log"` thì tệp là
UTF-8 và **phải** thêm `-Encoding UTF8` khi đọc, nếu không các từ có dấu sẽ
không khớp.

Trên Pi:

```bash
export PYTHONPATH=src
python -m posture_monitor run --config config.yaml 2>&1 | tee run.log
```

---

## 2. Chạy app trên iPhone bằng Expo Go

### 2.1. Trên máy dev

```powershell
cd E:\2026\DUT\IOT\Cuoiki\apps\mobile
npm install          # lần đầu, hoặc sau khi đổi package.json
npx expo start
```

### 2.2. Trên iPhone

1. Cài **Expo Go** từ App Store.
2. iPhone và máy chạy dashboard phải **cùng một mạng Wi-Fi** (không dùng 4G,
   không dùng Wi-Fi khách có "AP isolation").
3. Quét QR mà `npx expo start` in ra bằng **Camera** của iOS (iOS 11 trở lên
   nhận QR của Expo Go trực tiếp), hoặc mở Expo Go rồi nhập tay
   `exp://<ip-máy-dev>:8081`.
4. Lần đầu, Expo CLI và Expo Go phải đăng nhập **cùng một tài khoản Expo** thì
   iPhone thật mới mở được project.

Mạng chặn thiết bị-tới-thiết bị (Wi-Fi công cộng, AP isolation):

```powershell
cd E:\2026\DUT\IOT\Cuoiki\apps\mobile
npx expo start --tunnel
```

Nhắc lại: `--tunnel` chỉ giải cứu **Metro**. Địa chỉ API vẫn là IP LAN của Pi.

### 2.3. Phiên bản Expo Go phải khớp SDK

Project ghim `expo: ~54.0.38` ([`package.json`](../apps/mobile/package.json)).
Mỗi bản Expo Go nhúng **đúng một** SDK; lệch là lỗi *"Project is incompatible
with this version of Expo Go"*, và trên iPhone thật **không cài được bản Expo
Go cũ hơn**.

**Bước 0 khi chạy thật:** mở Expo Go xem nó đang ở SDK nào, rồi đặt `expo`
trong `package.json` đúng số đó. Không đoán. Sau khi sửa:

```powershell
cd E:\2026\DUT\IOT\Cuoiki\apps\mobile
npx expo install --fix
npx expo-doctor@latest
```

---

## 3. Nhập địa chỉ máy chủ trong app

Mở tab **Kết nối** → nhập **địa chỉ gốc**, không kèm đường dẫn:

```
http://192.168.1.50:8000
```

rồi bấm **Lưu địa chỉ**, sau đó **Kiểm tra kết nối**.

- App **không hardcode IP nào**. Địa chỉ lưu bằng AsyncStorage (khóa
  `posture-mobile/base-url/v1`), mở lại app vẫn còn.
- Nhập `192.168.1.50:8000` (thiếu `http://`) vẫn được — app tự thêm.
- Nhập kèm đường dẫn (`.../api/status`) thì app **từ chối** kèm câu giải thích,
  vì app tự ghép đường dẫn.
- Cổng: `8000` theo `config.yaml`; đổi cổng ở đó thì nhập cổng mới ở đây. App
  **không** có cổng dự phòng.

### Vì sao tuyệt đối không `localhost`

Trên iPhone, `localhost` / `127.0.0.1` trỏ vào **chính chiếc điện thoại**, không
phải Pi → mọi request hỏng ngay. App vẫn cho nhập (hữu ích khi chạy iOS
Simulator cùng máy) nhưng hiện cảnh báo vàng ngay dưới ô nhập.

### Mẫu cấu hình tham chiếu

[`docs/mobile.config.example.json`](mobile.config.example.json) ghi lại bộ giá
trị đang dùng để đối chiếu khi báo lỗi:

```json
{
  "baseUrl": "http://192.168.1.50:8000",
  "pollMs": 2000
}
```

Đây là **mẫu để đọc và đối chiếu**, không phải tệp app tự nạp: app không đọc
tệp JSON nào, địa chỉ do người dùng nhập và lưu trong AsyncStorage. `pollMs` là
nhịp làm mới của app (`DEFAULT_POLL_MS = 2000`, sàn `MIN_POLL_MS = 1000`).

---

## 4. ATS và `http://` trên iOS — chưa kiểm chứng

App Transport Security (ATS) chặn tải `http://` không mã hoá; `fetch` của React
Native trên iOS đi qua URL loading system nên **chịu** ATS.

**Điểm quyết định:** khi chạy trong **Expo Go**, `Info.plist` là của **Expo Go**,
không phải của project. Vì vậy `ios.infoPlist` trong `app.json` (đang đặt
`NSAllowsLocalNetworking: true`) **KHÔNG có tác dụng trong Expo Go** — nó chỉ có
tác dụng khi prebuild / dev build.

**Mức độ chắc chắn: CHƯA KIỂM CHỨNG.** Không có iPhone thật trong phiên làm
việc này, nên không thể nói `http://<ip-lan>:8000` bị chặn hay được cho qua.

Thứ tự xử lý:

1. **Thử luôn từ app.** Nhiều bản iOS cho qua tải trong mạng nội bộ.
2. **Nếu bị chặn:** dựng HTTPS cho dashboard trong LAN (reverse proxy có chứng
   chỉ tin được trên thiết bị — ví dụ chứng chỉ tự ký đã cài + tin cậy trong
   Settings → General → About → Certificate Trust Settings), rồi nhập `https://…`.
   **Đây là phương án khả thi duy nhất** trong ràng buộc hiện tại.
3. **Nếu buộc phải `http://`:** cần **development build** để `app.json` →
   `ios.infoPlist` → `NSAppTransportSecurity` → `NSAllowsLocalNetworking: true`
   có hiệu lực. Dev build iOS **không làm được trên Windows** (không có Xcode,
   không có `xcodebuild`, không có iOS Simulator), phải dùng macOS hoặc EAS
   Build trên cloud.

Kể cả khi ATS cho qua, iOS vẫn có thể hỏi quyền **"Local Network"** cho kết nối
trong LAN — phải bấm **Cho phép**. Đó là hành vi của hệ điều hành, không phải
lỗi app.

---

## 5. Bảng: màn hình app ↔ route ↔ mã lỗi ↔ câu hiển thị

Nguồn sự thật của route là `src/posture_monitor/web/app.py`; bảng dưới được
đối chiếu bằng cách dump `url_map` từ chính `create_app()`:

```powershell
$env:PYTHONPATH = 'src'
python -c "from posture_monitor.web.app import create_app; a=create_app(); print('\n'.join(sorted(str(r.rule) for r in a.url_map.iter_rules())))"
```

`url_map` hiện có **21 đường dẫn** (đếm theo `rule` là 24 mục, vì `/api/voice`,
`/api/people`, `/api/schedule` đăng ký nhiều method thành nhiều mục):
`/`, `/api/calibrate`, `/api/enroll/<enroll_id>`,
`/api/enroll/<enroll_id>/cancel`, `/api/frame`, `/api/history`, `/api/mute`,
`/api/people` (GET, POST), `/api/people/<person_id>` (DELETE), `/api/ptz`,
`/api/schedule` (GET, PUT), `/api/select`, `/api/session`,
`/api/session/start`, `/api/session/stop`, `/api/signals`, `/api/speak`,
`/api/status`, `/api/voice` (GET, POST), `/static/<path:filename>`, `/stream`.

### 5.1. Tab trong app (7 tab)

| Tab | Route app gọi | Mã lỗi app phân biệt | Câu hiển thị (đo từ server) |
|---|---|---|---|
| **Trạng thái** | `GET /api/status` | không có nhánh lỗi — luôn 200 | `state_text`; `stale`/`data_age_s > 10` ⇒ **"Không nhận được dữ liệu mới"**; `PAUSED` ⇒ **"Chưa bắt đầu phiên học"** |
| **Camera** | `GET /api/frame` (+ `GET /api/status` lấy `stream_enabled`) | **403**, **404**, **503** | 403: *Tính năng xem trực tiếp đang tắt. Bật 'web.stream_enabled: true' …* 404: *Máy chủ chưa có route ảnh tĩnh này…* 503: *Chưa có khung hình nào trong bộ nhớ…* (503 **vẫn** tự thử lại) |
| **Phiên học** | `GET /api/session`, `POST /api/session/start`, `POST /api/session/stop` | **503**, **400** | 503: *Phiên học chưa được bật trong lần chạy này nên chưa bấm được Bắt đầu/Dừng.* 400: *Thời lượng phiên học phải trong khoảng 1–720 phút, nhận được 0 phút.* |
| **Tín hiệu** | `GET /api/signals` | **503** | *Tính năng người học chưa được bật trong phiên chạy này.* (`fresh: false` ⇒ **"Chưa có dữ liệu mới"**) |
| **Điều khiển** | `POST /api/mute`, `POST /api/ptz` | **400**, **501**, **502**, **503** | 400: *Hướng xoay phải là 'left', 'right', 'up' hoặc 'down'.* 502: *Không kết nối được tới camera để điều khiển PTZ (…). Kiểm tra camera đã bật, đúng địa chỉ, và đã đặt POSTURE_ONVIF_PASSWORD.* 501: *Camera không hỗ trợ PTZ (không điều khiển được hướng xoay).* Banner lỗi có nút **Gửi lại** phát lại đúng lệnh vừa hỏng |
| **Giọng đọc** | `GET /api/voice`, `POST /api/voice` | **503**, **400** | 503: *Loa cảnh báo chưa được bật trong phiên chạy này nên chưa đổi được giọng đọc. Kiểm tra mục 'speaker_alert' và 'camera.speaker' trong config.yaml.* 400: câu của server **đã kèm danh sách giọng hợp lệ** (`nam`, `nu`, `espeak`) |
| **Kết nối** | `GET /api/status` (qua `checkConnection`) | 200 nhưng thân không giống `/api/status` ⇒ báo sai | *Không kết nối được tới máy chủ. Kiểm tra: điện thoại và máy chủ có cùng mạng LAN, địa chỉ IP đúng, và chương trình dashboard đang chạy.* |

> **Không có `POST /api/session`.** Gọi vào đó nhận **405** kèm thân **HTML**
> (không phải JSON). App dùng đúng `GET` + `/api/session/start` + `/api/session/stop`.
> Ngược lại, **404 nằm trong tiền tố `/api/`** vẫn là JSON `{"ok": false, "message": …}`
> (`app.py`), còn 404 **ngoài** `/api/` là HTML — client phải chịu được cả hai.

### 5.2. Ghi chú trung thực về tab Giọng đọc

**Giọng đọc.** Route `/api/voice` đã có thật và trả đúng hợp đồng (đo bằng
`create_app()` + `test_client`):

- `GET` → `ok`, `available`, `voice`, `volume`, `speed`,
  `voices{ma: {label, dir, clips, ready, missing}}`,
  `fallbacks{loại_câu: "<câu tiếng Việt>"}`, `error`.
  Đo thực tế: `voices` có `nam`/`nu`/`espeak`, cả ba `ready: true`, `missing: []`.
- `POST` nhận `{"voice": "nam"|"nu"|"espeak"}` → 200 kèm báo cáo mới; giọng lạ
  → 400; chưa nối loa → 503.

**Phần app của tab này đang được hoàn thiện.** Hai lỗi mà phản biện vòng 2 tìm
ra là có thật trong bản trước:

1. App đọc **sai hình dạng** `fallbacks`. Server trả
   `{loại_câu → CÂU TIẾNG VIỆT}` (ví dụ
   *"Chưa có bản thu giọng nữ cho câu này nên tạm dùng giọng máy."*), app lại
   coi mỗi value là **mã giọng**, nên in câu rác ngay vị trí danh sách tên
   giọng.
2. Nút **Thử lại** chỉ tải lại `GET /api/voice`, **không** gửi lại
   `POST /api/voice` — người dùng tưởng đã đổi giọng.

Bản sửa cho cả hai đã nằm trong mã hiện tại: `normalizeVoice()` tách
`fallbackKinds` (KEY) khỏi `fallbackNote` (value, hiện nguyên văn), cảnh báo
thiếu bản thu đọc từ `voices[ma].missing`/`ready`; `VoiceScreen` lưu
`lastVoice` nên nút **Gửi lại** phát lại đúng lệnh. Kiểm chứng đã chạy:

```powershell
cd E:\2026\DUT\IOT\Cuoiki\apps\mobile
npm run verify
```

→ **10/10 PASS**, gồm các bài *"hiện nguyên văn câu server gửi trong
`fallbacks`"*, *"chip Thiếu bản thu theo `missing` của TỪNG giọng"*, và *"bấm
Gửi lại GỬI LẠI lệnh đổi giọng, không phải chỉ tải lại"*. Bộ kiểm này **nằm
trong repo** (`apps/mobile/test/ui/`, cần `npm install`), tái lập được.

**Trạng thái đúng của tab này:** bản sửa **đã qua phản biện vòng 3 với verdict
`pass`** (cả ba finding vòng 2 đều đóng) và **vẫn CHƯA chạy trên iPhone thật**.
Ba điều dưới đây vì vậy **chưa** được xác nhận và không được suy ra từ tài liệu
này:

- chưa ai bấm thử nút **Chọn** / **Gửi lại** bằng ngón tay trên thiết bị iOS;
- bố cục 7 tab trên màn hình thật (nhãn tự thu nhỏ) chưa được nhìn bằng mắt;
- phản hồi của loa camera sau khi đổi giọng chưa được nghe.

Cách đổi giọng **chắc chắn nhất** khi chưa có thiết bị để kiểm: dùng dashboard
web (thẻ "Giọng đọc") hoặc gọi thẳng route:

```powershell
$ip = '192.168.1.50'
curl.exe -s -X POST -H "Content-Type: application/json" -d '{\"voice\":\"nu\"}' `
  "http://${ip}:8000/api/voice"
```

**Camera.** Lỗi cũ "dừng tự thử lại sau ~4 giây khi gặp 503" **đã được sửa**
trong mã: `afterFrameFailure()` trong `framePolicy.ts` **không** cộng `503` vào
`MAX_AUTO_RETRY` và **không** đặt `stopReason = 'exhausted'`, nên app tiếp tục
tải ảnh khi camera còn khởi động chậm. Điều **đã** kiểm: test logic
`framePolicy`/`client` xanh (139 bài, chạy được cả khi chưa `npm install`),
`tsc --noEmit` exit 0, `npx expo export --platform ios` build được bundle
1,18 MB. Điều **chưa** kiểm: **chưa ai chạy tab này trên iPhone thật**.

---

## 6. Xác nhận lỗi "quay lại bàn học" đã hết — hai kịch bản người dùng tự thử

Chỉ có ý nghĩa **sau khi** dashboard chạy bằng bản `src/posture_monitor/pose.py`
mới nhất (bản có nhánh bám lại track id + cổng liên tục vị trí). Cách chắc chắn
nhất:

```powershell
git log --oneline -1
Select-String -Path src\posture_monitor\pose.py -Pattern 'REACQUIRE_MIN_IOU|_box_is_continuous'
```

Phải thấy cả hai hằng số/cổng trên. Nếu không thấy, bạn đang chạy bản cũ — mọi
kết quả bên dưới không nói gì về bản sửa.

Chuẩn bị chung cho cả hai kịch bản: chạy dashboard có ghi log (§1.4), bấm
**Bắt đầu học** trên dashboard, ngồi vào khung hình bình thường, chờ 5 giây cho
presence ổn định.

### Kịch bản (i) — ngồi học một mình, đứng dậy đi ra

1. Ngồi học, không có ai khác trong khung. Xác nhận ảnh camera **có skeleton**
   (xương màu xanh lá) và dashboard hiện "Tư thế tốt"/"Không thấy người" đúng lúc.
2. Đứng dậy, đi ra khỏi khung.
3. **Mong đợi:** loa báo *"Bạn ơi, quay lại bàn học nhé"* sau khoảng **3–5 giây**
   (presence chuyển "vắng" ở mốc `presence.absent_grace_s = 3,0` giây; cảnh báo
   chỉ phát khi đã vắng **liên tục** ≥ `schedule.kinds.leave_frame.hold_s = 5,0`
   giây). Câu này **được nhắc lại mỗi ~2 giây** trong khi bạn còn vắng
   (`cooldown_s: 2`) — đó là thiết kế, không phải lỗi.
4. Quay lại ngồi vào bàn.
5. **Mong đợi:** **im ngay** sau khung hình đầu tiên thấy bạn; skeleton hiện
   lại; log có dòng `Thấy người trở lại trong khung sau … giây vắng.` và
   **không** còn dòng `SPEAK_OK: đã phát cảnh báo 'leave_frame'` nào nữa.
6. Nếu loa vẫn nhắc tiếp **sau khi** bạn đã ngồi lại trong khung ≥ 2 giây:
   đó là lỗi, ghi lại giờ và gửi kèm `run.log`.

### Kịch bản (ii) — ngồi học mà CÓ NGƯỜI KHÁC trong khung, rồi bạn đứng dậy

Đây là kịch bản **quan trọng nhất**, vì nó chính là lỗi mà phản biện tìm ra:
bản bám lại đầu tiên lấy "hộp lớn nhất trong khung", nên khi bạn rời bàn mà còn
người khác, khoá track **nhảy sang người kia** và hệ thống **không bao giờ** báo
vắng — tính năng "nhắc quay lại bàn học" chết hẳn.

1. Mời một người ngồi/đứng trong khung, ở **chỗ khác hẳn** chỗ bạn ngồi (ví dụ
   người kia ngồi ở mép bàn bên kia, hoặc đứng cách xa một bước). Bạn vẫn là
   người đang được theo dõi.
2. Xác nhận ảnh có skeleton của **bạn**, và presence đang "Đang trong khung hình".
3. Bạn đứng dậy, đi ra khỏi khung. Người kia **vẫn ở trong khung**.
4. **Mong đợi:** loa **VẪN phải báo** *"Bạn ơi, quay lại bàn học nhé"* sau
   khoảng 3–5 giây, và dashboard/app chuyển "Không thấy người"/"Không thấy ai".
5. **Nếu loa KHÔNG báo** trong khi người kia vẫn trong khung: **đó là lỗi F1
   chưa được sửa hết** — báo lại cho nhóm phát triển, kèm `run.log` và mô tả
   vị trí hai người trong khung. Không tự sửa bằng cách tắt `tracking`.
6. Quay lại ngồi: loa phải im, skeleton của bạn hiện lại.

> **Vì sao phải "chỗ khác hẳn":** bản sửa chỉ bám lại track id khi hộp mới còn
> **liên tục về vị trí** với hộp của bạn ở khung trước (IoU ≥ 0,1 **hoặc** tâm
> dịch ≤ 0,5 lần cạnh dài hộp trước). Hai người ngồi sát nhau tới mức hộp chồng
> lấn nhiều thì hộp người kia vẫn "giống" hộp của bạn, hệ thống coi là cùng một
> người và **cố ý** không báo vắng. Đó là hành vi đã thiết kế, và các ngưỡng
> 0,1 / 0,5 đều **chưa hiệu chuẩn** trên camera thật (§9c) — nên hãy thử ở
> khoảng cách rõ ràng trước, rồi mới thử ca sát nhau.

### 6.1. Đọc log để xác nhận (không phải nghe bằng tai)

```powershell
Select-String -Path run.log -Pattern 'Thấy người trở lại trong khung'
Select-String -Path run.log -Pattern 'Không thấy người trong khung liên tục'
Select-String -Path run.log -Pattern 'báo vắng mặt'
Select-String -Path run.log -Pattern 'bám lại track id'
Select-String -Path run.log -Pattern 'nhả khoá để chọn người khác'
Select-String -Path run.log -Pattern "SPEAK_OK: đã phát cảnh báo 'leave_frame'"
Select-String -Path run.log -Pattern 'Bỏ cảnh báo'
```

Muốn biết log có **lặp vô ích** hay không, đếm số lần loa phát câu nhắc, rồi
so với số lần người quay lại:

```powershell
(Select-String -Path run.log -Pattern "SPEAK_OK: đã phát cảnh báo 'leave_frame'").Count
(Select-String -Path run.log -Pattern 'Thấy người trở lại trong khung').Count
```

Hai con số này **đều tăng** trong một buổi thử bình thường (mỗi lần bạn ra rồi
vào là một lần mỗi bên). Chỉ khi số lần phát lớn hơn hẳn số lần quay lại —
hoặc tăng trong lúc bạn **không** rời khỏi khung — mới là lỗi.

Ý nghĩa từng dòng (đều là chuỗi có thật trong mã):

| Dòng log | Nguồn | Nói điều gì |
|---|---|---|
| `Thấy người trở lại trong khung sau X giây vắng.` | `presence.py` | presence vừa chuyển từ vắng → có mặt. Chỉ ghi khi **đổi** trạng thái |
| `Không thấy người trong khung liên tục X giây; báo vắng mặt.` | `presence.py` | vắng đủ `presence.absent_grace_s` (3,0 s) |
| `Track id N mất khỏi khung nhưng còn người: bám lại track id M …` | `pose.py` | **bản sửa đang hoạt động**: id đổi nhưng người vẫn trong khung, đã bám lại ngay |
| `Track id N vắng quá X giây; nhả khoá để chọn người khác.` | `pose.py` | hết `timing.absent_reset_s` (120 s) mới nhả khoá — nếu dòng này xuất hiện trong lúc bạn còn ngồi, có gì đó sai |
| `SPEAK_OK: đã phát cảnh báo 'leave_frame' ra loa camera.` | `__main__.py` | loa **đã** phát câu nhắc |
| `Bỏ cảnh báo '…': <lý do>` | `speaker_alert.py` | quyết định có nhưng bị chặn (tắt tiếng, loa bận…) |

Cách đọc nhanh một lần thử đúng: **một** dòng `bám lại track id` khi id đổi,
**không** có dòng `nhả khoá` khi bạn vẫn ngồi, và cụm `SPEAK_OK … leave_frame`
**dừng** ngay sau dòng `Thấy người trở lại`.

### 6.2. Xác nhận skeleton trên ảnh

- Trên dashboard web: khung camera phải có xương xanh lá khi bạn ở trong hình.
- Trên app: tab **Camera** hiển thị đúng khung đó (cùng nguồn `/api/frame`).
- Không có điện thoại trong tay: lưu một khung ra tệp rồi mở xem —

```powershell
$env:PYTHONPATH = 'src'
python -m posture_monitor run --config config.yaml --no-gpio --save-overlay frame.jpg
```

`--save-overlay` lưu **một** khung đã vẽ rồi thoát và in ra hai dòng:
`Đã lưu khung đã vẽ: <đường dẫn>` và `persons=<N>`. Cách đọc:

- `persons=0` ⇒ lúc chụp **không** có người trong khung. Lệnh vẫn trả mã thoát
  0 và đây là trạng thái hợp lệ, không phải lỗi code — nhưng nó **không** dùng
  để kiểm skeleton được, hãy chạy lại khi bạn đã ngồi vào khung.
- `persons>=1` mà ảnh **không** có xương ⇒ vấn đề nằm ở pose/overlay, không ở
  web/app.

---

## 7. Chạy test của bản sửa (bắt buộc dùng `-p tmpmode` + `--basetemp`)

> **Quy ước này có một nguồn sự thật duy nhất:**
> [`docs/TESTING_ON_WINDOWS_SANDBOX.md`](TESTING_ON_WINDOWS_SANDBOX.md). Đọc mục 1
> và mục 2 của tài liệu đó trước khi viết hay chạy bất kỳ lệnh pytest nào. Mục
> dưới đây chỉ là bản tóm tắt cho tiện, **không** thay thế tài liệu kia.

Trên Windows, sandbox của máy dự án chặn thư mục do pytest tạo bằng
`mkdir(mode=0o700)`; pytest luôn dùng mode đó cho fixture `tmp_path`, nên các
bài dùng `tmp_path` sẽ lỗi `PermissionError [WinError 5]` — **lỗi môi trường,
không phải lỗi sản phẩm**. Vì vậy **mọi** lệnh pytest chạm tệp có `tmp_path`
trong tài liệu này đều kèm plugin vá mode + `--basetemp` trỏ vào workspace:

```
$env:PYTHONPATH="src;.scratch\plug"; python -m pytest <files> `
  -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\btN"
```

Ba điều dễ làm sai, đều đã gây lỗi thật trong dự án này:

1. **`--basetemp` phải là thư mục MỚI** trong `.scratch/` (đổi `N` mỗi lần).
   Dùng lại basetemp do lần chạy trước tạo bằng `0o700` thì vẫn lỗi.
2. **Không chạy `pytest` trần**, kể cả để "xem nhanh": một lần như vậy đã xoá
   thư mục tạm riêng của sandbox và làm mọi lệnh `pwsh` sau đó hỏng.
3. Plugin phải vá **cả ba** chỗ (`os.mkdir`, `pathlib.Path.mkdir`,
   `os.makedirs`). Chỉ vá `pathlib.Path.mkdir` thì
   `tempfile.TemporaryDirectory()` vẫn lỗi.

Nội dung `.scratch/plug/tmpmode.py` (đã bị `.gitignore` chặn nên **không** vào
repo) ghi nguyên văn ở
[`TESTING_ON_WINDOWS_SANDBOX.md` §2](TESTING_ON_WINDOWS_SANDBOX.md). Nó chỉ đổi
`mode` khi tạo thư mục — **không** chạm mã sản phẩm, không bỏ bài nào, không đổi
assert nào.

Ba tệp test lõi của bản sửa pose (không có `tmp_path`, nhưng vẫn truyền
`--basetemp` theo quy ước số 2 ở trên):

```powershell
cd E:\2026\DUT\IOT\Cuoiki
$env:PYTHONPATH = "src;.scratch\plug"
python -m pytest tests/test_pose.py tests/test_presence.py `
  tests/test_pose_track_reacquire.py `
  -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt-docs1"
```

Đo được (2026-11-12): **59 passed, 1 skipped, exit 0**. Bài `skipped` là bài
tích hợp cần trọng số thật `yolo11n-pose.pt` + `bus.jpg` — tự `pytest.skip` khi
thiếu, không liên quan bản sửa.

Route `/api/frame`:

```powershell
$env:PYTHONPATH = "src;.scratch\plug"
python -m pytest tests/test_web_frame.py `
  -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt-docs2"
```

Đo được: **21 passed, exit 0**.

Cộng thêm `tests/test_web.py` (tệp này **có** `tmp_path`, nên plugin là bắt buộc):

```powershell
$env:PYTHONPATH = "src;.scratch\plug"
python -m pytest tests/test_web_frame.py tests/test_web.py `
  -q -p tmpmode -p no:cacheprovider --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt-docs3"
```

Đo được: **69 passed, exit 0**.

Toàn bộ suite:

```powershell
cd E:\2026\DUT\IOT\Cuoiki
$env:PYTHONPATH = "src;.scratch\plug"
python -m pytest tests/ -q -p tmpmode -p no:cacheprovider `
  --basetemp="E:\2026\DUT\IOT\Cuoiki\.scratch\bt-docs-full"
```

Đo được: **1544 passed, 4 skipped, exit 0** (hai lần chạy trong phiên này: 163 s
và 107 s — thời gian phụ thuộc tải máy).

### 7.1. Hai bài test trong `tests/test_pose.py` đã được cập nhật kịch bản

Nói trung thực để người đọc không bị bất ngờ khi xem `git diff`: **không bài
test nào bị xoá**, nhưng **hai bài** đã được viết lại kịch bản vì bản sửa đổi
hành vi. Lý do nằm ngay trong docstring của từng bài:

| Bài | Vì sao phải đổi |
|---|---|
| `test_detect_returns_none_while_track_temporarily_absent` | Kịch bản cũ (khung 8×8, một hộp 200×200 mang id 9) đòi `detect()` trả `None`, tức nó **khoá chính hành vi lỗi** cần sửa. Nay dùng khung thật 640×480 + hộp rác 3×3: vẫn phải trả `None` và không cướp khoá. **Bắt buộc đổi.** |
| `test_detect_releases_track_after_absent_reset` | Assert cũ vẫn đúng, nhưng với hộp 200×200 (lớn hơn cả khung 8×8 — dữ liệu không thể có từ camera thật) thì bản sửa **bám lại ngay**, nên bài mang tên "nhả khoá sau `absent_reset_s`" mà thật ra kiểm đường **bám lại**. Đổi sang khung 640×480 + hộp 3×3 để đi đúng nhánh nhả khoá. **Nhẹ hơn bài trên.** |

Bài `skipped` duy nhất trong toàn bộ suite là bài tích hợp cần trọng số thật,
không liên quan bản sửa.

Test app — **hai tầng**, đừng lẫn:

```powershell
cd E:\2026\DUT\IOT\Cuoiki\apps\mobile
npm test        # 139 bài logic thuần, KHÔNG cần npm install
npm run verify  # 10 bài giao diện thật trong jsdom, CẦN npm install
node node_modules\typescript\bin\tsc --noEmit
```

Đo được: `npm test` **139 passed, exit 0**; `npm run verify` **10/10 passed,
exit 0**; `tsc --noEmit` **exit 0**. Tầng `npm test` chỉ chạy module thuần
(không `import react-native`), nên nó **không** chứng minh màn hình render
đúng. Tầng `npm run verify` dựng app React Native thật trong jsdom rồi bấm nút —
mạnh hơn, nhưng vẫn **không** phải thiết bị thật: nó không kiểm ATS, không kiểm
`<Image>` với `data:` URI trên iOS, không kiểm cỡ chữ trên màn hình retina.

Build thử bundle iOS (chỉ chạy được **sau** `npm install`):

```powershell
cd E:\2026\DUT\IOT\Cuoiki\apps\mobile
npm install           # nếu chưa có node_modules
npx tsc --noEmit
npx expo export --platform ios --no-bytecode --max-workers 1 `
  --output-dir "E:\2026\DUT\IOT\Cuoiki\.scratch\dist-ios"
```

Đo được trên máy dự án (2026-11-12, `npm install --offline` → 764 gói): `tsc`
**exit 0**, bundle **1,18 MB**, exit 0. Đây là bằng chứng **mọi import phân
giải được** và Metro đóng gói thành công — không phải bằng chứng app chạy trên
máy thật.

> **`node_modules` không nằm trong git** (`apps/mobile/.gitignore` chặn). Ai
> clone repo cũng phải tự chạy `npm install` trước khi `npm run verify`,
> `npx tsc --noEmit` hay `npx expo export` chạy được. Chỉ `npm test` là chạy
> được khi chưa cài gói.

> Dùng `--output-dir` để bundle không rơi vào `apps/mobile/dist/` (đã gitignore,
> nhưng để trong `.scratch/` thì dọn một chỗ là xong). Thêm
> `--no-bytecode --max-workers 1` để tránh bước Hermes `spawn` — bước đó có thể
> lỗi `EPERM` trong môi trường bị hạn chế quyền.

---

## 8. Sự cố thường gặp

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| App báo *Không kết nối được tới máy chủ* ngay lập tức | Nhập `localhost`/`127.0.0.1`; khác LAN; tường lửa chặn 8000 | Mở Safari **trên chính iPhone**: `http://<ip-lan>:8000/api/status`. Được ⇒ lỗi ở app (địa chỉ/ATS). Không được ⇒ lỗi mạng/tường lửa |
| Safari mở được, app không | ATS hoặc quyền Local Network | Xem §4. Bấm **Cho phép** khi iOS hỏi quyền Local Network |
| *Project is incompatible with this version of Expo Go* | `expo` trong `package.json` khác SDK của Expo Go | Xem SDK trong Expo Go, sửa `package.json`, `npx expo install --fix` |
| Tab Camera: *Máy chủ chưa có route ảnh* (404) | Tiến trình dashboard **đang chạy** là bản cũ, chưa có `GET /api/frame` | Khởi động lại `posture_monitor run` bằng mã hiện tại rồi bấm **Thử lại** |
| Tab Camera: *Xem trực tiếp đang tắt* (403) | `web.stream_enabled: false` | Đặt `true` trong `config.yaml`, khởi động lại dashboard |
| Tab Camera: *Chưa có khung hình* (503) | Vòng lặp chưa đặt khung đầu tiên (camera RTSP cần vài giây) | Chờ; app tự thử lại mỗi 2 giây. Quá 30 giây ⇒ kiểm tra camera + log `run` |
| Tab Phiên học: *Phiên học chưa được bật…* (503) | Dashboard chạy không có `StudySession` | Chạy đúng lệnh `run`; app không gọi sai route |
| Tab Tín hiệu: *Tính năng người học chưa được bật…* (503) | `people` là `None` trong lần chạy (mục `face` tắt / dịch vụ người học lỗi) | Bật mục `face` trong `config.yaml` |
| Tab Điều khiển: 502 khi bấm PTZ | Không kết nối được tới camera ONVIF | Đặt `POSTURE_CAMERA_SOURCE` dạng `rtsp://…` hoặc `POSTURE_ONVIF_PASSWORD` |
| Tab Giọng đọc hiện câu lạ / nút Gửi lại không đổi giọng | Lỗi đã biết của bản app cũ (đọc sai `fallbacks`) — bản hiện tại đã sửa, xem §5.2 | Cập nhật `apps/mobile` mới nhất; nếu vẫn sai, dùng dashboard web hoặc gọi `POST /api/voice` bằng `curl.exe` |
| Ảnh đứng yên | Camera không đẩy khung mới | Xem log `run`; app vẫn tải lại mỗi 2 giây và có nhãn "Ảnh cuối lúc …" |
| Loa nhắc "quay lại bàn học" dù đang ngồi | Bản `pose.py` cũ (khoá track id kẹt 120 s) | Dùng bản mới (§6), rồi thử lại hai kịch bản |

---

## 9. Điều CHƯA kiểm chứng

Danh sách này là **bắt buộc đọc** trước khi kết luận "đã chạy đúng":

**(a) Chưa chạy app trên iPhone / Expo Go thật.** Không có thiết bị iOS trong
phiên làm việc. Máy dev là Windows: không có Xcode, không có `xcodebuild`,
không có iOS Simulator. Bằng chứng hiện có chỉ là: test logic Node (139 bài),
test giao diện trong jsdom (10 bài), `tsc --noEmit` exit 0, và
`npx expo export --platform ios` build được bundle 1,18 MB. **Không** có phép đo
nào về thời gian tải ảnh, cỡ chữ trên màn hình thật, hay luồng quét QR.

**(b) ATS với `http://` chưa kiểm chứng, và `ios.infoPlist` KHÔNG có tác dụng
trong Expo Go.** `app.json` có đặt `NSAllowsLocalNetworking: true`, nhưng trong
Expo Go `Info.plist` là của **Expo Go**, không phải của project — nên khoá đó
chỉ có hiệu lực ở dev build/prebuild, và dev build iOS không làm được trên
Windows. Không khẳng định `http://<ip-lan>:8000` bị chặn hay được cho qua.

**(c) `REACQUIRE_MIN_FRAME_RATIO` và `FRAME_WAIT_S` chưa hiệu chuẩn.** Hai ngưỡng
này nằm trong mã (`pose.py`, `web/app.py`) và docstring của chúng tự ghi
"**CHƯA đo trên dữ liệu thật**". Cùng nhóm: `REACQUIRE_MAX_ASPECT_RATIO = 4.0`,
`REACQUIRE_MAX_CENTER_SHIFT_RATIO = 0.5`, `REACQUIRE_MIN_IOU = 0.1`. Chưa có
phép đo nào trên Pi/camera thật; mọi con số hiện có đều từ khung tổng hợp và
model giả.

**(d) Bản sửa `pose.py` chưa chạy với model pose thật.** Vì vậy **chưa ai xác
nhận** BotSORT có thực sự đổi track id trong cảnh của người dùng hay không, và
chưa ai xác nhận cổng liên tục vị trí (IoU/dịch tâm) không chặn oan khi người
học cúi xuống hoặc xê dịch ghế. Bản sửa vẫn đúng kể cả khi giả thuyết "BotSORT
đổi id" là sai — một lần đổi id từng gây lỗi tự kéo dài 120 giây.

Ngoài bốn mục trên, **chưa** kiểm chứng: kết nối app ↔ Pi thật qua LAN trong
điều kiện mạng của bạn; quyền "Local Network" của iOS; tường lửa của router;
`npx expo install --fix` / `npx expo-doctor` (không chạy được trong sandbox vì
chặn ghi `~/.expo`); phát âm thực tế của loa camera; và toàn bộ phần **bấm tay
trên thiết bị** của mọi tab (bố cục 7 tab nhãn tự thu nhỏ, `focus` khi chuyển
tab, thời gian tải ảnh thật qua Wi-Fi). Màn **Giọng đọc** đã qua phản biện
vòng 3 (`pass`) nhưng những gì đã kiểm đều là test trong jsdom, không phải
thiết bị — xem §5.2.

**(e) Bán kính "lọt" của cổng liên tục vị trí — con số cần biết khi hiệu chuẩn.**
Cổng `_box_is_continuous` cho phép bám lại khi IoU ≥ 0,1 **hoặc** tâm dịch
≤ 0,5 × cạnh dài hộp trước. Đo trên khung tổng hợp: người khác đứng cách tâm
hộp cũ **≤ 180 px** mới bị bám nhầm (khi đó IoU đã là 0,89 — tức hai hộp gần
như trùng nhau); người **ngồi cạnh, dịch 200 px thì bị chặn** đúng như thiết kế.
Hệ quả thực tế: nếu hai người ngồi chen nhau tới mức hai hộp gần trùng, hệ thống
coi là cùng một người và **không** báo vắng — đó là hành vi đã thiết kế, không
phải lỗi. Con số 180 px phụ thuộc kích thước hộp (tức phụ thuộc khoảng cách tới
camera), nên **phải đo lại** trên camera thật của bạn trước khi coi là đã
hiệu chuẩn — cùng nhóm với mục (c).

### 9.1. Hạn chế đã biết — chưa xử lý (ghi lại, không trình bày như đã sửa)

Ba điểm dưới đây do phản biện vòng 3 ghi nhận. Đều **không** chặn dùng và
**không** phải lỗi nghiệp vụ, nhưng phải biết để không hiểu sai hành vi:

| Mã | Mức | Nội dung | Ảnh hưởng tới người dùng |
|---|---|---|---|
| **M1** | medium | Bộ khung test giao diện (`apps/mobile/test/ui/env.mjs`) chỉ gom `console.error` **trong lúc mount** rồi trả lại ngay, nên lỗi React phát sinh lúc `click()`/`wait()` **không** vào `ui.errors`. **9/10** bài `npm run verify` dựa vào `ui.errors` (đếm lại từng bài: `cameraScreen.test.mjs` dòng 89/112/133 và `voiceScreen.test.mjs` dòng 78/92/112/138/180/209), tức chốt chặn chống hồi quy đang hở ở gần như toàn bộ bộ test giao diện. Con số "6/10" trong báo cáo cũ của vòng phản biện là đếm thiếu; xem `docs/KNOWN_LIMITATIONS_AND_NEXT_STEPS.md` §1. | Không ảnh hưởng app đang chạy. Ảnh hưởng **chất lượng test**: một lỗi React mới có thể lọt qua `npm run verify` trong khi vẫn in ra stderr. Khi chạy verify, đừng chỉ đọc số PASS — đọc cả stderr. |
| **M2** | low | `VoiceScreen.tsx` vẽ khối "Còn câu phải mượn giọng khác" chỉ dựa vào `fallbackCount > 0`, **không** xét `available`. Nếu server gửi `fallbacks` trong khi loa chưa nối, app hiện **đồng thời** "Loa cảnh báo chưa bật" và "Còn câu phải mượn giọng khác". | Hai khối thông tin cùng lúc, không crash. Tổ hợp này chưa được test phủ. Gặp thì hiểu là: câu sau **không** áp dụng khi loa chưa nối. |
| **M3** | low | `/api/voice` chưa có `ROUTE_HINTS` trong `errors.ts`, nên 503/400 rơi về câu chung **khi server không gửi `message`**. | Server thật hiện **luôn** gửi `message` (đã đo), nên gần như không gặp. Chỉ thấy câu chung nếu chạy sau một reverse proxy nuốt thân lỗi. |

Ba mục này **không** được sửa trong tài liệu này (ngoài phạm vi), và **không**
được coi là đã xử lý.

---

## 10. Tài liệu liên quan

- [`apps/mobile/README.md`](../apps/mobile/README.md) — app, cấu trúc, giới hạn.
- [`docs/REQUIREMENTS_MOBILE_AND_PRESENCE_FIX.md`](REQUIREMENTS_MOBILE_AND_PRESENCE_FIX.md) — hợp đồng API và tiêu chí nghiệm thu.
- [`docs/VERIFICATION_MOBILE_AND_PRESENCE_FIX.md`](VERIFICATION_MOBILE_AND_PRESENCE_FIX.md) — kết quả kiểm định độc lập (lệnh verify, phân loại lỗi môi trường).
- [`docs/TESTING_ON_WINDOWS_SANDBOX.md`](TESTING_ON_WINDOWS_SANDBOX.md) — vì sao phải dùng `-p tmpmode` + `--basetemp`.
- [`docs/WEB_DASHBOARD.md`](WEB_DASHBOARD.md) — dashboard web, SQLite, PTZ.
