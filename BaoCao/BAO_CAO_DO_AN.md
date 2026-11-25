---
university: "TRƯỜNG ĐẠI HỌC BÁCH KHOA"
faculty: "KHOA CÔNG NGHỆ THÔNG TIN"
report_type: "BÁO CÁO"
course_title: "Đồ án Học phần: Internet Vạn Vật (IoT)"
project_title: "Hệ thống giám sát học tập trên Raspberry Pi 4 kết hợp Camera IP và Ứng dụng di động"
advisor: "TS. [Cập nhật tên Giảng viên hướng dẫn]"
location_date: "ĐÀ NẴNG, 11/2026"
header_text: "Báo cáo Đồ án IoT: Hệ thống giám sát học tập trên Raspberry Pi 4"
footer_students: "Phan Gia Bảo"
students:
  - name: "Phan Gia Bảo"
    class_code: "22.10A"
    student_id: "102220265"
---

## CHƯƠNG 1. GIỚI THIỆU BÀI TOÁN VÀ MỤC TIÊU NGHIÊN CỨU

### 1.1. Mở đầu

Sự phổ biến của hình thức tự học tại nhà và học trực tuyến cá nhân đặt ra bài toán duy trì sự tập trung liên tục trong suốt một phiên học kéo dài từ 45 đến 90 phút. Trong không gian bàn học cá nhân, các yếu tố gây xao nhãng diễn ra thường xuyên và lặp đi lặp lại, bao gồm việc tự ý rời khỏi khu vực bàn học giữa chừng, cầm điện thoại di động để giải trí trong giờ học, hoặc trường hợp người khác ngồi thay vào vị trí của người đã đăng ký học. Các công cụ hẹn giờ truyền thống trên máy tính hoặc điện thoại chỉ theo dõi thời gian trôi qua trên đồng hồ mà hoàn toàn không nhận biết được trạng thái hiện diện thực tế cũng như hành vi vật lý của người học trước mặt bàn.

Ngược lại, các giải pháp giám sát sử dụng dịch vụ thị giác máy tính trên đám mây (Cloud AI) đòi hỏi truyền liên tục luồng hình ảnh riêng tư của phòng học cá nhân ra mạng Internet bên ngoài, làm phát sinh chi phí băng thông, độ trễ mạng khó kiểm soát và đặc biệt là rủi ro xâm phạm dữ liệu cá nhân nhạy cảm. Sự trưởng thành của các bộ vi xử lý nhúng tiết kiệm điện như Raspberry Pi 4 kết hợp cùng khung suy luận mạng nơ-ron tối ưu cho kiến trúc ARM (như NCNN và ONNX Runtime tích hợp trong OpenCV) mở ra hướng tiếp cận khả thi hơn: thực thi toàn bộ chuỗi nhận thức thị giác ngay trên thiết bị biên đặt trong mạng nội bộ (LAN), phát cảnh báo tức thì qua loa của chính camera IP và cung cấp giao diện theo dõi đồng thời trên cả trình duyệt web lẫn ứng dụng di động mà không lưu trữ bất kỳ bức ảnh thô nào ra đĩa.

Từ định hướng đó, đề tài tập trung nghiên cứu, thiết kế và hiện thực hóa **Hệ thống giám sát học tập trên Raspberry Pi 4 kết hợp Camera IP và Ứng dụng di động**. Báo cáo này trình bày có hệ thống từ cơ sở bài toán, kiến trúc phân tầng một chiều, luồng thu nhận dữ liệu biên, các module suy luận AI và hậu xử lý hình học, tầng giao tiếp phần cứng RTSP/ONVIF/GPIO, giao diện Web Dashboard và ứng dụng React Native/Expo cho đến phương pháp kiểm thử tự động và quy trình kiểm chứng trung thực số liệu thực nghiệm.

### 1.2. Bối cảnh thực tiễn tại không gian tự học cá nhân

Trong bối cảnh học tập tại góc học tập gia đình hoặc ký túc xá, thiết bị quan sát phù hợp nhất là một camera IP phổ thông gắn cố định ở góc trước mặt bàn sao cho trường nhìn bao quát đồng thời phần thân trên của người ngồi và mặt bàn học. Quá trình vận hành thực tế của một phiên tự học đặt ra các nhu cầu cụ thể về nhận diện trạng thái, phản hồi âm thanh tại chỗ, điều khiển từ xa trên điện thoại và bảo vệ quyền riêng tư dữ liệu. Bảng 1 tổng hợp các nhu cầu thực tiễn này cùng hướng giải quyết kỹ thuật tương ứng được lựa chọn trong đề tài.

*Bảng 1. Nhu cầu thực tiễn trong giám sát tự học và hướng xử lý tương ứng của đề tài*

| STT | Nhu cầu thực tiễn tại bàn học | Hạn chế của cách tiếp cận thông thường | Hướng xử lý kỹ thuật trong đề tài |
|---|---|---|---|
| 1 | Phát hiện người học rời khỏi bàn quá thời gian cho phép | Cảm biến hồng ngoại thụ động (PIR) dễ báo sai khi người ngồi yên ít cử động | Ước lượng khung xương 17 điểm bằng YOLO11n-pose và kiểm tra nhóm 7 keypoint thân trên kèm thời gian ân hạn 3,0 giây |
| 2 | Phát hiện hành vi cầm và sử dụng điện thoại trong phiên học | Chỉ tìm hộp bao điện thoại sẽ báo nhầm khi điện thoại nằm yên trên mặt bàn hoặc nhầm gọng kính là điện thoại | Kết hợp YOLO11n detect (lớp `cell phone`), khoảng cách cổ tay chuẩn hóa theo bề rộng vai và ba bộ lọc hình học chống báo nhầm |
| 3 | Xác thực đúng danh tính người đã đăng ký phiên học | Nhị phân hóa kết quả nhận diện (đúng/sai) gây báo động giả liên tục khi người học cúi đầu, che mặt hoặc ngược sáng | Phân tách ba trạng thái danh tính (`MATCH`, `MISMATCH`, `UNKNOWN`) với cặp mô hình YuNet + SFace trên OpenCV |
| 4 | Nhắc nhở tức thì mà không cần gắn thêm loa rời phức tạp | Loa nối dây qua cổng âm thanh của bo mạch nhúng đòi hỏi khuếch đại nguồn riêng và đi dây rườm rà | Tận dụng trực tiếp loa tích hợp trên camera IP thông qua giao thức RTSP backchannel chuẩn G.711 PCMA 8 kHz |
| 5 | Bật/dừng phiên học và quan sát nhanh ngay tại bàn | Phải mở máy tính cá nhân và trình duyệt web mỗi lần muốn bắt đầu học hoặc xoay góc camera | Phát triển đồng bộ Web Dashboard nội bộ và Ứng dụng di động React Native/Expo hiển thị trực tiếp camera cùng 3 tín hiệu người học |
| 6 | Đảm bảo tuyệt đối quyền riêng tư trong không gian phòng riêng | Lưu ảnh chụp vi phạm hoặc đẩy luồng video lên máy chủ đám mây tiềm ẩn nguy cơ rò rỉ hình ảnh cá nhân | Xử lý khung hình hoàn toàn trên RAM thiết bị biên, không gọi hàm ghi ảnh ra đĩa, chỉ lưu số liệu thống kê SQLite và vector đặc trưng 128 chiều |

Bảng 1 cho thấy bài toán giám sát học tập cá nhân không thể giải quyết trọn vẹn chỉ bằng việc gọi một mô hình học sâu đơn lẻ, mà đòi hỏi sự phối hợp chặt chẽ giữa mô hình nhận thức, bộ luật hình học - thời gian, giao thức điều khiển thiết bị mạng và kiến trúc phần mềm bảo toàn quyền riêng tư.

### 1.3. Phát biểu bài toán

Xét hệ thống gồm một người ngồi học một mình trước bàn học dưới góc quan sát của một camera IP hỗ trợ giao thức RTSP và ONVIF trong cùng mạng LAN với bo mạch Raspberry Pi 4. Khi và chỉ khi người học chủ động kích hoạt một phiên học hợp lệ, hệ thống phải liên tục tiếp nhận luồng khung hình trực tiếp và trả lời ba câu hỏi nghiệp vụ cốt lõi theo chu kỳ vài giây một lần:

1. **Bài toán hiện diện (`Presence`):** Người đang học có còn hiện diện thực sự trong khung hình quan sát của camera hay đã rời khỏi bàn học?
2. **Bài toán sử dụng điện thoại (`Phone Use`):** Người đang học có đang cầm hoặc thao tác với điện thoại di động trong tay hay không?
3. **Bài toán danh tính người học (`Learner Identity`):** Khuôn mặt của người đang ngồi tại bàn có khớp với hồ sơ sinh trắc học của người đã đăng ký học hay là một người khác ngồi thay?

Khi một trong ba câu trả lời rơi vào trạng thái vi phạm và duy trì liên tục vượt quá ngưỡng thời gian giữ (`hold time`) tương ứng nhằm loại trừ nhiễu tức thời, hệ thống phải thực hiện đồng thời ba tác vụ đầu ra: (1) phát thông điệp nhắc nhở bằng tiếng Việt có thứ tự ưu tiên ra loa của camera IP, (2) cập nhật trạng thái trực quan kèm độ tươi của tín hiệu lên Web Dashboard và Ứng dụng di động trong mạng LAN, và (3) ghi nhận sự kiện vi phạm vào cơ sở dữ liệu cục bộ SQLite để phục vụ tra cứu lịch sử.

### 1.4. Lý do chọn hướng tiếp cận AI thị giác máy tính trên thiết bị biên

Để giải quyết bài toán nêu trên, đề tài lựa chọn kiến trúc xử lý thị giác máy tính cục bộ trên thiết bị biên (Edge AI) thay vì kiến trúc xử lý tập trung trên đám mây hoặc mạng cảm biến đeo người. Hình 1 minh họa bức tranh tổng thể bốn tầng vật lý và logic của hệ thống được xây dựng trong đề tài.

![Kiến trúc tổng thể hệ thống](figures/01-kien-truc-tong-the.png)

*Hình 1. Kiến trúc tổng thể bốn tầng của hệ thống giám sát học tập trên Raspberry Pi 4*

Quan sát Hình 1, quyết định đặt toàn bộ tầng nhận thức AI trên bo mạch Raspberry Pi 4 kết nối trực tiếp với camera IP qua mạng LAN xuất phát từ bốn cơ sở kỹ thuật rõ ràng:

- **Thứ nhất, bảo vệ dữ liệu hình ảnh ngay từ kiến trúc vật lý:** Toàn bộ khung hình giải mã từ camera chỉ tồn tại ngắn hạn trong bộ nhớ RAM của Raspberry Pi 4 để trích xuất tọa độ khớp xương, hộp bao vật thể và vector đặc trưng khuôn mặt rồi bị giải phóng ngay trong vòng lặp. Không có bất kỳ gói tin hình ảnh nào đi ra ngoài cổng định tuyến Internet.
- **Thứ hai, kiểm soát độ trễ vòng kín tại chỗ:** Từ thời điểm camera thu hình qua RTSP đến khi Raspberry Pi phát gói âm thanh RTP/PCMA ngược trở lại loa camera hoàn toàn diễn ra trong mạng nội bộ một bước nhảy (`single-hop LAN`), loại bỏ sự phụ thuộc vào chất lượng đường truyền Internet bên ngoài.
- **Thứ ba, tận dụng hiệu quả các mô hình pretrained gọn nhẹ:** Các tác vụ ước lượng tư thế người (`person pose`), phát hiện điện thoại (`cell phone` trong tập COCO) và trích xuất đặc trưng khuôn mặt đều đã có sẵn các mô hình pretrained chất lượng cao (YOLO11n-pose, YOLO11n, YuNet, SFace). Khi chuyển đổi sang định dạng NCNN và ONNX ở độ phân giải đầu vào hợp lý (`imgsz = 320`), CPU bốn nhân Cortex-A72 không cần GPU rời vẫn đủ khả năng vận hành nếu được lập lịch chu kỳ suy luận thông minh.
- **Thứ tư, tách biệt rõ nguồn sự thật duy nhất và đa giao diện hiển thị:** Việc đặt máy chủ Flask ngay trên Raspberry Pi giúp cả trình duyệt máy tính lẫn ứng dụng di động Expo Go chỉ đóng vai trò khách hàng HTTP mỏng (`thin HTTP client`), không phải nhân đôi logic suy luận AI trên điện thoại của người dùng.

### 1.5. Mục tiêu nghiên cứu

Mục tiêu tổng quát của đề tài là xây dựng hoàn chỉnh một hệ thống IoT biên hoạt động ổn định đầu-cuối trên phần cứng Raspberry Pi 4 thật, kết hợp đa mô hình thị giác máy tính pretrained, điều khiển ngoại vi camera mạng và giao diện giám sát đa nền tảng, đồng thời thiết lập chuẩn mực kiểm thử và truy xuất nguồn gốc số liệu nghiêm ngặt. Các mục tiêu kỹ thuật cụ thể được hệ thống hóa trong Bảng 2.

*Bảng 2. Mục tiêu nghiên cứu cụ thể và phương thức hiện thực hóa trong đề tài*

| Mã mục tiêu | Nội dung mục tiêu kỹ thuật | Phương thức hiện thực hóa trong hệ thống |
|---|---|---|
| **MT1** | Chạy ổn định trên Raspberry Pi 4 Model B không có bộ tăng tốc GPU | Sử dụng 4 mô hình pretrained chuyển sang định dạng NCNN (`imgsz = 320`) và ONNX; phân tách chu kỳ chạy giữa các mô hình để tiết kiệm ngân sách CPU |
| **MT2** | Không huấn luyện lại trọng số mạng nơ-ron khi thêm người học mới | Thực hiện quy trình đăng ký 5 góc mặt trực tiếp trên camera để trích xuất và chuẩn hóa L2 các vector đặc trưng 128 chiều, tự suy ngưỡng cosine an toàn |
| **MT3** | Cam kết không lưu trữ hình ảnh và bảo vệ thông tin nhạy cảm | Cấm tuyệt đối thao tác ghi ảnh ra đĩa trong mã nguồn; áp dụng bộ lọc `scrub_biometrics` trên toàn bộ API JSON và tự động che mật khẩu trong URL RTSP |
| **MT4** | Ngoại vi hóa toàn bộ ngưỡng thuật toán và tái cấu trúc mã nguồn sạch | Tập trung mọi tham số vào `config.yaml` kiểm tra kiểu chặt chẽ; tổ chức mã nguồn thành 9 phân hệ Python một chiều không phụ thuộc vòng (`circular import`) |
| **MT5** | Tích hợp trọn vẹn cảnh báo loa camera, điều khiển PTZ và GPIO | Giao tiếp RTSP backchannel (cổng 554) để phát giọng đọc tiếng Việt, giao thức ONVIF HTTP (cổng 80) để xoay camera 4 hướng và thư viện `gpiozero` cho đèn/còi phụ trợ |
| **MT6** | Xây dựng giao diện Web offline-first và Ứng dụng di động đồng bộ | Cung cấp Dashboard Web thuần không phụ thuộc CDN và ứng dụng React Native/Expo SDK 58 (*Nocturne Telemetry*) gộp luồng camera cùng 3 tín hiệu người học ngay trên màn hình chính |
| **MT7** | Đảm bảo khả năng kiểm chứng độc lập bằng kiểm thử tự động và nhãn số liệu | Xây dựng 1.662 bài kiểm thử Python và 189 bài kiểm thử Mobile chạy độc lập phần cứng; gắn nhãn `ĐÃ ĐO`, `TÍNH TỪ ĐO`, `CHƯA ĐO` cho mọi chỉ số hiệu năng |

Các mục tiêu trong Bảng 2 đóng vai trò kim chỉ nam xuyên suốt quá trình thiết kế kiến trúc ở Chương 2 cũng như đối chiếu nghiệm thu thực nghiệm ở Chương 9.

### 1.6. Phạm vi nghiên cứu và giới hạn của hệ thống

Để đảm bảo tính khả thi và độ sâu kỹ thuật trong khuôn khổ đồ án học phần Internet Vạn Vật, phạm vi của hệ thống được xác định tường minh theo hai ranh giới trong phạm vi và ngoài phạm vi như sau.

**Các chức năng nằm trong phạm vi thực hiện:**
- Thu nhận luồng video thời gian thực từ camera IP qua RTSP (hỗ trợ mở rộng nguồn USB camera, Pi Camera hoặc tệp video phát lại phục vụ kiểm thử).
- Nhận diện trạng thái có mặt hoặc vắng mặt của một người học được chọn trong khung hình.
- Phát hiện hành vi cầm sử dụng điện thoại di động bằng sự kết hợp giữa hộp bao đối tượng và tọa độ cổ tay người học.
- Đăng ký người học mới qua 5 tư thế khuôn mặt, chọn người đang học và xác thực danh tính định kỳ trong suốt phiên học.
- Quản lý công tắc phiên học thủ công kết hợp lịch học theo tuần (cổng điều kiện hai lớp) làm điều kiện duy nhất kích hoạt chuỗi suy luận cảnh báo.
- Phát âm thanh cảnh báo tiếng Việt (giọng người thu sẵn, giọng tổng hợp `espeak-ng` hoặc âm bíp dự phòng) trực tiếp ra loa camera IP; điều khiển xoay PTZ bốn hướng và xuất tín hiệu trạng thái ra cụm đèn LED/còi GPIO.
- Phục vụ Web Dashboard tiếng Việt trong mạng LAN và Ứng dụng di động React Native/Expo Go kết nối qua 10 endpoint HTTP dùng chung, kèm lưu trữ nhật ký phiên học và vi phạm trên SQLite.

**Các vấn đề chủ động đặt ngoài phạm vi đồ án:**
- Không nhận diện các hành vi vi mô phức tạp khác như ngủ gật nhắm mắt, nói chuyện riêng hay quay cóp tài liệu giấy.
- Không xây dựng hệ thống chấm điểm thi đua, xếp hạng hay đồng bộ báo cáo qua đám mây Internet.
- Không huấn luyện lại (`fine-tune`) các mô hình phát hiện vật thể hoặc nhận diện khuôn mặt trên tập dữ liệu tự gán nhãn mới.
- Không triển khai thuật toán chống giả mạo khuôn mặt (`face anti-spoofing` trước ảnh in hoặc video phát lại trên màn hình khác); hạn chế này được ghi nhận công khai là rủi ro đã biết của hệ thống.
- Không giám sát đồng thời nhiều người học trong cùng một phiên mà chỉ khóa theo dõi một người học mục tiêu tại một thời điểm.

### 1.7. Các thách thức kỹ thuật cốt lõi

Quá trình đưa bốn mô hình thị giác máy tính cùng giao thức truyền thông đa phương tiện lên một bo mạch nhúng không GPU đặt ra năm thách thức kỹ thuật cốt lõi mà đề tài phải giải quyết:

1. **Giới hạn ngân sách thời gian trên CPU ARM bốn nhân:** Một lượt suy luận YOLO11n-pose ở kích thước `320` đã tiêu tốn trung bình hơn `100 ms` trên Raspberry Pi 4, chưa tính chi phí đọc giải mã khung hình HEVC (`~66 ms`), phát hiện điện thoại (`~98,6 ms`) và nhận diện khuôn mặt (`~86,1 ms`). Nếu chạy đồng loạt cả bốn mô hình trên mọi khung hình, tốc độ hệ thống sẽ sụt xuống dưới `2,5 FPS`, làm mất tính phản hồi thời gian thực.
2. **Hiện tượng phình bộ đệm RTSP làm trôi độ trễ theo thời gian:** Camera IP phát luồng phụ ở tốc độ `20 fps` trong khi vòng lặp AI tiêu thụ chậm hơn nhiều (`~4-5 fps`). Cơ chế đệm mặc định của FFmpeg/OpenCV khiến mỗi lệnh đọc thông thường trả về khung hình cũ nhất trong hàng đợi, dẫn đến độ trễ hình ảnh tăng tuyến tính lên hàng chục giây chỉ sau vài phút vận hành.
3. **Sự chồng lấn phổ điểm tin cậy gây báo nhầm điện thoại:** Ở góc quay từ phía trước bàn học, mô hình YOLO11n pretrained trên tập COCO thường xuyên nhận nhầm gọng kính cận trên mặt người học thành lớp `cell phone` với độ tin cậy trùng lấp dải điểm thấp của chiếc điện thoại thật bị bàn tay che khuất một phần, khiến mọi cách chọn ngưỡng `conf_threshold` tĩnh đơn thuần đều thất bại.
4. **Xung đột đồng bộ đa luồng giữa vòng lặp thị giác, máy chủ Web và SQLite:** Vòng lặp camera chạy liên tục ở luồng chính trong khi nhiều khách hàng trình duyệt và ứng dụng di động truy vấn trạng thái, đọc luồng MJPEG, gọi loa backchannel và truy vấn lịch sử vi phạm ở các luồng worker khác nhau. Thiết kế khóa không khéo sẽ làm treo vòng lặp đọc camera hoặc gây lỗi truy cập SQLite xuyên luồng.
5. **Tính minh bạch của số liệu kỹ thuật trước nguy cơ suy diễn chủ quan:** Khi hệ thống có nhiều cấu hình chạy khác nhau (ảnh tĩnh, khung tổng hợp, pipeline chỉ pose, pipeline đa mô hình), việc trộn lẫn độ trễ suy luận thuần với tốc độ toàn tuyến rất dễ tạo ra các con số FPS ảo không phản ánh thực tế phần cứng.

### 1.8. Đóng góp chính của đề tài

Trên cơ sở giải quyết trực tiếp các thách thức nêu trên, đề tài mang lại năm đóng góp kỹ thuật cụ thể:

- **Kiến trúc phần mềm biên 9 phân hệ một chiều và cơ chế khe hẹp `DashboardState`:** Tổ chức toàn bộ gói `src/posture_monitor/` theo đồ thị phụ thuộc một chiều nghiêm ngặt, tách rời tuyệt đối vòng lặp nhận thức khỏi tầng giao tiếp Flask/Mobile, cho phép kiểm thử tự động `1.662` kịch bản Python và `189` kịch bản Mobile ngay trên máy tính cá nhân không cần gắn camera hay bo mạch Pi.
- **Chiến lược lập lịch đa chu kỳ và bộ lọc hình học dựa trên phép đo thực tế:** Kết hợp chu kỳ chạy phân tầng (pose mỗi khung, detect điện thoại cách khung có thời hạn sống `TTL`, nhận diện mặt mỗi `2,0 giây`) với quy tắc khoảng cách cổ tay chuẩn hóa theo bề rộng vai và bộ lọc vị trí tương đối so với đường vai, triệt tiêu hiện tượng báo nhầm gọng kính mà vẫn giữ được các trường hợp cầm điện thoại thật.
- **Cơ chế xác thực danh tính ba trạng thái bảo toàn quyền riêng tư:** Thiết kế bộ phân loại `MATCH / MISMATCH / UNKNOWN` ưu tiên tránh kết tội oan khi thiếu sáng hoặc che mặt, kết hợp quy trình quét 5 tư thế tự suy ngưỡng và cam kết không lưu ảnh thô ở mọi tầng hệ thống.
- **Tích hợp đồng bộ phần cứng camera mạng và giao diện di động Nocturne Telemetry:** Hiện thực hóa trọn vẹn kênh âm thanh ngược RTSP backchannel PCMA 8 kHz có ba tầng dự phòng giọng đọc, điều khiển ONVIF PTZ an toàn và ứng dụng di động React Native/Expo SDK 58 hợp nhất khung hình trực tiếp với cụm 3 tín hiệu người học Bento 2+1 ngay trên một màn hình duy nhất.
- **Thiết lập quy ước bằng chứng ba nhãn và hàng rào kiểm thử chống tái phát số liệu sai:** Xây dựng hệ thống nhãn `ĐÃ ĐO`, `TÍNH TỪ ĐO`, `CHƯA ĐO` đi kèm các bài kiểm thử tự động kiểm soát tính nhất quán giữa mã nguồn, tệp cấu hình và tài liệu kỹ thuật.

### 1.9. Kết chương

Chương 1 đã xác lập bối cảnh thực tiễn, phát biểu chính xác ba câu hỏi cốt lõi của bài toán giám sát phiên học cá nhân, đồng thời làm rõ lý do lựa chọn hướng tiếp cận AI thị giác máy tính trên thiết bị biên Raspberry Pi 4 thay vì phụ thuộc vào hạ tầng đám mây. Phạm vi chức năng, các ranh giới loại trừ có chủ đích và năm thách thức kỹ thuật từ ngân sách CPU, độ trễ đệm RTSP đến chống báo nhầm hình học cũng đã được định hình rõ ràng.

Trên cơ sở các mục tiêu và ràng buộc đã đặt ra, Chương 2 tiếp theo sẽ trình bày chi tiết kiến trúc tổng thể bốn tầng của hệ thống, bản đồ chín phân hệ mã nguồn một chiều, luồng xử lý dữ liệu đầu-cuối, thiết kế trạng thái chia sẻ của tầng dịch vụ và các thông số môi trường phần cứng thực nghiệm.

## CHƯƠNG 2. KIẾN TRÚC HỆ THỐNG VÀ THIẾT KẾ KỸ THUẬT TỔNG THỂ

### 2.1. Mục tiêu kiến trúc hệ thống

Kiến trúc tổng thể của hệ thống giám sát học tập được thiết kế xoay quanh bốn nguyên lý bất biến nhằm đảm bảo khả năng vận hành bền bỉ trên thiết bị nhúng tài nguyên hạn chế và khả năng bảo trì, kiểm thử lâu dài:

1. **Nguyên lý khung hình mới nhất, không xếp hàng chờ (`Latest-frame, Zero-queueing`):** Luồng thu nhận camera luôn ghi đè khung hình mới nhất lên vùng đệm một phần tử thay vì đẩy vào hàng đợi FIFO. Nhờ đó, dù tốc độ suy luận của CPU có dao động tạm thời, độ trễ giữa hiện thực vật lý và kết luận của mô hình không bao giờ tích lũy tăng dần theo thời gian chạy.
2. **Nguyên lý một khe hẹp duy nhất giữa vòng lặp nhận thức và giao diện (`Single Narrow Waist`):** Đối tượng `DashboardState` có khóa luồng (`threading.Lock`) đóng vai trò cầu nối dữ liệu duy nhất giữa luồng xử lý camera và máy chủ web Flask. Vòng lặp thị giác tuyệt đối không phụ thuộc thư viện web, và các endpoint HTTP tuyệt đối không chạm trực tiếp vào phần cứng camera hay mô hình học sâu.
3. **Nguyên lý không tồn tại dữ liệu ảnh trên bộ nhớ ngoài (`Zero Disk Image Footprint`):** Mọi khung hình BGR và JPEG chỉ lưu chuyển trong bộ nhớ khả biến (RAM); cơ sở dữ liệu SQLite chỉ ghi nhận dấu thời gian cùng nhãn sự kiện, còn kho danh tính chỉ lưu các vector số thực đã chuẩn hóa.
4. **Nguyên lý suy giảm nhẹ nhàng khi gặp sự cố ngoại vi (`Graceful Degradation`):** Sự vắng mặt của chân GPIO trên máy tính phát triển, mất kết nối tạm thời tới camera RTSP, thiếu công cụ `ffmpeg` chuyển mã âm thanh hay thiếu tệp trọng số tùy chọn đều được bắt giữ rõ ràng, chuyển sang chế độ giả lập hoặc nhánh dự phòng kèm thông báo tiếng Việt cụ thể thay vì làm sập toàn bộ tiến trình.

### 2.2. Kiến trúc tổng quan bốn tầng và bản đồ phân hệ một chiều

Ở góc độ triển khai mã nguồn, toàn bộ hệ thống backend Python được đóng gói chuẩn hóa thông qua tệp `pyproject.toml` dưới không gian tên `src/posture_monitor/`, tách biệt hoàn toàn với thư mục trọng số `models/`, thư mục ứng dụng di động `apps/mobile/` và mười thư mục kiểm thử trong `tests/`. Để ngăn chặn triệt để lỗi phụ thuộc vòng vốn rất phổ biến trong các dự án tích hợp AI và phần cứng, gói `posture_monitor` được phân rã thành **chín phân hệ có hướng phụ thuộc một chiều từ trên xuống dưới**, như minh họa tại Hình 2.

![Bản đồ phân hệ một chiều](figures/08-ban-do-module.png)

*Hình 2. Bản đồ chín phân hệ một chiều trong `src/posture_monitor/`, ứng dụng di động và cấu trúc kiểm thử đối xứng*

Hình 2 thể hiện rõ sự phân tách trách nhiệm giữa tầng nền tảng, tầng giao tiếp vào/ra, tầng thị giác, tầng nghiệp vụ miền, tầng cảnh báo, tầng dịch vụ web và tầng lắp ráp dòng lệnh. Trách nhiệm cụ thể và quy tắc nhập (`import`) bắt buộc của từng phân hệ được quy định chi tiết trong Bảng 3.

*Bảng 3. Chức năng và quy tắc phụ thuộc một chiều của chín phân hệ trong gói `src/posture_monitor/`*

| STT | Phân hệ | Các mô-đun thành phần chính | Trách nhiệm kỹ thuật cốt lõi | Quy tắc phụ thuộc bắt buộc |
|---|---|---|---|---|
| 1 | `core/` | `config_models`, `config_parsers`, `config`, `labels`, `atomic_io`, `credentials`, `log_buffer`, `logging_setup` | Định nghĩa cấu trúc cấu hình kiểu mạnh, hằng số nhãn hệ thống, ghi tệp nguyên tử có `fsync`, che mật khẩu RTSP và bộ đệm nhật ký vòng | Tầng đáy cùng: không phụ thuộc bất kỳ phân hệ nội bộ nào khác |
| 2 | `camera/` | `capture`, `control`, `audio` | Quản lý nguồn đọc khung hình tự kết nối lại, điều khiển xoay ONVIF PTZ và đóng gói luồng âm thanh RTP/PCMA qua RTSP backchannel | Chỉ được phép phụ thuộc phân hệ `core/` |
| 3 | `hardware/` | `gpio_base`, `gpio_real`, `gpio_mock`, `sensors` | Trừu tượng hóa điều khiển đèn LED, còi buzzer, mô-tơ rung qua `gpiozero` và đọc cảm biến khoảng cách siêu âm HC-SR04 | Chỉ được phép phụ thuộc phân hệ `core/` |
| 4 | `storage/` | `sqlite_store` | Quản lý cơ sở dữ liệu SQLite chế độ `WAL`, gom lô giao dịch 10 giây, dọn dẹp dữ liệu quá hạn và đóng phiên mồ côi | Chỉ được phép phụ thuộc phân hệ `core/` |
| 5 | `vision/` | `yolo_loader`, `pose`, `phone_detector`, `phone`, `faces`, `features`, `calibration`, `classifier`, `overlay` | Cung cấp lớp nạp `YoloModelMixin`, suy luận khung xương, phát hiện điện thoại, nhận diện khuôn mặt YuNet/SFace, tính đặc trưng hình học và vẽ lớp phủ | Chỉ được phép phụ thuộc phân hệ `core/` |
| 6 | `domain/` | `presence`, `study_session`, `schedule`, `state`, `enrollment`, `signal_board`, `people_service` | Xử lý quy tắc nghiệp vụ thuần: xác định hiện diện, cổng phiên học - lịch học, máy trạng thái giữ/hysteresis, quy trình quét 5 tư thế mặt và bảng hợp nhất 3 tín hiệu | Chỉ phụ thuộc `vision/` và `core/`; hoàn toàn độc lập phần cứng và web |
| 7 | `alerts/` | `speaker_alert`, `espeak_synth`, `voice_library`, `gpio_dispatcher` | Điều phối thứ tự ưu tiên cảnh báo âm thanh, tổng hợp giọng đọc tiếng Việt và đồng bộ trạng thái đèn/còi ngoại vi | Phụ thuộc `camera/`, `hardware/`, `domain/` và `core/` |
| 8 | `web/` | `app`, `context`, `state`, `streaming`, `privacy`, `routes/{core,diagnostics,session,media,people}` | Phục vụ máy chủ Flask, quản lý `DashboardState`, phát luồng MJPEG, lọc sinh trắc học và cung cấp 24 endpoint HTTP cho Web/Mobile | Phụ thuộc `domain/`, `storage/`, `core/`; cấm mở camera hay nạp mô hình trực tiếp |
| 9 | `cli/` | `parser`, `monitor_runner`, `dashboard_host`, `cmd_run`, `cmd_calibrate`, `cmd_replay`, `cmd_speak_test`, `benchmark/` | Phân tích tham số dòng lệnh, khởi tạo toàn bộ đối tượng thật hoặc giả lập và tiêm phụ thuộc (`Dependency Injection`) vào vòng lặp chạy | Tầng đỉnh lắp ráp: kết nối toàn bộ các phân hệ bên dưới |

Cấu trúc phân tầng tại Bảng 3 giải thích vì sao toàn bộ nghiệp vụ cốt lõi trong `vision/` và `domain/` có thể kiểm thử đơn vị với tốc độ tính bằng mili-giây: chúng là các hàm và lớp thuần túy nhận dữ liệu mảng số hoặc dấu thời gian truyền từ ngoài vào mà không bị ràng buộc với trình điều khiển phần cứng hay khung ứng dụng web.

### 2.3. Luồng xử lý dữ liệu từ camera RTSP đến giao diện đa nền tảng

Trong suốt thời gian hệ thống vận hành, một khung hình đi từ cảm biến quang học của camera IP tới kết luận cảnh báo và giao diện người dùng trải qua một chuỗi bảy bước tuần tự có kiểm soát chu kỳ. Hình 3 minh họa sự phối hợp ba nhánh suy luận chạy ở ba tần số khác nhau trước khi hội tụ về bảng tín hiệu trung tâm.

![Luồng xử lý một khung hình](figures/02-luong-xu-ly-ai.png)

*Hình 3. Luồng xử lý một khung hình với ba chu kỳ mô hình khác nhau hợp nhất thành ba tín hiệu nghiệp vụ*

Chi tiết đầu vào, xử lý kỹ thuật, đầu ra và tần suất thực thi của từng bước trên đường ống dữ liệu đầu-cuối được mô tả cụ thể trong Bảng 4.

*Bảng 4. Đặc tả từng bước trong luồng xử lý dữ liệu thời gian thực từ camera đến người dùng*

| Bước | Khâu xử lý | Phân hệ đảm nhiệm | Xử lý kỹ thuật chính | Đầu ra dữ liệu | Tần suất thực thi |
|---|---|---|---|---|---|
| **B1** | Thu nhận và xả đệm khung hình | `camera/capture.py` | Luồng nền đọc RTSP sub-stream `704×576`, xả các khung cũ bằng vòng lặp `grab()` ngưỡng `30 ms` và giải mã khung mới nhất | Mảng ảnh `ndarray` BGR kích thước `576×704×3` trên RAM | Liên tục ở luồng nền (`20 fps` nguồn) |
| **B2** | Nhận diện khuôn mặt định kỳ | `vision/faces.py` · `domain/people_service.py` | Phát hiện mặt bằng YuNet, căn chỉnh `112×112`, trích vector SFace 128 chiều và so khớp cosine với kho `faces.json` | Kết quả `MATCH`, `MISMATCH` hoặc `UNKNOWN` cập nhật vào `SignalBoard` | Mỗi `2,0 giây` (cả trong và ngoài phiên học) |
| **B3** | Kiểm tra cổng phiên học hai lớp | `domain/study_session.py` · `domain/schedule.py` | Kiểm tra hội hai điều kiện: phiên học đang ở trạng thái `running` và thời gian hệ thống nằm trong khung giờ cho phép | Cờ boolean `session_active`; nếu `False` thì bỏ qua B4-B6 để tiết kiệm CPU | Mỗi vòng lặp chính (`~5 Hz` mục tiêu) |
| **B4** | Ước lượng khung xương và hiện diện | `vision/pose.py` · `domain/presence.py` | Chạy YOLO11n-pose NCNN (`imgsz = 320`), khóa đối tượng theo `track id` và kiểm tra số keypoint thân trên hợp lệ | Cấu trúc `PoseResult` (17 điểm) và tín hiệu `co_mat` / `vang_mat` | Mỗi khung hình khi `session_active = True` |
| **B5** | Phát hiện sử dụng điện thoại | `vision/phone_detector.py` · `vision/phone.py` | Chạy YOLO11n detect cách khung, lọc hộp giả bằng đường vai, tính khoảng cách Euclid từ cổ tay tới hộp còn hạn `TTL` | Tín hiệu `khong` / `dang_dung` sau bộ đếm giữ `1,0 giây` | Suy luận `1/2 khung`; kiểm tra chạm mỗi khung |
| **B6** | Quyết định cảnh báo và lưu trữ | `alerts/speaker_alert.py` · `storage/sqlite_store.py` | Xét thứ tự ưu tiên vi phạm, kiểm tra `cooldown`, phát âm thanh RTP/PCMA ra loa camera (nếu không tắt tiếng) và đẩy sự kiện vào hàng đợi SQLite | Âm thanh trên loa camera IP, tín hiệu LED GPIO và bản ghi bảng `events` | Khi vi phạm vượt ngưỡng giữ (`hold_s`) |
| **B7** | Xuất bản trạng thái và luồng hình | `web/state.py` · `web/routes/*` | Vẽ lớp phủ hộp bao/khớp xương, mã hóa JPEG vào `DashboardState` và trả JSON/MJPEG cho Web Dashboard cùng App di động | Luồng `/stream`, ảnh `/api/frame` và JSON trên `/api/signals`, `/api/status` | Cập nhật RAM mỗi vòng; khách hàng hỏi mỗi `0,3-2,0 s` |

Sự phân tách rõ ràng giữa bước B2 và khối B4-B6 trong Bảng 4 là một điểm nhấn thiết kế quan trọng: khi người học chưa bấm bắt đầu phiên học, hệ thống tự động nghỉ chạy hai mô hình nặng nhất (YOLO11n-pose và YOLO11n detect) giúp CPU mát và tiết kiệm điện năng, nhưng vẫn duy trì luồng hình ảnh và nhận diện khuôn mặt thưa mỗi `2,0 giây` để giao diện hiển thị sẵn tên người đang ngồi trước bàn.

### 2.4. Vai trò và lịch trình điều phối của bốn mô hình AI trong hệ thống

Hệ thống sử dụng kết hợp bốn tệp trọng số mạng nơ-ron sâu, tất cả đều là các mô hình đã huấn luyện sẵn (`pretrained`) và được chuyển đổi sang định dạng thực thi tối ưu cho CPU ARM64 mà không yêu cầu huấn luyện lại. Bảng 5 tổng hợp vai trò, định dạng lưu trữ và chu kỳ điều phối của từng mô hình.

*Bảng 5. Tổng hợp bốn mô hình AI pretrained và chiến lược lập lịch trên thiết bị biên*

| Tên mô hình | Đường dẫn tệp trong `models/` | Kích thước tệp | Định dạng suy luận | Vai trò trong đường ống nhận thức | Chu kỳ gọi suy luận |
|---|---|---|---|---|---|
| **YOLO11n-pose** | `yolo11n-pose.pt` -> `yolo11n-pose_ncnn_model/` | `6,26 MB` -> `11,5 MB` | PyTorch xuất sang **NCNN** | Phát hiện lớp `person` duy nhất, trả hộp bao người và tọa độ 17 khớp xương chuẩn COCO | **Mỗi khung hình** (trong phiên học) |
| **YOLO11n detect** | `yolo11n.pt` -> `yolo11n_ncnn_model/` | `5,61 MB` -> `10,5 MB` | PyTorch xuất sang **NCNN** | Phát hiện vật thể 80 lớp COCO, trích lọc riêng lớp `67` (`cell phone`) trên bàn và tay người học | **Cách khung (`1/2` khung)** kèm `box_ttl_s = 0,5 s` |
| **YuNet** | `models/yunet.onnx` | `232.589 B` (`227 KB`) | **ONNX** (`cv2.FaceDetectorYN`) | Phát hiện vị trí khuôn mặt và trích xuất 5 điểm mốc sinh trắc (hai mắt, mũi, hai khóe miệng) | **Mỗi `2,0 giây`** |
| **SFace** | `models/sface.onnx` | `38.696.353 B` (`36,9 MB`) | **ONNX** (`cv2.FaceRecognizerSF`) | Căn chỉnh ảnh mặt về `112×112` và ánh xạ thành vector đặc trưng chuẩn hóa 128 chiều | **Mỗi `2,0 giây`** (chỉ chạy khi YuNet thấy mặt hợp lệ) |

Việc lựa chọn ba chu kỳ khác nhau trong Bảng 5 hoàn toàn dựa trên đặc tính vật lý của từng loại tín hiệu và chi phí tính toán đo được thực tế trên Raspberry Pi 4: tọa độ cổ tay và thân trên thay đổi nhanh theo từng cử động nên cần cập nhật ở mọi khung hình; chiếc điện thoại di chuyển chậm hơn trong phạm vi bàn tay nên có thể nội suy vị trí hộp bao qua hai khung liên tiếp; trong khi danh tính của người ngồi trước bàn là đại lượng bán tĩnh, việc kiểm tra lại sau mỗi `2,0 giây` (tiêu tốn khoảng `86,1 ms`) vừa đủ phát hiện hành vi đổi người vừa chỉ chiếm chưa tới `4,5%` quỹ thời gian thực.

### 2.5. Thiết kế tầng dịch vụ Web Backend và Ứng dụng di động

Tầng giao tiếp người dùng được thiết kế theo mô hình một máy chủ nội bộ phục vụ đồng thời hai loại giao diện khách hàng độc lập: trình duyệt Web (trên máy tính hoặc điện thoại) và ứng dụng di động gốc React Native chạy qua Expo Go. Máy chủ Flask `3.1.3` được khởi chạy trong một luồng daemon cùng tiến trình với `MonitorRunner`, giao tiếp thông qua đối tượng ngữ cảnh `WebContext` và kho trạng thái chia sẻ `DashboardState`.

Cấu trúc trao đổi này đảm bảo sự đồng nhất tuyệt đối về mặt dữ liệu: cả giao diện Web lẫn ứng dụng di động đều đọc chung các endpoint tiêu chuẩn (`/api/status`, `/api/signals`, `/api/session`, `/api/voice`, `/api/violations`, `/stream`, `/api/frame`) và gửi lệnh điều khiển qua cùng các endpoint tác động (`/api/mute`, `/api/ptz`, `/api/session/start`, `/api/session/stop`). Khi người dùng bấm tắt tiếng cảnh báo trên điện thoại, giao diện trình duyệt trên máy tính tự động cập nhật trạng thái tắt tiếng ở ngay chu kỳ hỏi kế tiếp sau `1-2 giây` mà không cần bất kỳ kênh đồng bộ phức tạp nào khác.

### 2.6. Thiết kế lưu trữ dữ liệu SQLite, kho đặc trưng khuôn mặt và quyền riêng tư

Hệ thống phân tách lưu trữ bền vững trên thẻ nhớ microSD thành hai nhóm tệp gọn nhẹ trong thư mục `data/`:

- **Cơ sở dữ liệu quan hệ `SQLite` (`data/posture.db`):** Lưu trữ ba bảng gồm `sessions` (quản lý thời điểm mở và đóng phiên học), `events` (ghi nhận các sự kiện cảnh báo rời khung, dùng điện thoại, sai người học hoặc kết quả phát loa) và `minute_stats` (tổng hợp thống kê theo từng phút). Cơ sở dữ liệu vận hành ở chế độ nhật ký ghi trước (`journal_mode = WAL`) kết hợp cơ chế gom lô giao dịch mỗi `10 giây`, vừa cho phép tầng Web truy vấn lịch sử song song không khóa luồng ghi, vừa giảm thiểu số chu kỳ xóa/ghi vật lý giúp kéo dài tuổi thọ thẻ nhớ.
- **Kho dữ liệu cấu hình JSON nguyên tử (`data/faces.json`, `data/face_threshold.json`, `data/audio/voice.json`):** Mọi thao tác cập nhật tệp JSON đều đi qua mô-đun `core/atomic_io.py` theo quy trình ghi ra tệp tạm cùng thư mục, gọi lệnh đồng bộ đĩa `os.fsync()` rồi mới đổi tên nguyên tử (`os.replace()`), ngăn ngừa hoàn toàn nguy cơ hỏng tệp cấu hình nếu bo mạch bị rút nguồn đột ngột.

Về mặt bảo mật và quyền riêng tư, hệ thống áp dụng hai chốt chặn kỹ thuật cứng: toàn bộ phản hồi API liên quan đến danh sách người học đều đi qua hàm lọc đệ quy `scrub_biometrics()` (`web/privacy.py`) để tước bỏ mọi khóa mang tên `embedding`, `vector` hoặc `feature` trước khi đóng gói HTTP; đồng thời mô-đun `core/credentials.py` tự động quét và thay thế thông tin xác thực trong chuỗi `rtsp://user:pass@host` thành `***` trước khi xuất ra nhật ký hệ thống hay báo cáo đo kiểm.

### 2.7. Môi trường triển khai thực tế và quy ước minh bạch số liệu

Toàn bộ quá trình triển khai phần cứng và đo đạc thực nghiệm của đề tài được thực hiện trên bo mạch Raspberry Pi 4 thật kết nối camera IP trong mạng nội bộ. Để đảm bảo tính trung thực khoa học tuyệt đối: xuất phát từ bài học thực tế trong quá trình phát triển khi các con số suy đoán từng bị trộn lẫn với số đo phần cứng: báo cáo này áp dụng nghiêm ngặt quy ước phân loại ba nhãn bằng chứng cho mọi chỉ số hiệu năng, được định nghĩa tại Bảng 6.

*Bảng 6. Quy ước ba nhãn phân loại bằng chứng số liệu áp dụng xuyên suốt báo cáo*

| Nhãn phân loại | Định nghĩa nguồn gốc số liệu | Phạm vi sử dụng hợp lệ trong báo cáo |
|---|---|---|
| **ĐÃ ĐO** | Số liệu đo trực tiếp trên chính bo mạch Raspberry Pi 4 hoặc thiết bị thật của dự án, có lưu vết điều kiện đo và thời điểm thực hiện | Được phép dùng làm căn cứ thiết kế kiến trúc, chọn ngưỡng thuật toán và đối chiếu nghiệm thu |
| **TÍNH TỪ ĐO** | Giá trị dẫn xuất bằng phép tính đại số tường minh (cộng độ trễ, nghịch đảo chu kỳ, lấy trung bình) từ các con số **ĐÃ ĐO** | Dùng để phân tích ngân sách thời gian và lập kế hoạch tài nguyên, bắt buộc ghi kèm công thức tính |
| **CHƯA ĐO** | Hạng mục đã có mã nguồn hoặc công cụ đo nhưng chưa thực hiện bài đo hoàn chỉnh trên phần cứng đích | Chỉ dùng để nhận diện rủi ro và đề xuất hướng phát triển; nghiêm cấm dùng để kết luận đạt nghiệm thu |

Theo đúng quy ước tại Bảng 6, các thông số kỹ thuật của môi trường phần cứng và hệ điều hành triển khai thực tế của đề tài được ghi nhận đầy đủ trong Bảng 7.

*Bảng 7. Thông số môi trường phần cứng và hệ thống triển khai thực tế trên Raspberry Pi 4*

| Hạng mục kỹ thuật | Giá trị thực tế trên hệ thống đích | Nhãn bằng chứng |
|---|---|---|
| Bo mạch xử lý trung tâm | Raspberry Pi 4 Model B **Rev 1.5** | **ĐÃ ĐO** |
| Kiến trúc tập lệnh vi xử lý | ARMv8 `aarch64` (4 nhân Cortex-A72, hỗ trợ tập lệnh `crc32` / NEON) | **ĐÃ ĐO** |
| Dung lượng bộ nhớ RAM khả dụng | **3.795 MB** (phiên bản thương mại 4 GB LPDDR4) | **ĐÃ ĐO** |
| Dung lượng lưu trữ trống thời điểm đo | **7,6 GB** trên thẻ nhớ microSD | **ĐÃ ĐO** |
| Hệ điều hành và nhân Linux | Raspberry Pi OS **Trixie** (Debian 13), kernel `6.18.34+rpt-rpi-v8` | **ĐÃ ĐO** |
| Trình thông dịch và nhóm quyền người dùng | Python **3.13.5** · nhóm quyền `video`, `gpio`, `i2c`, `spi`, `dialout` | **ĐÃ ĐO** |
| Nguồn thu nhận hình ảnh chính | Camera IP mạng LAN, luồng phụ RTSP `/1/2` độ phân giải **704×576 @ 20 fps**, chuẩn nén **HEVC** | **ĐÃ ĐO** |
| Nhiệt độ CPU khi chạy tải 60 giây | Tăng từ **55,0 °C** lên **58,0 °C**, cực đại **58,9 °C** (thấp hơn nhiều ngưỡng hãm xung 80 °C) | **ĐÃ ĐO** |
| Cờ hãm xung nhịp và sụt áp nguồn | `vcgencmd get_throttled` = **`0x0`** tại mọi thời điểm lấy mẫu | **ĐÃ ĐO** |
| Mức tiêu thụ RAM đỉnh của tiến trình | **464,0 MiB** (trong bài chạy thực tế 60 giây của cấu hình pipeline chỉ pose) | **ĐÃ ĐO** |

Các thông số tại Bảng 7 xác nhận nền tảng phần cứng vận hành ở trạng thái nhiệt và nguồn điện hoàn toàn sạch (`throttled = 0x0`), đảm bảo các phép đo độ trễ mô hình ở các chương sau không bị sai lệch bởi hiện tượng tự động hạ xung nhịp của vi xử lý.

### 2.8. Kết chương

Chương 2 đã thiết lập khung kiến trúc tổng thể bốn tầng cùng bản đồ chín phân hệ mã nguồn một chiều của gói `posture_monitor`, làm rõ cách một khung hình đi qua ba nhánh suy luận đa chu kỳ để hội tụ thành các quyết định cảnh báo an toàn luồng qua khe hẹp `DashboardState`. Đồng thời, chương này cũng đã công bố cấu hình phần cứng Raspberry Pi 4 thực tế và quy ước ba nhãn bằng chứng số liệu làm nền tảng minh bạch cho toàn bộ báo cáo.

Để các mô hình nhận thức trong kiến trúc trên hoạt động chính xác và kịp thời, khâu cung cấp trọng số, giải mã luồng video mạng không trễ và chuẩn hóa tín hiệu âm thanh đóng vai trò quyết định. Chương 3 tiếp theo sẽ đi sâu phân tích luồng dữ liệu đầu vào, cơ chế kiểm chứng mô hình pretrained và các thuật toán tiền xử lý trên thiết bị biên.

## CHƯƠNG 3. LUỒNG DỮ LIỆU ĐẦU VÀO, MÔ HÌNH PRETRAINED VÀ TIỀN XỬ LÝ TRÊN THIẾT BỊ BIÊN

### 3.1. Đặc thù dữ liệu trong hệ thống AI biên không lưu trữ hình ảnh

Khác với các đề tài thị giác máy tính truyền thống vốn bắt đầu bằng việc thu thập hàng chục nghìn bức ảnh về máy chủ để gán nhãn hộp bao và huấn luyện lại mạng nơ-ron từ đầu, hệ thống giám sát học tập trên thiết bị biên có hai đặc thù dữ liệu hoàn toàn riêng biệt:

- **Thứ nhất, tận dụng tri thức biểu diễn từ các tập dữ liệu chuẩn quy mô lớn thông qua trọng số pretrained:** Các đối tượng cần phát hiện của đề tài gồm cơ thể người với 17 khớp xương giải phẫu (`person`), chiếc điện thoại di động (`cell phone`) và khuôn mặt người nhìn thẳng/nghiêng đều là các lớp đối tượng cốt lõi đã được huấn luyện trên hàng trăm nghìn mẫu đa dạng của tập dữ liệu Microsoft COCO và kho mô hình OpenCV Zoo. Việc không tự thu thập vài trăm ảnh phòng học nhỏ lẻ để `fine-tune` lại YOLO giúp tránh hiện tượng học vẹt theo phông nền cố định (`overfitting`), đồng thời loại bỏ hoàn toàn nhu cầu thu thập và lưu giữ ảnh cá nhân của sinh viên.
- **Thứ hai, bài toán dữ liệu chuyển trọng tâm sang xử lý luồng tín hiệu sống (`live stream preprocessing`) và dữ liệu tham chiếu cục bộ:** Chất lượng nhận diện của hệ thống trên Raspberry Pi 4 phụ thuộc trực tiếp vào bốn luồng dữ liệu thời gian thực: (1) tính toàn vẹn của các tệp trọng số khi chuyển đổi sang định dạng NCNN/ONNX trên kiến trúc ARM64, (2) độ tươi của khung hình giải mã từ luồng nén HEVC qua giao thức RTSP, (3) phép biến đổi kích thước và ánh xạ hệ tọa độ giữa ảnh suy luận và khung gốc, và (4) chất lượng kho mẫu âm thanh giọng đọc tiếng Việt truyền qua kênh hẹp G.711 PCMA 8 kHz.

### 3.2. Nguồn mô hình pretrained, chuyển đổi NCNN và kiểm chứng toàn vẹn SHA-256

Toàn bộ các tệp trọng số phục vụ suy luận được quản lý tập trung tại thư mục `models/` ở gốc kho mã nguồn. Hàm phân giải đường dẫn `resolve_model_path()` trong `core/config.py` ưu tiên nạp tệp từ `models/` và duy trì cơ chế tự động kiểm tra thư mục gốc nhằm đảm bảo tương thích ngược với các bản cài đặt cũ trên thẻ nhớ Pi.

Đối với hai mô hình họ YOLO (`yolo11n-pose` và `yolo11n`), định dạng gốc PyTorch (`.pt`) chứa đồ thị động không tối ưu cho tập lệnh SIMD NEON của nhân Cortex-A72. Do đó, hệ thống chuyển đổi chúng sang định dạng tĩnh **NCNN** thông qua công cụ `pnnx` ở kích thước đầu vào cố định `imgsz = 320`. Quá trình xuất mô hình `yolo11n-pose` sang NCNN thực hiện trực tiếp trên chính bo mạch Raspberry Pi 4 của dự án mất **42,8 giây** và sinh ra thư mục trọng số dung lượng **11,1 MB** (**ĐÃ ĐO**). Khi triển khai trên môi trường Python `3.13.5` (`aarch64`), dự án cũng ghi nhận và khóa cứng phiên bản thư viện để tránh ba lỗi tương thích nghiêm trọng trên nền tảng ARM: `torch==2.6.0` gây lỗi `Illegal instruction` do thiếu lệnh nguyên tử `ldaddal` trên Cortex-A72 (phải nâng lên `torch==2.7.1`), `ultralytics` các bản `8.4.0..8.4.3` ném `NotImplementedError` khi gọi NCNN trên ARM64 (khóa ở `8.4.191`), và `opencv-python==4.13.0.90` gặp lỗi tự kiểm tra FIPS (nâng lên `5.0.0.93`).

Đối với hai mô hình khuôn mặt thuộc kho OpenCV Zoo, do tệp `sface.onnx` có dung lượng gần `37 MB` không đưa trực tiếp vào lịch sử Git, hệ thống áp dụng quy trình kiểm chứng mã băm mật mã **SHA-256** kết hợp bài kiểm thử nạp cấu trúc tự động `tests/vision/test_models_present.py`. Thông số định danh và mã băm chuẩn của các tệp trọng số được tổng hợp trong Bảng 8.

*Bảng 8. Danh mục nguồn gốc, giấy phép và mã kiểm chứng toàn vẹn của bốn mô hình pretrained*

| Tệp mô hình | Nguồn phát hành chính thức | Dung lượng chuẩn | Giấy phép | Mã băm SHA-256 / Cơ chế kiểm chứng khi nạp |
|---|---|---|---|---|
| `yolo11n-pose.pt` | Ultralytics YOLO11 Release (tập huấn luyện COCO Keypoints) | `6.564.000 B` (`~6,26 MB`) | AGPL-3.0 | Tự động xuất sang `yolo11n-pose_ncnn_model/` qua `YoloModelMixin`; kiểm tra chạy thử tensor đầu ra `(17, 3)` |
| `yolo11n.pt` | Ultralytics YOLO11 Release (tập huấn luyện COCO Detection 80 lớp) | `5.880.000 B` (`~5,61 MB`) | AGPL-3.0 | Tự động xuất sang `yolo11n_ncnn_model/` ở `imgsz = 320`; lọc lớp chỉ số `67` (`cell phone`) |
| `yunet.onnx` | OpenCV Zoo (`face_detection_yunet_2023mar.onnx`) | `232.589 B` (`227 KB`) | Apache-2.0 | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| `sface.onnx` | OpenCV Zoo (`face_recognition_sface_2021dec.onnx`) | `38.696.353 B` (`36,9 MB`) | Apache-2.0 | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |

Bài kiểm thử `test_models_present.py` đảm bảo rằng nếu một tệp tải về bị lỗi mạng hoặc cắt cụt dung lượng nhưng vẫn mang đúng tên `yunet.onnx` hay `sface.onnx`, bộ phân tích cú pháp ONNX của OpenCV sẽ phát hiện và báo lỗi ngay ở bước kiểm tra thay vì để hệ thống âm thầm trả kết quả nhận diện rỗng khi vận hành.

### 3.3. Thu nhận luồng phụ RTSP 704×576 HEVC và thuật toán xả đệm khung cũ

Camera IP của hệ thống phát đồng thời hai luồng video nén chuẩn HEVC (H.265): luồng chính (`/1/1`) ở độ phân giải Full HD `1920×1080` và luồng phụ (`/1/2`) ở độ phân giải D1 mở rộng **`704×576` tốc độ `20 fps`**. Đề tài chủ đích lựa chọn luồng phụ `/1/2` làm nguồn dữ liệu đầu vào duy nhất. Lý do xuất phát trực tiếp từ kiến trúc đường ống: các mô hình YOLO phía sau đều co ảnh về kích thước cạnh dài `320 px`, nên việc giải mã luồng `1920×1080` bằng phần mềm trên CPU Raspberry Pi 4 sẽ tiêu tốn gấp hơn sáu lần số điểm ảnh cần giải mã HEVC mà không mang lại thêm thông tin hữu ích nào cho mạng nơ-ron.

Thách thức lớn nhất khi thu nhận luồng RTSP bằng OpenCV/FFmpeg là hiện tượng tích tụ khung hình cũ trong bộ đệm nhận mạng. Ngay cả khi đặt thuộc tính `CAP_PROP_BUFFERSIZE = 1`, tầng giao vận bên dưới của FFmpeg vẫn duy trì hàng đợi gói tin riêng. Do camera đẩy đều đặn `20 khung/giây` (chu kỳ `50 ms/khung`) trong khi vòng lặp AI chỉ lấy khung ở nhịp khoảng `5 khung/giây` (chu kỳ `200 ms/khung`), mỗi giây có khoảng `15 khung` bị dồn ứ lại. Nếu chỉ gọi hàm `read()` thông thường, hệ thống sẽ đọc phải khung hình của quá khứ và độ trễ quan sát sẽ trượt dài không giới hạn.

Để giải quyết triệt để hiện tượng này, lớp `RTSPSource` trong `camera/capture.py` kết hợp hai tầng kỹ thuật:

1. **Thuật toán xả đệm thích ứng bằng ngưỡng thời gian `grab()` (`30 ms`):** Hàm `grab()` của OpenCV chỉ bước qua gói tin khung tiếp theo mà không thực hiện bước giải mã màu tốn kém như `retrieve()`. Kết quả đo thực nghiệm cho thấy một lệnh `grab()` trên khung hình **đã nằm sẵn trong bộ đệm RAM** chỉ mất trung bình **`0,29 ms`**, trong khi nếu bộ đệm đã cạn sạch, lệnh `grab()` buộc phải chờ khung trực tiếp tiếp theo từ camera mất xấp xỉ **`50 ms`** (`= 1 / 20 fps`). Do đó, `RTSPSource` gọi `grab()` liên tiếp để vứt bỏ toàn bộ khung cũ và dừng lại ngay khi phát hiện một lượt `grab()` kéo dài vượt quá **`30 ms`**: con số nằm chính giữa hai chế độ (lớn gấp hơn `100 lần` mức `0,29 ms` và nhỏ hơn mức `50 ms`), sau đó mới gọi `retrieve()` đúng một lần duy nhất cho khung hình vừa tới.
2. **Luồng đọc nền bất đồng bộ (`Background Reader Thread`):** Một luồng riêng chạy liên tục ở hậu trường để đọc và ghi đè biến khung mới nhất. Phép đo cho thấy thao tác đọc đồng bộ tốn trung bình **`49 ms`**, chiếm tới **`52%`** quỹ thời gian vòng lặp nếu đặt nối tiếp với mô hình suy luận. Tách sang luồng nền giúp quá trình giải mã mạng của khung kế tiếp diễn ra song song với quá trình suy luận NCNN của khung hiện tại.

Quy mô tích tụ khung đệm và hiệu quả tức thì của thuật toán xả đệm khi vòng lặp xử lý bị trễ được minh chứng qua phép đo trên máy tính phát triển tại Bảng 9.

*Bảng 9. Kết quả đo quy mô khung đệm bị dồn ứ và thời gian xả đệm của thuật toán `grab()` liên tiếp*

| Thời gian vòng lặp xử lý bị trễ | Số khung hình cũ tích tụ phải xả bỏ | Tổng thời gian thực hiện vòng xả đệm (`ms`) | Trạng thái khung thu được sau khi xả |
|---|---|---|---|
| `0,2 giây` | `4 khung` | `34 ms` | Bắt kịp khung trực tiếp mới nhất |
| `0,5 giây` | `10 khung` | `40 ms` | Bắt kịp khung trực tiếp mới nhất |
| `1,0 giây` | `26 khung` | `59 ms` | Bắt kịp khung trực tiếp mới nhất |
| `2,0 giây` | `42 khung` | `51 ms` | Bắt kịp khung trực tiếp mới nhất |
| `3,0 giây` | `62 khung` | `137 ms` | Bắt kịp khung trực tiếp mới nhất |
| `5,0 giây` | `101 khung` | `66 ms` | Bắt kịp khung trực tiếp mới nhất |
| `8,0 giây` | `128 khung` | `94 ms` | Bắt kịp khung trực tiếp mới nhất |

Số liệu tại Bảng 9 khẳng định rằng ngay cả khi hệ thống tạm dừng tới `8,0 giây` khiến `128 khung hình` bị dồn trong đệm FFmpeg, vòng xả chỉ cần chưa tới `100 ms` để loại bỏ toàn bộ dữ liệu cũ và khôi phục độ trễ về mức thời gian thực.

Bên cạnh nguồn RTSP, đối với chế độ dò camera cục bộ trên Raspberry Pi 4, công cụ `scripts/camera_probe.py` cũng xử lý một bẫy phần cứng đặc thù của nhân Linux trên SoC Broadcom: các thiết bị ảo `/dev/video10` đến `/dev/video31` thực chất là khối giải mã phần cứng và xử lý tín hiệu ảnh (`bcm2835-codec`, `bcm2835-isp`, `rpi-hevc-dec`) nhưng vẫn trả về `True` khi kiểm tra `cv2.VideoCapture.isOpened()`. Công cụ dò phải đọc tên trình điều khiển từ cây hệ thống `/sys/class/video4linux/` trước để lọc bỏ chính xác **14/14 node không phải camera** trên bo mạch Pi 4 thật (**ĐÃ ĐO**).

### 3.4. Tiền xử lý khung hình cho suy luận NCNN và phát hiện khuôn mặt

Sau khi thu được khung hình BGR gốc kích thước `704×576`, dữ liệu đi vào hai quy trình tiền xử lý khác nhau tùy theo đặc thù của mô hình đích:

- **Tiền xử lý giữ tỷ lệ khung hình (`Letterbox`) cho hai mô hình YOLO NCNN:** Cả `PoseEstimator` và `PhoneDetector` đều chuẩn hóa ảnh đầu vào về lưới vuông `320×320` thông qua phép co đồng dạng giữ nguyên tỷ lệ khung hình (`704×576` thu về `320×262`, chèn dải đệm xám ở hai biên trên/dưới), chuyển đổi không gian màu BGR sang RGB và chuẩn hóa giá trị điểm ảnh về đoạn `[0,0; 1,0]`. Toàn bộ tọa độ khớp xương `xy` và hộp bao `bbox` sau suy luận đều được ánh xạ ngược trở lại hệ tọa độ pixel của **khung gốc `704×576`**. Quy ước thống nhất hệ tọa độ khung gốc này cực kỳ quan trọng vì nó cho phép các phép đo khoảng cách giữa cổ tay (từ mô hình pose) và hộp điện thoại (từ mô hình detect) khớp hoàn toàn trên cùng một mặt phẳng hình học.
- **Quyết định giữ nguyên độ phân giải gốc `704×576` cho bộ phát hiện khuôn mặt YuNet:** Trong bản thiết kế sơ bộ ban đầu, nhóm phát triển từng dự kiến thu nhỏ khung hình về bề ngang `320 px` kết hợp cân bằng sáng cục bộ `CLAHE` (không gian màu `LAB`, `clipLimit = 2,0`, lưới `8×8`, tốn `11,4 ms`) để giảm thời gian chạy YuNet từ `99,9 ms` xuống còn `19,3 ms` (**ĐÃ ĐO**). Tuy nhiên, bài kiểm tra thực nghiệm trên `20 khung hình` camera thật ở ngưỡng phát hiện chuẩn `0,9` cho thấy một kết quả quyết định: chạy trực tiếp trên khung gốc `704×576` phát hiện được mặt trên **20/20 khung**, trong khi ảnh thu nhỏ về `320 px` làm khuôn mặt người ngồi cách camera gần một mét bị mờ chi tiết khiến tỷ lệ phát hiện tụt xuống chỉ còn **0 đến 3/20 khung** (**ĐÃ ĐO**). Nếu cố tình hạ sâu ngưỡng điểm của YuNet trên ảnh nhỏ để vớt lại khuôn mặt, bộ phát hiện sẽ sinh ra các hộp mặt giả đưa vector nhiễu vào bộ phân loại danh tính. Vì vậy, đường chạy chính thức (`vision/faces.py`) chủ đích giữ nguyên khung gốc `704×576` cho YuNet và loại bỏ hoàn toàn các khóa cấu hình thu nhỏ không dùng đến để đảm bảo độ tin cậy nhận diện.

### 3.5. Xây dựng kho dữ liệu âm thanh cảnh báo và chuẩn hóa PCMA 8 kHz

Khác với loa vi tính thông thường hỗ trợ âm thanh nổi tần số cao `44,1 kHz` hoặc `48 kHz`, kênh âm thanh ngược (`RTSP backchannel`) của camera IP tuân thủ chuẩn viễn thông thoại G.711 với băng thông rất hẹp: tần số lấy mẫu **`8.000 Hz`**, đơn kênh (`mono`), lượng tử hóa phi tuyến **8-bit A-law (`PCMA`)** hoặc **µ-law (`PCMU`)**, đóng gói `320 mẫu` trong mỗi gói tin RTP tương ứng chu kỳ **`40 ms/gói`**.

Trên loa tích hợp đường kính chỉ khoảng `2 cm` của camera IP đặt trong phòng kín, âm thanh tổng hợp bằng giọng đọc máy quy tắc (`espeak-ng -v vi`) thường bị hiện tượng méo âm sắc kim loại và khó nghe rõ dấu thanh tiếng Việt sau khi nén xuống A-law 8 kHz. Để định lượng hóa sự khác biệt này và xây dựng kho dữ liệu âm thanh chất lượng cao tại `data/audio/`, đề tài đã tiến hành đo chỉ số độ rõ lời nói khách quan **STOI (`Short-Time Objective Intelligibility`)** đi qua đúng chuỗi biến đổi của camera (`WAV gốc -> lấy mẫu lại 8 kHz -> mã hóa A-law 8-bit -> giải mã PCM`). Kết quả đo đạt được trình bày trong Bảng 10.

*Bảng 10. So sánh độ rõ lời nói khách quan (STOI) và đặc tính kỹ thuật của ba tầng nguồn âm thanh cảnh báo*

| Thứ tự ưu tiên | Nguồn âm thanh cảnh báo | Vị trí lưu trữ / Công cụ sinh | Chỉ số độ rõ STOI qua kênh 8 kHz A-law | Yêu cầu công cụ ngoài | Vai trò vận hành thực tế |
|---|---|---|---|---|---|
| **Tầng 1 (Chính)** | Bản thu giọng người thật (Giọng Nam / Giọng Nữ) | `data/audio/giongnam/`, `data/audio/giongnu/` (tệp `.wav` chuẩn hóa) | **0,958 - 0,972** (**ĐÃ ĐO**) | Cần `ffmpeg` để chuyển mã sang luồng G.711 | Nguồn phát mặc định cho 3 câu cảnh báo cố định và thông báo hết giờ học |
| **Tầng 2 (Dự phòng 1)** | Giọng tổng hợp quy tắc tiếng Việt | Mô-đun `alerts/espeak_synth.py` gọi tiến trình `espeak-ng -v vi` | **0,929 - 0,945** (**ĐÃ ĐO**) | Cần cả `espeak-ng` và `ffmpeg` | Tự động kích hoạt khi câu thoại động chưa có tệp thu sẵn trong thư mục giọng |
| **Tầng 3 (Dự phòng cuối)** | Âm hiệu sóng hình sin thuần Python (`speak_tone`) | Sinh trực tiếp mảng mẫu G.711 và đóng gói RTP trong `camera/audio.py` | Không áp dụng (âm đơn sắc) | **Không cần** bất kỳ chương trình ngoài nào | Chốt chặn an toàn tuyệt đối trên máy thiếu `ffmpeg` (như Windows phát triển) |

Kết quả STOI cao vượt trội (`0,958 - 0,972`) của bản thu giọng người tại Bảng 10 khẳng định việc đầu tư chuẩn bị trước bộ tệp WAV giọng nam và giọng nữ cho các tình huống cố định (rời khung hình, dùng điện thoại, người lạ ngồi vào bàn, kết thúc phiên học) mang lại trải nghiệm nghe rõ ràng hơn hẳn trên loa nhỏ của camera.

### 3.6. Kiểm soát chất lượng tín hiệu và tính độ tươi dữ liệu (`Signal Freshness`)

Trong một hệ thống IoT đa chu kỳ mà mỗi cảm biến/mô hình cập nhật ở tốc độ khác nhau, sai lầm nguy hiểm nhất về mặt dữ liệu là trình bày một kết luận đã đo từ nhiều phút trước như thể đó là trạng thái hiện tại của người học. Để ngăn chặn hiện tượng "dữ liệu thối" (`stale telemetry`), bảng hợp nhất tín hiệu `SignalBoard` (`domain/signal_board.py`) và kho `DashboardState` (`web/state.py`) gắn chặt cho mỗi mẩu thông tin hai siêu dữ liệu thời gian:

- **Tuổi của tín hiệu (`age_s`):** Khoảng thời gian tính bằng giây kể từ lần cập nhật hợp lệ cuối cùng đến thời điểm khách hàng truy vấn, đo bằng đồng hồ đơn điệu (`time.monotonic()`) để miễn nhiễm với việc nhảy giờ hệ thống NTP.
- **Cờ độ tươi (`fresh` / `stale`):** Nếu `DashboardState` không nhận được nhịp cập nhật mới từ vòng lặp camera quá ngưỡng `STALE_AFTER_S = 10,0 giây`, cờ `stale = True` lập tức được bật lên; tương tự, từng tín hiệu thành phần (`presence`, `phone`, `identity`) khi vượt quá thời hạn hiệu lực hoặc khi hệ thống đang ở ngoài phiên học sẽ trả về `fresh = False`. Cả giao diện Web lẫn Ứng dụng di động đều tuân thủ quy ước cứng: hễ `fresh = False`, giao diện bắt buộc hiển thị nhãn `"Chưa có dữ liệu mới"` thay vì giữ lại màu xanh `"Đang trong khung hình"` hay `"Không dùng điện thoại"` của phiên trước.

### 3.7. Kết chương

Chương 3 đã làm rõ toàn bộ nền tảng dữ liệu và tiền xử lý ở phía đầu vào của thiết bị biên: từ lý do sử dụng bộ bốn mô hình pretrained có kiểm chứng mã băm SHA-256, lựa chọn luồng phụ RTSP `704×576` kèm thuật toán xả đệm `grab()` ngưỡng `30 ms` giúp triệt tiêu độ trễ tích lũy, quyết định giữ nguyên độ phân giải gốc cho YuNet dựa trên phép đo thực tế `20/20 khung`, cho đến quy trình chuẩn hóa âm thanh G.711 PCMA 8 kHz đạt chỉ số STOI `0,958-0,972`.

Khi khung hình tươi và sạch đã sẵn sàng trên RAM, nó được chuyển giao cho mô hình xương sống đầu tiên của tầng nhận thức. Chương 4 tiếp theo sẽ phân tích chuyên sâu module ước lượng khung xương YOLO11n-pose, thuật toán khóa đối tượng chống nhảy người, cơ chế xác định hiện diện và bộ luật hình học tư thế.

## CHƯƠNG 4. MODULE ƯỚC LƯỢNG KHUNG XƯƠNG, HIỆN DIỆN VÀ BỘ LUẬT TƯ THẾ (YOLO11N-POSE)

### 4.1. Mục tiêu của module trong hệ thống

Module ước lượng khung xương đóng vai trò xương sống trung tâm của toàn bộ tầng nhận thức thị giác trong phiên học. Thay vì chỉ cung cấp một hộp chữ nhật bao quanh cơ thể người vốn rất nhạy cảm với khoảng cách đặt ghế và góc nghiêng camera, module này trích xuất cấu trúc giải phẫu 17 điểm khớp xương chuẩn COCO trên từng khung hình để phục vụ đồng thời ba nhiệm vụ nghiệp vụ:

1. Xác định chính xác người học mục tiêu đang còn ngồi trước bàn hay đã rời khỏi khu vực quan sát (`Presence Detection`).
2. Cung cấp tọa độ hai cổ tay (điểm mốc số `9` và `10`) cùng bề rộng hai vai (điểm mốc số `5` và `6`) làm thước đo chuẩn hóa hình học cho bộ phát hiện sử dụng điện thoại ở Chương 5.
3. Tính toán các góc nghiêng vai, nghiêng đầu, độ cúi và khoảng cách tương đối cho bộ luật đánh giá tư thế ngồi và hiển thị điểm số trực quan trên ứng dụng di động.

### 4.2. Cấu trúc đầu ra 17 điểm mốc COCO và cơ chế nạp an toàn `YoloModelMixin`

Mô hình `YOLO11n-pose` là biến thể nhẹ nhất (`nano`) của kiến trúc YOLO11 dành cho bài toán ước lượng tư thế người, chỉ dự đoán một lớp đối tượng duy nhất (`person`) kèm theo 17 bộ ba giá trị `(x, y, conf)` đại diện cho tọa độ điểm ảnh và độ tin cậy trong đoạn `[0, 1]` của từng khớp xương. Trong mã nguồn `vision/pose.py`, kết quả suy luận của người học mục tiêu trên mỗi khung hình được chuẩn hóa thành cấu trúc bất biến `PoseResult` (`NamedTuple`) gồm ba mảng `float32`: mảng tọa độ `xy` kích thước `(17, 2)` trên hệ khung gốc, mảng độ tin cậy `conf` kích thước `(17,)` và hộp bao cơ thể `bbox` kích thước `(4,)` dạng `(x1, y1, x2, y2)`.

Thứ tự chỉ số 17 khớp xương tuân thủ chuẩn COCO gồm: `0` (mũi), `1-2` (mắt trái/phải), `3-4` (tai trái/phải), `5-6` (vai trái/phải), `7-8` (khuỷu tay trái/phải), `9-10` (cổ tay trái/phải), `11-12` (hông trái/phải), `13-14` (gối trái/phải) và `15-16` (cổ chân trái/phải). Với góc đặt camera IP trước bàn học, nhóm điểm từ `0` đến `10` (đầu, vai, cánh tay) thường xuyên nằm rõ trong khung hình, trong khi nhóm thân dưới từ `11` đến `16` bị mặt bàn che khuất.

Để đảm bảo hệ thống khởi động an toàn trên cả Raspberry Pi 4 (ưu tiên tốc độ NCNN) lẫn máy tính phát triển Windows/Linux (có thể chưa xuất tệp NCNN), lớp trộn `YoloModelMixin` trong `vision/yolo_loader.py` thực thi chuỗi nạp dự phòng ba bậc tự động: **`NCNN -> ONNX -> PyTorch (.pt)`**. Nếu cấu hình yêu cầu định dạng `ncnn` nhưng thư mục `models/yolo11n-pose_ncnn_model/` chưa tồn tại, hệ thống tự động gọi quy trình xuất mô hình một lần duy nhất ở kích thước `imgsz = 320`. Nếu quá trình xuất hoặc nạp NCNN thất bại do thiếu thư viện nền tảng, bộ nạp ghi nhật ký cảnh báo `WARNING` nêu rõ nguyên nhân và tự động rơi xuống định dạng ONNX, sau đó mới đến tệp `.pt` gốc. Chỉ khi cả ba định dạng đều hỏng, hệ thống mới ném ngoại lệ `PoseError` để tầng dòng lệnh thông báo lỗi cấu hình rõ ràng cho người vận hành.

### 4.3. Thuật toán bám đối tượng theo `track id` và chống nhảy sang người đi ngang

Trong điều kiện thực tế tại gia đình hoặc phòng trọ, việc có một người thứ hai đi ngang qua phía sau lưng người học hoặc đứng gần bàn học trong vài giây diễn ra khá phổ biến. Ở phiên bản thử nghiệm đầu tiên, hệ thống chọn người cần giám sát bằng quy tắc đơn giản "lấy hộp bao có diện tích lớn nhất trong khung hình". Quy tắc ngây thơ này gây ra một lỗi nghiệp vụ nghiêm trọng: khi người học chính rời khỏi ghế để đi lấy nước và một người khác đi ngang qua ống kính, hệ thống lập tức chọn người đi ngang làm đối tượng giám sát và hủy bỏ bộ đếm cảnh báo vắng mặt của người học chính.

Để khắc phục triệt để lỗi này, `PoseEstimator` chuyển sang cơ chế khóa đối tượng theo mã định danh vết (**`track id`**) kết hợp thời gian giữ khóa khi vắng mặt (`timing.absent_reset_s = 120 giây`) theo ba quy tắc chặt chẽ:

1. **Khi đã khóa một `track id` và mã đó còn xuất hiện trong khung hiện tại:** Hệ thống luôn trích xuất đúng khung xương của `track id` này, bất kể trong khung có người khác đứng gần camera hơn với diện tích hộp bao lớn hơn.
2. **Khi mất dấu `track id` đã khóa nhưng thời gian mất dấu chưa vượt quá `absent_reset_s` (`120 giây`):** Hệ thống chủ động trả về `None` (coi như người đang học vắng mặt) và **tuyệt đối không nhảy khóa sang người khác** đang có mặt trong khung hình. Chỉ khi chính người cũ quay lại vị trí ghế ngồi phù hợp điều kiện bám lại (`reacquire`), theo dõi mới được nối tiếp.
3. **Khi chưa khóa ai ở đầu phiên học hoặc thời gian vắng đã vượt quá `120 giây`:** Hệ thống mới thực hiện chọn hộp bao lớn nhất để thiết lập khóa `track id` mới. Trong trường hợp bộ theo dõi vết (`tracker`) bên trong Ultralytics gặp lỗi ngoại lệ lúc đang chạy, `PoseEstimator` tự động ghi `WARNING` và chuyển mềm sang chế độ suy luận từng khung độc lập (`predict`) để vòng lặp giám sát không bị gián đoạn.

### 4.4. Cơ chế xác định hiện diện (`Presence`) dựa trên nhóm keypoint thân trên

Thay vì đánh giá sự hiện diện của người học chỉ dựa trên việc có hay không một hộp bao `person` (vốn dễ bị báo giả bởi chiếc áo khoác vắt trên lưng ghế xoay), mô-đun `domain/presence.py` kiểm định trực tiếp cấu trúc giải phẫu phần thân trên của đối tượng đã khóa. Quy tắc xác định hiện diện và các tham số điều khiển được tổng hợp trong Bảng 11.

*Bảng 11. Quy tắc và tham số xác định trạng thái hiện diện của người học trong `domain/presence.py`*

| Tham số / Thành phần | Giá trị thiết lập | Vai trò và ý nghĩa kỹ thuật trong quyết định hiện diện |
|---|---|---|
| Tập điểm mốc kiểm tra | `COCO 0..6` (7 điểm) | Bao gồm mũi, hai mắt, hai tai và hai vai: nhóm điểm luôn lộ diện trên mặt bàn học ngay cả khi cúi viết bài |
| Ngưỡng tin cậy từng điểm | `conf >= 0,50` | Loại bỏ các điểm mốc suy đoán mờ khi mô hình nhìn nhầm lưng ghế hoặc bóng đổ |
| Số điểm hợp lệ tối thiểu | `>= 2 điểm` | Chỉ cần thấy rõ ít nhất 2 trong 7 điểm thân trên (ví dụ hai vai hoặc một tai và một vai khi quay nghiêng) là xác nhận có người |
| Thời gian ân hạn vắng mặt | `absent_grace_s = 3,0 s` | Phải mất dấu liên tục đủ `3,0 giây` mới chuyển trạng thái sang `vang_mat`, chống nhấp nháy khi cúi nhặt bút |
| Thời gian giữ phát cảnh báo | `leave_frame.hold_s = 5,0 s` | Duy trì trạng thái vắng đủ ngưỡng cấu hình mới kích hoạt câu nhắc nhở ra loa camera |
| Khôi phục khi quay lại | Tức thời (`0,0 s`) | Ngay khung đầu tiên thấy lại `>= 2` điểm thân trên hợp lệ, trạng thái trở về `co_mat` ngay lập tức |

Một ưu điểm kỹ thuật quan trọng của `domain/presence.py` là tính thuần khiết hàm (`pure state tracker`): mô-đun hoàn toàn không tự gọi hàm đọc cấu hình đĩa hay đồng hồ hệ thống `time.time()`, mà nhận dấu thời gian `now` qua tham số đầu vào, cho phép bộ kiểm thử tự động tua nhanh hàng trăm giây thời gian giả lập chỉ trong vài phần nghìn giây chạy máy.

### 4.5. Bộ luật đặc trưng hình học tư thế và máy trạng thái có trễ (`Hysteresis`)

Kế thừa từ nền tảng đánh giá tư thế ngồi của phiên bản hệ thống trước (v2), các mô-đun `vision/features.py`, `vision/classifier.py` và `domain/state.py` vẫn tính toán đầy đủ sáu đặc trưng hình học chuẩn hóa trên mỗi khung hình có người để phục vụ hiển thị thông số trên ứng dụng di động và hỗ trợ gỡ lỗi kỹ thuật. Định nghĩa toán học và ngưỡng phân loại của sáu đặc trưng này được trình bày trong Bảng 12.

*Bảng 12. Các đặc trưng hình học khung xương và ngưỡng phân loại của bộ luật tư thế*

| Tên đặc trưng | Công thức / Ý nghĩa hình học | Ngưỡng mặc định | Hiện tượng vật lý phản ánh |
|---|---|---|---|
| `shoulder_width` | Khoảng cách Euclid giữa vai trái (`kp 5`) và vai phải (`kp 6`) tính bằng pixel | Dùng làm mẫu số chuẩn hóa | Thước đo tỷ lệ cơ thể bất biến với độ phân giải, đồng thời phản ánh độ tiến sát camera |
| `head_height` | `(y_trung_bình_vai - y_mũi) / shoulder_width` | `head_down_ratio = 0,70` | Tỷ số giảm xuống dưới `0,70` so với mốc chuẩn khi người học gục đầu thấp xuống bàn |
| `closeness` | `shoulder_width / baseline_shoulder_width` | `too_close_ratio = 1,25` | Lớn hơn `1,25` cho biết người ngồi nhô sát về phía màn hình/camera hơn `25%` so với lúc hiệu chỉnh |
| `shoulder_tilt_deg` | Góc hợp bởi đoạn thẳng nối hai vai so với trục ngang khung hình | `8,0 độ` | Phản ánh tư thế ngồi lệch vai hoặc tỳ hẳn một bên khuỷu tay xuống bàn |
| `head_tilt_deg` | Góc hợp bởi đoạn thẳng nối hai tai (`kp 3, 4`) so với trục ngang | `12,0 độ` | Phản ánh tư thế nghiêng đầu sang một bên trong thời gian dài |
| `lean_x` · `head_yaw` | Độ lệch tâm ngang thân trên và tỷ lệ bất đối xứng khoảng cách mũi - hai tai | `0,35` · `0,50` | Phản ánh hành vi nhoài người lệch khỏi tâm ghế hoặc quay mặt nhìn hẳn sang hướng khác |

Để ngăn chặn hiện tượng nhãn trạng thái nhảy liên tục ở vùng biên ngưỡng, máy trạng thái trong `domain/state.py` áp dụng bộ lọc trung vị trượt cửa sổ `1,0 giây` nối tiếp với cơ chế trễ hai chiều (`hysteresis`): trạng thái xấu phải duy trì liên tục đủ `bad_hold_s = 5,0 giây` mới mở sự kiện cảnh báo, phải ngồi chuẩn trở lại liên tục `good_hold_s = 2,0 giây` mới đóng sự kiện, đồng thời chịu sự chi phối của khoảng nghỉ `cooldown = 30 giây` và nhắc leo thang sau `60 giây`. Trong cấu hình vận hành hiện hành của đề tài, công tắc `posture_labels_enabled: false` được bật có chủ đích để **lược bỏ các cảnh báo âm thanh về sai tư thế ngồi**, chỉ cho phép nhãn `ABSENT` đi tiếp vào luồng phát loa nhằm tập trung đúng vào ba sự kiện trọng tâm của bài toán (rời bàn, dùng điện thoại, sai người học), trong khi điểm số tư thế thang `100` và khoảng cách vẫn được duy trì phục vụ hiển thị trên màn hình ứng dụng di động.

### 4.6. Nhận xét và hạn chế kỹ thuật của module

Thực tế vận hành trên Raspberry Pi 4 cho thấy `YOLO11n-pose` ở định dạng NCNN `imgsz = 320` hoạt động rất ổn định với các tư thế ngồi học nhìn từ phía trước và phía chếch `30-45 độ`, đạt thời gian suy luận thuần trung vị `107,3 ms/khung` (**ĐÃ ĐO**). Cơ chế khóa `track id` kết hợp đếm keypoint thân trên đã loại bỏ hoàn toàn lỗi nhảy trạng thái khi có người đi qua phía sau.

Tuy nhiên, module vẫn tồn tại hai hạn chế kỹ thuật được ghi nhận rõ trong mã nguồn: thứ nhất, bốn hằng số hình học phục vụ việc bắt lại `track id` sau khi người học quay lại ghế (`REACQUIRE_MIN_IOU = 0,1`, `REACQUIRE_MAX_CENTER_SHIFT_RATIO = 0,5`, `REACQUIRE_MIN_FRAME_RATIO = 0,05`, `REACQUIRE_MAX_ASPECT_RATIO = 4,0`) hiện đang là giá trị khởi tạo hợp lý nhưng **chưa được hiệu chuẩn bằng phép đo thống kê trên camera thật** (**CHƯA ĐO**, đã xây dựng sẵn công cụ `scripts/calibrate_reacquire.py` để đo bổ sung); thứ hai, khi người học cúi sát mặt bàn che khuất cả mũi, mắt và tai dưới ánh sáng yếu khiến dưới 2 keypoint đạt ngưỡng `0,5`, bộ theo dõi có thể coi là vắng mặt nếu tư thế đó giữ nguyên quá `3,0 giây`.

### 4.7. Kết chương

Chương 4 đã trình bày chi tiết cấu trúc và nguyên lý vận hành của module ước lượng khung xương YOLO11n-pose, từ cơ chế nạp dự phòng ba bậc `NCNN -> ONNX -> PyTorch`, thuật toán khóa `track id` chống nhảy người trong `120 giây`, quy tắc kiểm định hiện diện từ 7 điểm mốc thân trên cho đến bộ đặc trưng hình học và máy trạng thái trễ.

Các tọa độ cổ tay (`kp 9, 10`), mũi (`kp 0`) và hai vai (`kp 5, 6`) trích xuất được từ module này chính là dữ liệu nền tảng không thể thiếu để giải bài toán phức tạp tiếp theo: phân biệt chiếc điện thoại đang được cầm sử dụng với chiếc điện thoại nằm yên trên bàn hoặc các vật thể gây nhiễu như gọng kính. Chương 5 tiếp theo sẽ đi sâu vào thiết kế và kiểm chứng thực nghiệm module phát hiện sử dụng điện thoại.

## CHƯƠNG 5. MODULE PHÁT HIỆN SỬ DỤNG ĐIỆN THOẠI TRONG PHIÊN HỌC (YOLO11N DETECT)

### 5.1. Mục tiêu của module và lý do cần mô hình thứ hai

Mô hình `YOLO11n-pose` ở Chương 4 chỉ được huấn luyện trên duy nhất một lớp đối tượng là cơ thể người (`person`), do đó hoàn toàn không có khả năng nhận biết sự xuất hiện của chiếc điện thoại di động trong khung hình. Ngược lại, nếu chỉ dựa vào chuyển động cúi đầu hoặc đưa cổ tay lên trước ngực từ khung xương thì hệ thống không thể phân biệt được người học đang cầm điện thoại lướt mạng với người học đang cầm máy tính bỏ túi Casio, cầm bút ghi chép hay nâng cốc nước uống.

Vì lý do đó, đề tài bổ sung mô hình thứ hai là **`YOLO11n` bài toán phát hiện vật thể tổng quát (80 lớp COCO)**, trích lọc riêng **lớp chỉ số `67` (`cell phone`)**, rồi kết hợp chặt chẽ hộp bao điện thoại với tọa độ cổ tay và đường vai của mô hình pose. Mục tiêu của module không phải là báo động mỗi khi thấy một chiếc điện thoại xuất hiện trên mặt bàn, mà là phát hiện chính xác hành vi **"người học đang cầm hoặc chạm tay sử dụng điện thoại kéo dài"**.

### 5.2. Đặc thù ảnh điện thoại tại bàn học và bài toán báo nhầm gọng kính

Khi quan sát thực tế qua luồng phụ `704×576` của camera IP đặt cách người ngồi khoảng `0,8 - 1,2 mét`, chiếc điện thoại nằm gọn trong lòng bàn tay bị các ngón tay che khuất phần lớn diện tích, chỉ lộ ra một phần cạnh viền hoặc mặt lưng tối màu với kích thước khoảng `35-70 pixel`. Đặc điểm hình ảnh này dẫn tới hai hiện tượng thực nghiệm rất khác biệt so với ảnh chụp cận cảnh rõ nét trong các bộ dữ liệu chuẩn:

1. **Độ tin cậy (`confidence`) của điện thoại thật xuống rất thấp và chồng lấn với nhiễu:** Phép đo trên camera thật cho thấy chiếc điện thoại đang cầm trên tay nhiều thời điểm chỉ đạt điểm tin cậy `0,06 - 0,236`. Trong khi đó, mô hình COCO lại thường xuyên nhận nhầm **gọng kính cận màu đen trên khuôn mặt người học** thành lớp `cell phone` với điểm tin cậy từ **`0,023` đến `0,068`** (**ĐÃ ĐO**). Vì hai dải điểm này giao thoa sát nhau ở vùng `0,06`, không tồn tại bất kỳ ngưỡng `conf_threshold` đơn lẻ nào vừa bắt nhạy được điện thoại bị tay che vừa loại sạch được gọng kính.
2. **Độ tin cậy của chính khớp xương cổ tay đang cầm máy cũng suy giảm:** Khi bàn tay co lại ôm lấy thân điện thoại, khớp cổ tay bị che khuất một phần khiến độ tin cậy keypoint cổ tay của YOLO11n-pose tụt xuống mức **`0,35 - 0,43`** (**ĐÃ ĐO**). Nếu dùng chung ngưỡng `model.kp_conf_min = 0,50` của bài toán tư thế, hệ thống sẽ loại bỏ đúng cổ tay đang cầm điện thoại và tính năng phát hiện hoàn toàn tê liệt. Do đó, cấu hình bắt buộc tách riêng tham số `phone.wrist_conf_min = 0,25`.

### 5.3. Lập lịch suy luận cách khung (`1/2` khung) và hộp bao có thời hạn (`TTL`)

Trên Raspberry Pi 4, một lượt suy luận `YOLO11n` detect ở định dạng NCNN `imgsz = 320` tiêu tốn **`98,6 ms`** trên khung thử nghiệm `640×480` (**ĐÃ ĐO**, lần chạy lặp lại thứ hai là `98,7 ms`): tương đương toàn bộ chi phí suy luận của mô hình pose. Nếu gọi mô hình detect ở mọi khung hình nối tiếp sau mô hình pose, tổng thời gian xử lý một khung sẽ vọt lên gần `300 ms` (`~3,36 FPS`).

Để giảm một nửa gánh nặng CPU của nhánh này, `PhoneDetector` (`vision/phone_detector.py`) áp dụng cơ chế chạy **cách khung** (`phone.detect_every_n_frames = 2`), tức cứ hai khung hình của vòng lặp chính mới gọi suy luận detect một lần. Ở các khung hình xen giữa không chạy mô hình detect, bộ kiểm tra hành vi (`vision/phone.py`) tái sử dụng danh sách hộp bao điện thoại gần nhất đi kèm cơ chế **thời hạn sống của hộp (`box_ttl_s = 0,5 giây`)**: mỗi hộp bao đều gắn dấu thời gian lúc được phát hiện; quá `0,5 giây` mà chưa có lượt detect mới xác nhận lại thì hộp đó tự động hết hạn và bị loại bỏ để không gây báo chạm giả với bóng ma của chiếc điện thoại đã cất đi.

### 5.4. Định nghĩa toán học của khoảng cách chạm chuẩn hóa theo bề rộng vai

Xét tập hợp `P` gồm các tọa độ khớp cổ tay trái và cổ tay phải (`COCO keypoint 9, 10`) có độ tin cậy thỏa mãn `conf >= wrist_conf_min` (`0,25`), và tập hợp `B` gồm các hộp chữ nhật lớp `cell phone` đã vượt qua bộ lọc hình học và còn nằm trong thời hạn sống `box_ttl_s`. Hàm `khoang_cach_diem_hop(p, b)` trong `vision/phone.py` tính khoảng cách Euclid ngắn nhất từ điểm cổ tay `p = (x, y)` tới hình chữ nhật `b = (x1, y1, x2, y2)` (nếu điểm `p` nằm bên trong hoặc ngay trên cạnh hộp `b` thì khoảng cách bằng `0`).

Một khung hình được đánh dấu là có tương tác cầm/chạm điện thoại khi khoảng cách nhỏ nhất giữa mọi cặp cổ tay và hộp điện thoại không vượt quá ngưỡng động `proximity_px`:

$$
\min_{p \in P,\, b \in B} d(p, b) \le \text{touching\_slack\_px} + \text{shoulder\_ratio} \times W_{\text{shoulder}}
$$

Trong cấu hình chuẩn của hệ thống, `touching_slack_px = 0` và **`shoulder_ratio = 1,0`**, tức ngưỡng khoảng cách cho phép bằng đúng một lần bề rộng hai vai `W_shoulder` đo trên khung hình đó. Con số `1,0` này không phải là ước lượng cảm tính mà được xác lập trực tiếp từ phép đo thực nghiệm trên `40 khung hình` cầm điện thoại thật ở độ phân giải `704×576` (**ĐÃ ĐO**):

- Điểm mốc số `9` và `10` của chuẩn COCO đặt tại **khớp cổ tay** chứ không đặt tại đầu ngón tay cầm máy; cộng thêm sai số co giãn hộp bao nên khoảng cách thực tế từ điểm cổ tay tới mép hộp điện thoại dao động trong khoảng **`112 - 138 px`**.
- Cùng lúc đó, bề rộng hai vai của người ngồi học đo được trong khoảng **`148,8 - 171,3 px`**, tức khoảng cách cổ tay - điện thoại tương đương **`0,70 - 0,86` lần bề rộng vai**.
- Khi thử nghiệm ngưỡng khoảng cách bằng `0 px` (yêu cầu điểm cổ tay phải đè lên hộp điện thoại như suy nghĩ trực giác ban đầu), kết quả thu được là **`0/40 khung`** phát hiện chạm (thất bại `100%`). Ngược lại, chuẩn hóa theo `1,0 × bề rộng vai` giúp bắt trọn vẹn vùng bàn tay cầm máy đồng thời tự động co giãn tỷ lệ thuận khi người học ngồi gần hay xa camera hơn.

### 5.5. Ba bộ lọc hình học triệt tiêu lỗi báo nhầm và bộ lọc thời gian

Để giải quyết triệt để hiện tượng gọng kính cận bị nhận nhầm thành điện thoại ở ngưỡng điểm thấp `conf_threshold = 0,06` (trong khi cổ tay đưa lên gãi đầu hoặc chống cằm lại nằm gần mặt dưới `1,0` lần bề rộng vai), hệ thống thiết kế ba quy tắc lọc hình học phối hợp cùng bộ lọc độ bền thời gian. Cơ chế và hiệu quả đo đạc thực tế trên tập `32 hộp` kiểm chứng (`8 hộp` điện thoại thật và `24 hộp` báo giả trên vùng mặt/kính) được trình bày trong Bảng 13.

*Bảng 13. Cơ chế và hiệu quả thực nghiệm của hệ thống lọc hình học và lọc thời gian cho điện thoại*

| Tên thành phần lọc | Điều kiện toán học áp dụng | Kết quả kiểm chứng thực nghiệm (**ĐÃ ĐO**) | Vai trò thực tế trong đường ống |
|---|---|---|---|
| `head_filter` | Loại hộp nếu hộp bao phủ điểm mũi (`kp 0`) **và** chiều cao hộp `>=` khoảng cách dọc từ mũi tới đường vai | Loại `0/32 hộp` | Chốt chặn lý thuyết cho hộp phủ kín cả đầu; thực tế gọng kính có chiều cao hẹp nên không bị bộ lọc này bắt (được ghi nhận trung thực trong cấu hình) |
| `phone_like_filter` | Loại hộp nếu tâm hộp nằm **cao hơn đường nối hai vai quá `10 px`** **hoặc** cạnh dài của hộp `< 0,45 × bề rộng vai` | Giữ trọn **8/8 hộp thật**, loại sạch **24/24 hộp giả** (riêng vế đường vai loại `22/24`, vế kích thước loại nốt `2/24`) | **Bộ lọc chủ lực** giải quyết dứt điểm bài toán nhận nhầm gọng kính và đốm nhiễu nhỏ trên mặt bàn |
| `oversize_ratio` *(van an toàn)* | Nếu cạnh dài hộp `> 2,25 × bề rộng vai` thì **miễn trừ**, giữ lại hộp bất chấp vị trí cao hơn vai | Dải an toàn thực nghiệm `1,8 - 2,8`; bắt đúng ca điện thoại giơ sát ống kính (`2,83×` vai, cao hơn vai `> 200 px`) | Ngăn ngừa `phone_like_filter` vô tình loại bỏ chiếc điện thoại thật khi người học giơ cao lên trước mặt |
| Bộ lọc thời gian (`hold_s` & `miss_tolerance`) | Duy trì chạm liên tục `hold_s = 1,0 s`, cho phép hụt tối đa `miss_tolerance_frames = 4 khung` liên tiếp không xóa bộ đếm | Giữ ổn định sự kiện ở tốc độ `~4-5 FPS` khi detect chạy cách khung | Chống báo sai khi tay vô tình lướt ngang qua chiếc điện thoại đặt trên bàn trong tích tắc |

Sự kết hợp giữa `phone_like_filter` và van an toàn `oversize_ratio` trong Bảng 13 minh họa rõ giá trị của kỹ thuật hậu xử lý có căn cứ đo lường: không cần huấn luyện lại mạng YOLO11n tốn kém mà vẫn phân tách chính xác `100%` tập mẫu nhiễu gọng kính khỏi điện thoại thật. Tham số `miss_tolerance_frames = 4` cũng đóng vai trò sống còn: ở tốc độ `4-5 FPS` và chu kỳ chạy cách khung, một khung bị nhòe chuyển động (`motion blur`) làm mất hộp detect sẽ khiến hộp cũ hết hạn `0,5 s`; nếu bộ đếm thời gian bị đặt về `0` ngay lập tức ở khung hụt đầu tiên thì điều kiện giữ `1,0 giây` sẽ không bao giờ tích lũy đủ trong thực tế.

### 5.6. Nhận xét và hạn chế kỹ thuật của module

Module phát hiện sử dụng điện thoại đạt được sự cân bằng tốt giữa độ nhạy thực tế và khả năng kháng nhiễu gọng kính ở cấu hình nhẹ cho CPU biên. Tuy nhiên, xét về mặt bản chất hình học 2D trên ảnh đơn mục (`monocular 2D projection`), module vẫn có hai giới hạn tự nhiên cần nêu rõ:

- Nếu người học đặt chiếc điện thoại nằm ngửa ngay sát bên cạnh bàn phím hoặc vở viết và để cổ tay tỳ lên mặt bàn trong bán kính `1,0 × bề rộng vai` suốt hơn `1,0 giây`, phép chiếu 2D không có thông tin chiều sâu 3D của các đốt ngón tay nên vẫn có thể kết luận là đang chạm sử dụng điện thoại.
- Các điện thoại có vỏ ốp trong suốt đặt úp trên mặt bàn đồng màu hoặc bị che khuất hơn `80%` diện tích dưới khuỷu tay có thể rơi xuống dưới ngưỡng `conf_threshold = 0,06` trong nhiều chu kỳ liên tiếp, làm trễ thời điểm phát cảnh báo.

### 5.7. Kết chương

Chương 5 đã phân tích trọn vẹn giải pháp phát hiện hành vi sử dụng điện thoại trên thiết bị biên bằng sự kết hợp giữa mô hình `YOLO11n` detect chạy cách khung, hộp bao có thời hạn sống `0,5 giây`, khoảng cách cổ tay chuẩn hóa theo bề rộng vai và bộ ba quy tắc lọc hình học giúp loại bỏ hoàn toàn hiện tượng báo nhầm gọng kính.

Sau khi đã trả lời được hai câu hỏi đầu tiên của bài toán là "người học có mặt tại bàn không" (Chương 4) và "có đang dùng điện thoại không" (Chương 5), hệ thống cần giải quyết câu hỏi thứ ba mang tính định danh cá nhân: "người đang ngồi học có đúng là chủ nhân của phiên học hay không". Chương 6 tiếp theo sẽ trình bày chi tiết module đăng ký và xác thực danh tính khuôn mặt bằng cặp mô hình YuNet và SFace.

## CHƯƠNG 6. MODULE ĐĂNG KÝ VÀ XÁC THỰC DANH TÍNH NGƯỜI HỌC (YUNET VÀ SFACE)

### 6.1. Mục tiêu của module và lý do chọn bộ công cụ gốc OpenCV Zoo

Module nhận diện danh tính đảm nhiệm hai chức năng song hành trong vòng đời sử dụng hệ thống: (1) cho phép đăng ký hồ sơ khuôn mặt của người học mới ngay trên giao diện Web mà không cần bất kỳ bước huấn luyện lại mô hình nào, và (2) định kỳ xác minh người đang ngồi trước bàn học có trùng khớp với người học đã được chọn cho phiên hiện tại hay không.

Khi lựa chọn công nghệ thực thi trên Raspberry Pi OS Trixie (`aarch64`, Python `3.13.5`), các thư viện nhận diện khuôn mặt phổ biến trên máy chủ x86 đều bộc lộ rào cản lớn: `dlib` / `face_recognition` đòi hỏi biên dịch mã nguồn C++ rất nặng trên RAM 4 GB và chạy chậm trên CPU ARM; trong khi `insightface` kéo theo phụ thuộc `onnxruntime` riêng lẻ dễ xung đột phiên bản thư viện hệ thống. Ngược lại, thư viện `opencv-python==5.0.0.93` đã tích hợp sẵn hai lớp gốc viết bằng C++ tối ưu là **`cv2.FaceDetectorYN`** (chạy mô hình **YuNet**) và **`cv2.FaceRecognizerSF`** (chạy mô hình **SFace**). Lựa chọn cặp YuNet + SFace giúp hệ thống tận dụng ngay thư viện OpenCV đang có sẵn cho luồng camera mà không phải cài đặt thêm bất kỳ gói phụ thuộc ngoại lai nào, đồng thời đạt thời gian thực thi trọn đường ống chỉ **`86,1 ms`** (tương đương `11,6 lượt/giây` ở cấu hình thu nhỏ thử nghiệm, **ĐÃ ĐO**).

### 6.2. Phát hiện 5 điểm mốc bằng YuNet và lựa chọn ngưỡng `score_threshold = 0,7`

Ở mỗi chu kỳ kiểm tra danh tính cách nhau `face.interval_s = 2,0 giây`, khung hình BGR `704×576` được đưa vào `cv2.FaceDetectorYN`. Mỗi khuôn mặt phát hiện được trả về dưới dạng một hàng gồm `15 số thực`: tọa độ hộp bao `(x, y, w, h)`, tọa độ `(x, y)` của **5 điểm mốc khuôn mặt** (tâm mắt phải, tâm mắt trái, đỉnh mũi, khóe miệng phải, khóe miệng trái) và điểm tin cậy phát hiện cuối cùng. Các hộp mặt quá nhỏ ở hậu cảnh xa có kích thước cạnh dưới `min_face_px = 40 px` bị loại bỏ ngay từ đầu; nếu khung hình có nhiều khuôn mặt hợp lệ, hệ thống chọn khuôn mặt có diện tích lớn nhất tương ứng với người đang ngồi gần bàn học nhất.

Một quyết định kỹ thuật quan trọng có căn cứ thực nghiệm tại khâu này là hạ tham số **`face.score_threshold` xuống `0,70`** thay vì giữ mức mặc định `0,90` của tài liệu mẫu OpenCV. Bảng 14 trình bày kết quả đo đối chiếu trực tiếp giữa hai mức ngưỡng trên camera của dự án (**ĐÃ ĐO**).

*Bảng 14. Kết quả đo thực nghiệm tỷ lệ phát hiện khuôn mặt của YuNet giữa ngưỡng mặc định `0,9` và ngưỡng chọn `0,7`*

| Tập mẫu kiểm chứng thực tế | Tỷ lệ giữ được mặt ở `score_threshold = 0,9` | Tỷ lệ giữ được mặt ở `score_threshold = 0,7` | Phân bố điểm tin cậy quan sát được (**ĐÃ ĐO**) |
|---|---|---|---|
| **10 ảnh tĩnh sạch** (độ phân giải `640×480`, `704×576`, `1280×720`, cùng một người ngồi bàn) | `7 / 10 ảnh` (`70%`) | **`10 / 10 ảnh` (`100%`)** | Khuôn mặt thật đạt điểm **`0,862 - 0,928`**; hộp nhiễu ứng viên cao nhất kế tiếp chỉ đạt **`0,451`** |
| **Chuỗi 14 khung hình động** khi người học đưa bàn tay lên che một phần khuôn mặt / chống cằm | `2 / 14 khung` (`14,3%`) | **`8 / 14 khung` (`57,1%`)** | Khoảng trống phân tách giữa mặt thật và nhiễu rộng hơn `0,40` đơn vị; mốc `0,70` cách nhiễu `0,25` và cách mặt thật `0,16` |

Số liệu tại Bảng 14 cho thấy ngưỡng `0,90` quá khắt khe ngay cả với ảnh tĩnh bình thường (bỏ sót `30%` số mẫu có điểm quanh `0,86-0,89`), trong khi mốc `0,70` nằm an toàn ở chính giữa vùng trống phân tách tự nhiên giữa khuôn mặt thật và nhiễu nền, giúp tăng gấp bốn lần khả năng duy trì nhận diện khi người học chống tay lên má trong giờ học.

### 6.3. Trích xuất vector 128 chiều bằng SFace và cơ chế phân loại ba trạng thái

Từ hàng tọa độ 5 điểm mốc của YuNet, phương thức `cv2.FaceRecognizerSF.alignCrop(frame, face_row)` thực hiện phép biến đổi afin chuẩn hóa hình học (xoay thẳng trục hai mắt và co giãn đồng nhất) để cắt ra ảnh khuôn mặt chuẩn kích thước **`112×112 pixel`**. Ảnh chuẩn hóa này tiếp tục đi qua mạng `SFace` (`feature()`) để sinh ra một vector đặc trưng `float32` gồm **`128 chiều`** (dung lượng đúng `512 byte`), sau đó được chuẩn hóa độ dài đơn vị theo chuẩn Euclid $L_2$ ($\|\mathbf{v}\|_2 = 1$). Nhờ chuẩn hóa $L_2$, độ tương đồng cosine giữa vector khuôn mặt hiện tại $\mathbf{u}$ và vector mẫu đã đăng ký $\mathbf{v}_k$ trong kho rút gọn thành tích vô hướng đơn giản $s_k = \mathbf{u} \cdot \mathbf{v}_k \in [-1, 1]$.

Điểm khác biệt cốt lõi nhất trong thiết kế của đề tài so với các bài hướng dẫn nhận diện mặt thông thường là việc **phân loại đầu ra thành ba trạng thái ngữ nghĩa độc lập (`MATCH`, `MISMATCH`, `UNKNOWN`) thay vì hai trạng thái nhị phân**. Quy tắc quyết định và tác động của từng trạng thái lên máy cảnh báo được quy định rõ trong Bảng 15.

*Bảng 15. Cơ chế phân loại danh tính ba trạng thái và nguyên lý chống báo động oan*

| Trạng thái danh tính | Điều kiện kích hoạt trong `PeopleService` | Hiển thị trên Web & App | Tác động lên bộ đếm cảnh báo người lạ |
|---|---|---|---|
| **`MATCH`** *(Đúng người)* | Phát hiện được mặt hợp lệ và điểm cosine lớn nhất vượt ngưỡng khớp với đúng người học đang được chọn cho phiên | Nhãn xanh: `Đúng người (<Tên>)` | Xóa bộ đếm vi phạm danh tính, duy trì trạng thái học bình thường |
| **`MISMATCH`** *(Khác người)* | Phát hiện rõ khuôn mặt hợp lệ, kho mẫu không rỗng, nhưng điểm cosine thuộc về một người khác trong kho hoặc thấp hơn ngưỡng khớp của người đang chọn | Nhãn đỏ: `Khác người` | Tích lũy thời gian vi phạm; nếu duy trì liên tục vượt `stranger.hold_s = 5,0 s` thì phát cảnh báo ra loa camera |
| **`UNKNOWN`** *(Chưa nhận ra)* | Không thấy khuôn mặt trong khung (do cúi gằm viết bài, quay lưng), kích thước mặt `< 40 px`, kho chưa đăng ký ai, chưa chọn người học, hoặc tín hiệu đã hết hạn | Nhãn vàng/trung tính: `Chưa nhận ra` (kèm lý do cụ thể) | **Không cộng dồn vào bộ đếm người lạ**; giữ nguyên kết luận hợp lệ trước đó mà không gây báo động giả |

Triết lý kỹ thuật đứng sau Bảng 15 rất rõ ràng: trong bối cảnh giám sát hỗ trợ tự học, **lỗi kết tội nhầm chủ nhân đang cúi viết bài là "người lạ ngồi học hộ" gây ức chế nghiêm trọng hơn nhiều so với việc trễ vài giây khi chưa nhìn rõ mặt**. Nhờ trạng thái trung gian `UNKNOWN`, mọi tình huống che mặt tạm thời, ngược sáng hoặc quay đầu tra từ điển đều đi vào nhánh trung tính an toàn chứ không bao giờ kích hoạt nhầm cảnh báo `IMPOSTOR`.

### 6.4. Quy trình đăng ký 5 tư thế khuôn mặt và tự suy ngưỡng cosine an toàn

Để thêm một người học mới vào hệ thống mà không cần dùng dòng lệnh hay huấn luyện mô hình, phân hệ `domain/enrollment.py` và `domain/people_service.py` cung cấp quy trình đăng ký tương tác giống trải nghiệm mở khóa khuôn mặt trên điện thoại thông minh, gồm **5 bước hướng dẫn tư thế tuần tự**:

1. **Bước 1:** Nhìn thẳng vào ống kính camera (`1,5 giây`).
2. **Bước 2:** Quay nhẹ mặt sang bên phải (`1,5 giây`).
3. **Bước 3:** Quay nhẹ mặt sang bên trái (`1,5 giây`).
4. **Bước 4:** Ngẩng nhẹ đầu lên trên (`1,5 giây`).
5. **Bước 5:** Cúi nhẹ đầu xuống dưới (`1,5 giây`).

Ở mỗi bước, bộ theo dõi `EnrollmentTracker` thu tối đa một vector đặc trưng 128 chiều đạt chuẩn chất lượng. Kết thúc 5 bước (`~7,5 giây`), hệ thống kiểm tra điều kiện toàn vẹn: phải thu được **tối thiểu `3/5 mẫu` hợp lệ** mới chấp nhận ghi hồ sơ vào `data/faces.json`; nếu thiếu mẫu (do người dùng bước ra ngoài hoặc phòng quá tối), phiên quét bị hủy bỏ kèm thông báo lỗi tiếng Việt rõ ràng và không ghi rác vào kho dữ liệu. Toàn bộ khung hình dùng trong lúc quét đều bị hủy ngay trên RAM sau khi rút trích xong vector `512 byte`.

Đặc biệt, trong tệp cấu hình gốc `config.yaml`, tham số `face.match_threshold` được chủ đích đặt là **`null`**. Quyết định này tuân thủ kỷ luật số liệu của đề tài: khi chưa thực hiện bài đo thống kê phân bố khoảng cách trong-cùng-người và khác-người bằng `scripts/face_threshold_probe.py` tại đúng góc ánh sáng lắp đặt, hệ thống tuyệt đối không chép bừa con số `0,363` từ tài liệu mẫu OpenCV vào làm hằng số cứng. Thay vào đó, lớp `ThresholdManager` tự động suy diễn ngưỡng an toàn nội bộ từ chính độ tương đồng cặp thấp nhất giữa các mẫu 5 góc mặt vừa đăng ký (trừ biên dự phòng và kẹp chặt trong đoạn `[0,30; 0,95]`), rồi lưu xuống `data/face_threshold.json`. Khi người triển khai đã chạy công cụ đo thực tế và điền một con số cụ thể vào `config.yaml`, giá trị cấu hình tường minh sẽ luôn được ưu tiên cao nhất.

### 6.5. Tuân thủ nguyên tắc bảo vệ dữ liệu sinh trắc học cá nhân

Theo quy định tại Nghị định `13/2023/NĐ-CP` về bảo vệ dữ liệu cá nhân tại Việt Nam, đặc trưng sinh trắc học khuôn mặt thuộc nhóm **dữ liệu cá nhân nhạy cảm**. Mặc dù phạm vi đồ án chỉ vận hành khép kín trong mạng nội bộ phòng thí nghiệm/gia đình, kiến trúc của module đã tích hợp sẵn bốn biện pháp bảo vệ từ gốc thiết kế (`Privacy by Design`):

- Không lưu trữ ảnh gốc hay ảnh cắt khuôn mặt `112×112` dưới bất kỳ hình thức nào trên thẻ nhớ; một người học đăng ký đủ 5 góc mặt chỉ chiếm khoảng `2,5 KB` dữ liệu số thực trong `data/faces.json` và không thể khôi phục ngược trực tiếp thành bức ảnh chụp thông thường.
- Thao tác xóa người học qua endpoint `DELETE /api/people/<id>` thực hiện xóa thật toàn bộ vector của người đó khỏi RAM và ghi đè nguyên tử xuống đĩa ngay lập tức, đồng thời tính toán lại ngưỡng khớp tự động.
- Hai lớp lọc trắng trường công khai `(id, name, created_ts)` kết hợp hàm `scrub_biometrics()` đảm bảo vector 128 chiều không bao giờ lọt ra ngoài qua bất kỳ phản hồi HTTP JSON nào.
- Ghi nhận rõ ràng về mặt vận hành: các biện pháp kỹ thuật trên giúp giảm thiểu tối đa bề mặt rủi ro rò rỉ, nhưng khi triển khai thực tế ngoài phạm vi thử nghiệm cá nhân vẫn bắt buộc phải có sự đồng ý minh bạch của người được đăng ký khuôn mặt.

### 6.6. Nhận xét và hạn chế kỹ thuật của module

Sự kết hợp giữa YuNet (`score_threshold = 0,7`), SFace 128 chiều và mô hình quyết định ba trạng thái `MATCH / MISMATCH / UNKNOWN` giúp module danh tính vận hành mượt mà, nhẹ nhàng trên Raspberry Pi 4 mà không gây báo động giả khi người học chuyển động đầu tự nhiên.

Ba giới hạn kỹ thuật hiện hữu của module gồm: (1) hệ thống chưa tích hợp lớp kiểm tra thực thể sống (`liveness detection / anti-spoofing`), do đó nếu một người cố tình giơ bức ảnh chân dung in sẵn hoặc mở ảnh chủ nhân trên máy tính bảng trước ống kính thì SFace vẫn kết luận `MATCH`; (2) khi hai anh chị em ruột có khuôn mặt rất giống nhau cùng sử dụng chung một bàn học, ngưỡng tự suy từ một người có thể chưa đủ chặt và cần chạy `scripts/face_threshold_probe.py` với cả hai người để chọn ngưỡng phân tách tối ưu; và (3) trong điều kiện phòng học tắt đèn chính chỉ bật một đèn bàn chiếu ngược gắt từ phía sau lưng, chưa có bước cân bằng sáng `CLAHE` trên đường chạy thật nên tỷ lệ rơi vào trạng thái `UNKNOWN` sẽ tăng lên.

### 6.7. Kết chương

Chương 6 đã hoàn tất việc trình bày module nhận diện thứ ba của tầng AI biên, giải quyết trọn vẹn bài toán đăng ký 5 góc mặt không cần huấn luyện lại và xác thực danh tính ba trạng thái có bảo vệ dữ liệu sinh trắc học. Như vậy, toàn bộ ba câu hỏi nghiệp vụ cốt lõi đặt ra ở Chương 1 (hiện diện, sử dụng điện thoại và danh tính người học) đã được giải đáp đầy đủ ở tầng thuật toán thị giác qua các Chương 4, 5 và 6.

Để biến các kết luận số học trên RAM thành tiếng nhắc nhở thực tế phát ra trong phòng học, xoay góc quan sát của ống kính và ghi nhận nhật ký bền vững trên thẻ nhớ mà không làm quá nhiệt vi xử lý, Chương 7 tiếp theo sẽ trình bày chi tiết việc triển khai tầng phần cứng Raspberry Pi 4, giao thức âm thanh ngược RTSP backchannel, điều khiển ONVIF PTZ và mạch ngoại vi GPIO.

## CHƯƠNG 7. TRIỂN KHAI PHẦN CỨNG RASPBERRY PI 4, LOA CAMERA BACKCHANNEL, PTZ VÀ GPIO

### 7.1. Sơ đồ chuỗi phần cứng và phân vai kênh cảnh báo

Tầng phần cứng vật lý của hệ thống được tổ chức xoay quanh hai nút thiết bị chính nối với nhau qua mạng cục bộ (Ethernet hoặc Wi-Fi nội bộ): camera IP thông minh đặt trước bàn học và máy tính nhúng một bo mạch Raspberry Pi 4 Model B (4 GB RAM) đóng vai trò nút xử lý biên trung tâm. Cấu trúc kết nối vật lý và luồng tín hiệu vào/ra của toàn hệ thống phần cứng như sau:

```text
Camera IP mạng LAN (RTSP luồng phụ /1/2 + Loa tích hợp + Động cơ PTZ)
   ├── [Chiều lên - RTSP cổng 554]   Luồng hình 704x576 @ 20 fps, nén HEVC
   ├── [Chiều xuống - RTP/PCMA 554]  Âm thanh cảnh báo 8.000 Hz phát ra loa camera
   └── [Điều khiển - ONVIF cổng 80]  Lệnh xoay ống kính trái / phải / lên / xuống
         │
         ▼
Raspberry Pi 4 Model B Rev 1.5 (4 GB RAM, Raspberry Pi OS Trixie aarch64)
   ├── Cụm GPIO (gpiozero): 3 đèn LED trạng thái, còi buzzer, mô-tơ rung (kênh phụ)
   ├── Cảm biến siêu âm HC-SR04: đo khoảng cách ngực - bàn (tùy chọn mở rộng)
   └── Thẻ nhớ microSD: SQLite chế độ WAL + kho vector khuôn mặt faces.json
```

Một quyết định kiến trúc phần cứng quan trọng của đề tài là chọn **loa tích hợp sẵn bên trong camera IP làm kênh cảnh báo âm thanh chính**, trong khi cụm linh kiện rời gắn trên chân cắm GPIO (đèn LED, còi chip buzzer, mô-tơ rung) được định vị làm kênh chỉ thị phụ trợ với cờ âm thanh mặc định tắt (`alerts.gpio_alert_enabled: false`). Thiết kế này giúp hệ thống triển khai gọn gàng tại bàn học chỉ với một sợi dây nguồn cho camera và bo mạch Pi đặt khuất góc phòng, không bắt buộc người dùng phải hàn mạch khuếch đại âm thanh rời mà vẫn phát được lời nhắc tiếng Việt rõ ràng ngay trước mặt người học.

### 7.2. Quản lý nhiệt độ, nguồn điện và cờ hãm xung nhịp trên Raspberry Pi 4

Trên dòng vi xử lý Broadcom BCM2711 của Raspberry Pi 4, ngưỡng nhiệt độ **`80,0 °C`** không phải là một mốc khuyến cáo cảm tính mà chính là **biên dưới cứng của cơ chế tự động hãm xung nhịp (`thermal throttling`)** trong firmware hệ thống: khi nhiệt độ nhân chạm khoảng `80 - 85 °C`, tần số xung nhịp CPU bị ép giảm bậc thang để tự bảo vệ, và vượt ngưỡng `85 °C` thì cả khối CPU lẫn GPU đều bị cắt giảm mạnh. Bất kỳ phép đo tốc độ FPS nào thực hiện khi bo mạch đang bị hãm xung hoặc sụt áp nguồn (`under-voltage`) đều cho ra các con số sai lệch nghiêm trọng không có giá trị khoa học.

Do đó, hệ thống bắt buộc trang bị cụm tản nhiệt nhôm kèm quạt làm mát cho Raspberry Pi 4 và tích hợp bộ giám sát phần cứng định kỳ mỗi `5 giây` thông qua lệnh hệ thống `vcgencmd get_throttled`. Trong suốt bài đo tải thực tế kéo dài `60 giây` trên bo mạch của dự án, nhiệt độ CPU chỉ tăng nhẹ từ mức nghỉ **`55,0 °C`** lên **`58,0 °C`** (đỉnh cực đại **`58,9 °C`**, còn cách ngưỡng nguy hiểm hơn `21 °C`), mức chiếm dụng bộ nhớ RAM đỉnh đạt **`464,0 MiB`** trên tổng số `3.795 MB` khả dụng, và thanh ghi `get_throttled` luôn giữ giá trị tuyệt đối sạch là **`0x0`** (**ĐÃ ĐO**). Trong công cụ đo kiểm của dự án, nếu phát hiện bất kỳ bit cảnh báo nào bật lên (chẳng hạn bit `0x4` đang hãm xung hoặc `0x40000` từng xảy ra hãm xung), toàn bộ lượt đo đó sẽ bị tự động gắn nhãn `"KHÔNG KẾT LUẬN"` thay vì chấp nhận kết quả.

### 7.3. Phát cảnh báo tiếng Việt qua loa camera IP bằng giao thức RTSP Backchannel

Để truyền âm thanh ngược từ Raspberry Pi 4 tới loa của camera IP mà không cần phần mềm đám mây độc quyền của hãng sản xuất camera, mô-đun `camera/audio.py` và `alerts/speaker_alert.py` triển khai giao thức **RTSP Backchannel theo hồ sơ ONVIF Profile T** trên cổng `554`. Khi bắt đầu phát thông báo, hệ thống gửi bản tin thương lượng `DESCRIBE` kèm trường tiêu đề `Require: www.onvif.org/ver20/backchannel` để mở kênh truyền tải RTP chiều xuống và đẩy các gói tin âm thanh đã mã hóa G.711. Các thông số giao thức và bằng chứng thực thi thực tế trên phần cứng được tổng hợp tại Bảng 16.

*Bảng 16. Thông số kỹ thuật kênh âm thanh ngược RTSP Backchannel và bằng chứng chạy thật*

| Hạng mục kỹ thuật | Giá trị thiết lập và vận hành | Ghi chú kiểm chứng trên thiết bị thật |
|---|---|---|
| Giao thức điều khiển và truyền tải | RTSP `DESCRIBE / SETUP / PLAY` + đóng gói `RTP` qua cổng **`554`** | Xác thực Digest/Basic tự động từ cấu hình camera |
| Chuẩn mã hóa âm thanh (`Codec`) | ITU-T G.711 **PCMA** (`A-law`, 8-bit) và **PCMU** (`µ-law`) | Camera dự án thương lượng thành công chế độ `PCMA` |
| Tần số lấy mẫu và cấu trúc gói | **`8.000 Hz`**, đơn kênh (`1 channel`), `320 mẫu/gói` = **`40 ms/gói`** | Định thời gửi gói chính xác để không tràn bộ đệm loa camera |
| Bằng chứng kết quả thực thi (**ĐÃ ĐO**) | `SpeakResult(mode='tone', codec='PCMA', sample_rate=8000, packets_sent=20, duration_seconds=0.8)` | Âm thanh phát rõ ràng trực tiếp trên loa camera IP |
| Thứ tự ưu tiên thông điệp vi phạm | **`stranger` (người lạ) > `leave_frame` (vắng mặt) > `phone` (điện thoại)** | Vi phạm danh tính nghiêm trọng nhất luôn được ưu tiên phát trước |

Trong quá trình thiết kế bộ điều phối loa, ba quyết định kỹ thuật quan trọng đã được áp dụng để bảo vệ độ ổn định của toàn hệ thống:

- **Chính sách từ chối tức thì khi loa bận (`Non-blocking Busy Policy`):** Phần cứng camera IP chỉ cho phép duy trì duy nhất một phiên backchannel tại một thời điểm. Bộ điều khiển âm thanh sử dụng một khóa `threading.Lock` ở chế độ không chờ (`acquire(blocking=False)`): nếu loa đang phát dở một câu nhắc mà có yêu cầu thứ hai gửi tới, lời gọi thứ hai nhận ngay ngoại lệ `CameraAudioBusy` và endpoint HTTP `/api/speak` trả về mã trạng thái **`409 Conflict`** tức thì thay vì xếp hàng chờ. Nếu cho phép các luồng HTTP đứng chờ khóa loa kéo dài `5-10 giây`, toàn bộ luồng phục vụ của máy chủ Flask sẽ bị nghẽn cứng khi người dùng bấm nút liên tục.
- **Kiểm tra sớm công cụ chuyển mã `ffmpeg`:** Đối với thao tác phát tệp `.wav` giọng người (`speak_file`), hệ thống kiểm tra `shutil.which("ffmpeg")` ngay đầu hàm. Trên Raspberry Pi 4 đã cài đặt sẵn `ffmpeg` nên hệ thống phát giọng thu âm tự nhiên; trên máy phát triển Windows không cài `ffmpeg`, hệ thống chủ động bắt thiếu hụt và tự động rơi xuống nhánh sinh âm bíp thuần Python (`speak_tone`) chứ không bao giờ ném lỗi `FileNotFoundError` làm hỏng vòng lặp.
- **Tách bạch trạng thái tắt tiếng (`muted`) và ghi nhận lịch sử:** Khi người học bật chế độ tắt tiếng trên Web hoặc Ứng dụng di động (`muted = True`), bộ điều phối chặn lệnh phát âm thanh ngay trước khi chạm tới đối tượng điều khiển loa, nhưng **vẫn ghi đầy đủ bản ghi sự kiện vi phạm vào cơ sở dữ liệu SQLite**. Mọi lỗi mạng phát sinh trong lúc truyền gói RTP đều được bắt gọn và ghi nhật ký loại `SPEAK_FAILED`, đảm bảo sự cố loa không bao giờ làm dừng luồng đọc camera.

### 7.4. Điều khiển xoay camera bốn hướng qua giao thức ONVIF HTTP

Để hỗ trợ người học điều chỉnh góc nhìn của camera sao cho thấy rõ cả khuôn mặt và mặt bàn ngay từ trình duyệt hoặc điện thoại, mô-đun `camera/control.py` tích hợp thư viện thuần Python `rtsp-backchannel==0.5.2` giao tiếp với dịch vụ điều khiển cơ điện **ONVIF PTZ (`Pan-Tilt-Zoom`)**. Thông số vận hành và kết quả xác nhận trên phần cứng được trình bày trong Bảng 17.

*Bảng 17. Thông số giao thức điều khiển xoay camera ONVIF PTZ và kết quả kiểm chứng*

| Tham số điều khiển | Giá trị áp dụng trong hệ thống | Ý nghĩa và cơ chế an toàn |
|---|---|---|
| Endpoint dịch vụ ONVIF | `http://{host}:{port}/onvif/device_service` (cổng HTTP **`80`**) | Khác biệt hoàn toàn với cổng `554` của luồng hình/tiếng RTSP |
| Chu trình lệnh mỗi bước bấm | `continuous_move(PtzVector(dx, dy), timeout_ms)` -> `stop()` -> `close()` | Khối `stop()` bắt buộc đặt trong mệnh đề `finally` |
| Vector hướng di chuyển `(dx, dy)` | Trái `(-1, 0)` · Phải `(1, 0)` · Lên `(0, 1)` · Xuống `(0, -1)` | Điều khiển hai trục quay ngang (`Pan`) và gật dọc (`Tilt`) |
| Giới hạn thời lượng mỗi xung xoay | Mặc định `0,5 giây` (từ giao diện gửi `0,4 giây`), kẹp biên **`[0,05 s .. 3,0 s]`** | Bấm giữ trên giao diện sẽ gửi chuỗi xung ngắn liên tiếp thay vì một lệnh mở vô hạn |
| Bằng chứng trạng thái phần cứng (**ĐÃ ĐO**) | `PtzStatus(pan_tilt=PtzVector(x=-0.008833, y=0.856344), zoom=0.0)` | Ống kính camera quay thực tế mượt theo cả bốn hướng |

Quá trình đưa tính năng PTZ vào hoạt động thực tế đã để lại ba bài học kỹ thuật sâu sắc được mã hóa thẳng vào phần mềm: (1) phải truyền tường minh số hiệu cổng vào chuỗi URL ONVIF vì nếu để thư viện tự suy diễn, các camera đặt dịch vụ ONVIF ở cổng khác `80` sẽ thất bại im lặng; (2) lệnh dừng động cơ `stop()` bắt buộc nằm trong khối `finally` để ngay cả khi tiến trình bị ngắt giữa chừng, ống kính vẫn đứng yên thay vì quay kịch biên cơ khí; và (3) do thư viện nền ném cùng một kiểu ngoại lệ `RuntimeError` cho cả lỗi "thiết bị không hỗ trợ PTZ" lẫn lỗi "mất kết nối mạng", tầng xử lý phải phân tích nội dung thông điệp lỗi để trả đúng mã HTTP **`501 Not Implemented`** hay **`502 Bad Gateway`**, giúp người vận hành chẩn đoán trúng nguyên nhân.

### 7.5. Giao tiếp mạch ngoại vi GPIO bằng `gpiozero` và cảm biến siêu âm HC-SR04

Bên cạnh kênh cảnh báo qua mạng LAN, hệ thống hỗ trợ đầy đủ giao tiếp phần cứng mức thấp qua hàng rào 40 chân cắm của Raspberry Pi 4 phục vụ chỉ thị đèn trạng thái tại chỗ và đo khoảng cách siêu âm bổ trợ. Hình 4 thể hiện sơ đồ đấu nối các linh kiện ngoại vi theo quy ước đánh số chân BCM (`Broadcom SOC channel`).

![Sơ đồ đấu dây ngoại vi GPIO](figures/07-so-do-dau-day.png)

*Hình 4. Sơ đồ đấu nối cụm đèn LED, còi buzzer, mô-tơ rung và cảm biến siêu âm HC-SR04 trên GPIO Raspberry Pi 4*

Chi tiết phân bổ chân tín hiệu BCM và các yêu cầu bảo vệ điện tử bắt buộc khi lắp ráp mạch được quy định trong Bảng 18.

*Bảng 18. Bảng phân bổ chân tín hiệu BCM và yêu cầu bảo vệ mạch điện cho ngoại vi GPIO*

| Linh kiện ngoại vi | Chân tín hiệu (BCM) | Vai trò hiển thị / đo lường | Yêu cầu kỹ thuật mạch điện bắt buộc |
|---|---|---|---|
| **LED Xanh lá** (`GOOD`) | **GPIO 17** | Sáng khi người học ngồi đúng trạng thái ổn định | Mắc nối tiếp điện trở hạn dòng `220 - 330 Ω` |
| **LED Vàng** (`WARN`) | **GPIO 27** | Sáng khi mới chớm lệch ngưỡng, đang trong thời gian giữ | Mắc nối tiếp điện trở hạn dòng `220 - 330 Ω` |
| **LED Đỏ** (`BAD`) | **GPIO 22** | Sáng khi xác nhận sự kiện vi phạm kéo dài | Mắc nối tiếp điện trở hạn dòng `220 - 330 Ω` |
| **Còi Buzzer chủ động** | **GPIO 18** | Phát 2 nhịp bíp khi `BAD`, 3 nhịp bíp khi nhắc giải lao `BREAK` | Kích qua transistor NPN nếu dòng tiêu thụ vượt `16 mA` |
| **Mô-tơ rung mini** | **GPIO 23** | Rung phản hồi xúc giác `300 ms` khi có cảnh báo | **Bắt buộc** dùng transistor NPN kèm diode chống dòng ngược (`flyback`) |
| **Cảm biến HC-SR04 (`TRIG`)** | **GPIO 5** | Phát xung kích hoạt chùm sóng siêu âm đo khoảng cách | Ngõ ra số `3,3 V` của Pi kích được trực tiếp chân `TRIG` |
| **Cảm biến HC-SR04 (`ECHO`)** | **GPIO 6** | Thu độ rộng xung phản hồi tỷ lệ với khoảng cách ngực - bàn | **Bắt buộc dùng cầu chia áp `5 V -> 3,3 V`** (`1 kΩ` + `2 kΩ` cho `~3,33 V`); nối thẳng `5 V` sẽ đánh thủng chân GPIO của SoC |

Về mặt thư viện điều khiển trong `hardware/gpio_real.py` và `hardware/gpio_mock.py`, đề tài lựa chọn **`gpiozero` (`2.0.1.post3` chạy trên nền `lgpio`)** thay cho thư viện cũ `RPi.GPIO`. Lý do là trên hệ điều hành Debian Bookworm/Trixie nhân `6.18`, giao diện bộ nhớ `/dev/gpiomem` kiểu cũ mà `RPi.GPIO` dựa vào không còn tương thích ổn định; quan trọng hơn, `gpiozero` cung cấp sẵn nhà máy chân giả lập chính thức `MockFactory`. Khi chạy với cờ `--no-gpio` hoặc trong bộ kiểm thử tự động, hệ thống gắn `Device.pin_factory = MockFactory()`, đảm bảo về mặt vật lý không một dòng lệnh kiểm thử nào có thể vô tình kích điện ra chân cắm thật. Đối với cảm biến HC-SR04 (`hardware/sensors.py`), một luồng nền riêng lấy mẫu mỗi `0,5 giây`, tính **trung vị của 5 phép đo liên tiếp** cách nhau `50 ms` và lọc bỏ các giá trị nhiễu ngoài đoạn `[2, 200] cm`. Khi cảm biến chưa được cắm vào mạch (trạng thái hiện tại trên bàn thử nghiệm chỉ dùng camera IP), ngoại lệ `DistanceSensorNoEcho` được xử lý êm làm trạng thái bình thường (`read()` trả `None`), nhường quyền ước lượng độ gần cho chỉ số `closeness` từ bề rộng vai của camera.

### 7.6. Lưu trữ bền vững SQLite chế độ WAL và bảo vệ tuổi thọ thẻ nhớ microSD

Thẻ nhớ microSD trên các thiết bị nhúng IoT rất dễ bị suy giảm tuổi thọ hoặc lỗi hệ thống tệp nếu ứng dụng thực hiện thao tác mở giao dịch và gọi đồng bộ đĩa (`fsync`) ở từng khung hình (`5 lần/giây` tương đương `18.000 giao dịch/giờ`). Để khắc phục nhược điểm này đồng thời giải quyết xung đột đọc/ghi đa luồng với máy chủ Flask, lớp `Storage` trong `storage/sqlite_store.py` thiết lập bốn cơ chế bảo vệ:

1. **Bật chế độ `PRAGMA journal_mode = WAL` và `synchronous = NORMAL`:** Cho phép các luồng HTTP của Web và Ứng dụng di động thực hiện truy vấn đọc lịch sử vi phạm song song ngay trong lúc vòng lặp chính đang ghi lô dữ liệu mới mà không khóa chặn lẫn nhau (`busy_timeout = 5000 ms`, `foreign_keys = ON`).
2. **Cơ chế hàng đợi gom lô chu kỳ `10 giây` (`Batch Flushing`):** Các sự kiện phát sinh và bản ghi thống kê phút được đẩy vào hàng đợi trong RAM (có trần giới hạn `2.000 bản ghi` để không tràn bộ nhớ nếu đĩa gặp lỗi). Cứ mỗi `10 giây`, hệ thống mới mở một giao dịch tường minh duy nhất (`BEGIN IMMEDIATE` -> `executemany` -> `COMMIT`), rút giảm số lần ghi vật lý xuống thẻ nhớ hơn `50 lần`.
3. **Chính sách tự động dọn dữ liệu cũ (`Retention 30 ngày`) và khôi phục phiên mồ côi:** Ngay khi khởi động mở tệp cơ sở dữ liệu, hệ thống tự động xóa các bản ghi quá hạn `30 ngày` (luôn bảo toàn phiên đang mở có `end_ts IS NULL`), đồng thời rà soát các phiên bị bỏ dở do mất điện đột ngột ở lần chạy trước để đóng lại bằng dấu thời gian sự kiện cuối cùng, ngăn chặn hiện tượng hai phiên học chồng lấn thời gian.

### 7.7. Ma trận rủi ro phần cứng và giải pháp kiểm soát

Tổng hợp toàn bộ các điểm nhạy cảm khi vận hành phần cứng biên thực tế, Bảng 19 liệt kê mức độ nghiêm trọng và trạng thái giải pháp kiểm soát hiện có của từng rủi ro.

*Bảng 19. Ma trận nhận diện rủi ro phần cứng biên và biện pháp kiểm soát kỹ thuật*

| Rủi ro phần cứng / giao thức | Mức độ | Biện pháp kiểm soát và trạng thái hiện tại trong hệ thống |
|---|---|---|
| Quá nhiệt CPU (`>= 80 °C`) làm hãm xung sai lệch tốc độ FPS | **Cao** | **Đã kiểm soát:** Lắp tản nhiệt cưỡng bức (nhiệt đo thực tế `<= 58,9 °C`); công cụ benchmark kiểm tra tự động thanh ghi `get_throttled` |
| Đứt kết nối mạng RTSP giữa chừng gây treo lệnh đọc khung hình | **Cao** *(cần hoàn thiện)* | **Đã nhận diện rõ:** Bộ cờ FFmpeg hiện chưa đặt `timeout`/`stimeout` (từng ghi nhận một lần `read()` chờ tới `2.201 ms`); cần bổ sung hạn chờ cứng ở bản kế tiếp |
| Điện áp phản hồi `5 V` từ chân `ECHO` cảm biến HC-SR04 làm hỏng SoC | **Cao** | **Đã kiểm soát bằng tài liệu và sơ đồ:** Bắt buộc lắp cầu chia áp `1 kΩ + 2 kΩ` hạ về `~3,33 V` trước khi cấp vào `GPIO 6` |
| Mất gói UDP trên luồng nén HEVC gây trễ giải mã (`Could not find ref with POC`) | **Trung bình** | **Đã ghi nhận số đo:** Bốn lần đo độ trễ đọc RTSP cho phân vị `p95` dao động `255 / 490 / 725 / 887 ms` khi chờ khung khóa mới |
| Hao mòn ô nhớ Flash của thẻ microSD khi chạy dài ngày | **Thấp - TB** | **Đã kiểm soát:** Gom lô giao dịch `10 giây`, bật `WAL` + `synchronous = NORMAL` và tự động dọn dữ liệu sau `30 ngày` |
| Sai lệch màu đỏ/xanh khi gắn thêm module Pi Camera CSI | **Thấp** | **Đã kiểm soát:** Cấu hình cứng định dạng `RGB888` trên `picamera2` để xuất đúng thứ tự byte BGR mà OpenCV yêu cầu |

### 7.8. Kết chương

Chương 7 đã trình bày toàn diện cách hệ thống kết nối và điều khiển thế giới vật lý từ bo mạch Raspberry Pi 4: đảm bảo biên độ an toàn nhiệt rộng rãi (`58,9 °C`, `throttled = 0x0`), phát lời nhắc tiếng Việt trực tiếp qua loa camera bằng RTSP backchannel PCMA 8 kHz, xoay góc ống kính qua ONVIF HTTP cổng `80`, điều khiển ngoại vi GPIO an toàn với `gpiozero` và bảo vệ thẻ nhớ bằng SQLite chế độ `WAL`.

Trên nền tảng phần cứng và tầng suy luận AI đã vận hành trơn tru đó, người học cần một giao diện trực quan, tin cậy để bắt đầu phiên học, quan sát luồng camera cùng các thông số nhận diện và tra cứu lịch sử vi phạm trên cả máy tính lẫn điện thoại di động. Chương 8 tiếp theo sẽ trình bày chi tiết thiết kế tầng dịch vụ Web Dashboard, Ứng dụng di động React Native/Expo và kịch bản vận hành đầu-cuối.

## CHƯƠNG 8. TRIỂN KHAI WEB DASHBOARD, ỨNG DỤNG DI ĐỘNG EXPO VÀ KỊCH BẢN VẬN HÀNH

### 8.1. Kiến trúc máy chủ Flask phân mô-đun và kho trạng thái chia sẻ `DashboardState`

Tầng giao tiếp dịch vụ được xây dựng bằng khung ứng dụng **Flask `3.1.3`** đặt trong phân hệ `src/posture_monitor/web/`, tổ chức theo kiến trúc tiêm phụ thuộc sạch thay vì sử dụng các biến toàn cục rải rác. Hàm khởi tạo `create_app()` (`web/app.py`) đóng gói các dịch vụ miền được truyền vào thành một đối tượng ngữ cảnh `WebContext` (`web/context.py`) và đăng ký năm mô-đun endpoint chuyên biệt trong thư mục `web/routes/` gồm: `core.py` (trang chủ, trạng thái tổng hợp, lịch sử, tắt tiếng, hiệu chỉnh), `diagnostics.py` (xoay PTZ, phát thử loa, chọn giọng đọc), `session.py` (điều khiển phiên học, lịch học theo tuần, danh sách vi phạm), `media.py` (luồng MJPEG trực tiếp và khung ảnh tĩnh JPEG) và `people.py` (quản lý người học, quét 5 tư thế mặt, truy vấn 3 tín hiệu). Hình 5 minh họa vai trò cầu nối trung tâm của đối tượng `DashboardState` giữa vòng lặp camera và tầng dịch vụ HTTP.

![Kiến trúc tầng dịch vụ Web](figures/05-kien-truc-web.png)

*Hình 5. Kiến trúc tầng dịch vụ Flask với `DashboardState` làm khe hẹp trao đổi dữ liệu duy nhất*

Như thể hiện trên Hình 5, mọi trao đổi dữ liệu giữa luồng xử lý thị giác (`MonitorRunner`) và hàng chục luồng phục vụ khách hàng HTTP đều đi qua một khóa đồng bộ duy nhất bên trong `DashboardState` (`web/state.py`). Cấu trúc các vùng dữ liệu và cơ chế bảo vệ không gây nghẽn của `DashboardState` được tóm tắt tại Bảng 20.

*Bảng 20. Cấu trúc dữ liệu và cơ chế đồng bộ không chặn trong kho trạng thái `DashboardState`*

| Thành phần lưu trữ | Dữ liệu nắm giữ | Cơ chế đồng bộ và bảo vệ an toàn |
|---|---|---|
| **Bảy khóa trạng thái cố định** | `state`, `labels`, `score`, `sitting_s`, `distance_cm`, `alert`, `message` | Kiểm tra tên khóa chặt chẽ; mọi khóa lạ truyền nhầm đều bị từ chối kèm nhật ký `DEBUG` |
| **Vùng đệm khung hình đơn** | Mảng byte JPEG `_frame` và số thứ tự tăng dần `_frame_seq` | Chỉ giữ đúng **1 khung mới nhất** trên RAM; phương thức `wait_frame()` ngủ từng nhịp `50 ms` (tối đa `2,0 s`) và **nhả khóa trong lúc ngủ** để khách hàng mạng chậm không bao giờ chặn vòng lặp camera |
| **Cờ điều khiển chiều xuống** | Trạng thái tắt tiếng `muted` và yêu cầu hiệu chỉnh `_calibrate_req` | `muted` đọc bất biến; `consume_calibration_request()` đọc-và-xóa nguyên tử đúng một lần duy nhất |
| **Giám sát độ tươi toàn cục** | Dấu thời gian cập nhật cuối cùng so với ngưỡng `STALE_AFTER_S = 10,0 s` | Quá `10,0 giây` không có nhịp đập từ vòng lặp chính thì tự động gắn cờ `stale = True` báo động giao diện |

Bên cạnh đó, toàn bộ `24 endpoint HTTP` đều thống nhất chuẩn phản hồi lỗi có chủ đích: khi một tính năng bị tắt trong cấu hình (ví dụ `face.enabled: false` làm `PeopleService` mang giá trị `None`), các route liên quan trả về mã **`503 Service Unavailable`** kèm cấu trúc JSON nhất quán `{"ok": false, "message": "<thông báo tiếng Việt rõ nghĩa>"}`, tuyệt đối không để rò rỉ dấu vết ngăn xếp lỗi (`stack traceback`) của Python ra phía trình duyệt.

### 8.2. Thiết kế luồng MJPEG `/stream` và xử lý khung chờ hợp lệ chuẩn giao thức

Endpoint `GET /stream` (`web/streaming.py`) phục vụ video thời gian thực cho cả thẻ `<img>` trên trình duyệt Web lẫn thành phần `WebView` trên ứng dụng di động thông qua kiểu nội dung `multipart/x-mixed-replace; boundary=frame`. Mỗi khách hàng kết nối được cấp phát một hàm sinh (`generator`) riêng biệt chạy vòng lặp chờ khung hình có số thứ tự `_frame_seq` mới hơn rồi đẩy mảng byte JPEG qua kết nối HTTP giữ mở.

Một chi tiết kỹ thuật tinh tế thường bị bỏ sót trong các dự án phát video MJPEG là quy định nghiêm ngặt của trình duyệt đối với luồng đa phần: **mọi phần tử con nằm giữa các ranh giới `--frame` bắt buộc phải là dữ liệu ảnh `image/jpeg` hợp lệ**; nếu máy chủ chèn một chuỗi văn bản thông báo `"Đang kết nối camera..."` vào giữa luồng, bộ giải mã ảnh của trình duyệt sẽ lập tức báo lỗi hỏng hình và ngừng hiển thị vĩnh viễn cho tới khi tải lại trang. Để xử lý sạch bài toán này, ngay khi khởi động chưa có khung hình đầu tiên từ camera, hệ thống tự động dựng sẵn trên RAM một **ảnh JPEG nền xám kích thước `320×240` hợp lệ** để trả về ngay lập tức; nếu quá `5,0 giây` không nhận được khung mới từ vòng lặp, hệ thống chỉ ghi cảnh báo `WARNING` đúng một lần duy nhất vào nhật ký rồi phát lặp lại khung hợp lệ cuối cùng để duy trì kết nối sống.

### 8.3. Giao diện Web Dashboard tiếng Việt theo triết lý Offline-first

Giao diện Web tại endpoint `GET /` được viết hoàn toàn bằng HTML5, CSS3 và JavaScript thuần đặt nội bộ trong `web/templates/` và `web/static/`, không sử dụng bất kỳ khung giao diện cồng kềnh hay đường dẫn CDN bên ngoài nào. Ba tệp phông chữ `Geist` định dạng nén `woff2` (có phân mảnh `unicode-range` riêng cho bảng chữ cái tiếng Việt) và biểu tượng trang dạng `data: URI` được đóng gói sẵn tại chỗ, giúp trang quản trị tải tức thì trong mạng LAN cô lập không có Internet. Hình 6 và Hình 7 là ảnh chụp màn hình vận hành thực tế của Dashboard trên Raspberry Pi 4 và trên trình duyệt điện thoại di động.

![Giao diện Web Dashboard trên màn hình rộng](figures/09-dashboard-pi.png)

*Hình 6. Giao diện Web Dashboard thực tế vận hành trên Raspberry Pi 4 (độ phân giải 1440×1000)*

![Giao diện Web Dashboard đáp ứng trên điện thoại](figures/10-dashboard-phone.png)

*Hình 7. Giao diện Web Dashboard tự động đảo thứ tự ưu tiên trên màn hình dọc điện thoại (780×1688)*

Đối chiếu Hình 6 và Hình 7 có thể thấy rõ ý đồ thiết kế đáp ứng (`responsive UX`): trên màn hình máy tính rộng, bố cục chia hai cột tỷ lệ `1.8fr / 1fr` đặt luồng camera làm tâm điểm quan sát bên trái và bảng điều khiển bên phải; nhưng khi mở trên màn hình hẹp của điện thoại, CSS tự động **đảo cụm 3 thẻ tín hiệu và thẻ điều khiển phiên học lên trên khung hình camera**, đồng thời dời cụm 4 nút xoay PTZ xuống dưới chân ảnh để ngón tay thao tác không che khuất khuôn mặt người học. Toàn bộ bảy khối chức năng của Web Dashboard được liệt kê trong Bảng 21.

*Bảng 21. Các khối chức năng của giao diện Web Dashboard và quy tắc hiển thị chống hiểu nhầm*

| Khối giao diện | Thành phần điều khiển và thông tin hiển thị | Quy tắc hiển thị chống hiểu nhầm áp dụng |
|---|---|---|
| **Thanh tiêu đề cố định (`Sticky Header`)** | Tên hệ thống, chỉ báo nhịp cập nhật, nút **Tắt tiếng / Bật tiếng**, nút **Hiệu chỉnh lại** | Mọi truy vấn JSON đặt `cache: "no-store"`; tệp tĩnh tự gắn tham số `?v=<mtime>` chống lưu đệm cũ |
| **Cụm 3 thẻ Tín hiệu trực tiếp** | Thẻ **Có mặt** · Thẻ **Điện thoại** · Thẻ **Danh tính** | Phối hợp đồng thời **màu sắc + biểu tượng + nhãn chữ** (hỗ trợ người mù màu); khi `fresh = false` bắt buộc đổi sang `"Chưa có dữ liệu mới"` |
| **Thẻ Điều khiển Phiên học** | Ô nhập thời lượng phút, nút **Bắt đầu học / Dừng học**, đồng hồ đếm ngược, thanh tiến độ | Đồng hồ đếm ngược tự nội suy mượt mỗi `250 ms` ở phía khách và đồng bộ lại với máy chủ mỗi `1,0 giây` |
| **Thẻ Quản lý Người học** | Nút **Thêm người** (mở hộp thoại quét 5 tư thế mỗi `0,7 s`), danh sách chọn người đang học, xóa hồ sơ | Giá trị trạng thái lạ (nếu phát sinh) luôn in nguyên văn `"Chưa rõ (<giá trị>)"` thay vì âm thầm ẩn đi |
| **Thẻ Chọn Giọng đọc** | Chuyển đổi tức thì giữa **Giọng Nam**, **Giọng Nữ** và **Giọng Máy (`espeak-ng`)** | Hiển thị rõ mô tả đặc tính từng giọng và đồng bộ xuống `data/audio/voice.json` |
| **Cụm 4 nút điều hướng PTZ** | Các nút xoay ống kính **Lên / Xuống / Trái / Phải** theo từng xung `0,4 giây` | Hỗ trợ cả thao tác nhấn đơn lẫn nhấn giữ liên tiếp (`requestPtz`) |
| **Thẻ Cam kết An toàn dữ liệu** | Tóm tắt nguyên tắc xử lý trên RAM, chỉ lưu vector đặc trưng và phạm vi mạng nội bộ | Minh bạch hóa cơ chế quyền riêng tư ngay trên màn hình sử dụng |

### 8.4. Cơ chế cổng phiên học hai lớp (`StudySession` và `Schedule`)

Để tránh việc hệ thống phát loa nhắc nhở phiền toái vào ban đêm hoặc khi người dùng chỉ ngồi vào bàn làm việc cá nhân ngoài giờ học, vòng lặp vận hành áp dụng cơ chế **cổng điều kiện hai lớp kết hợp phép hội logic (`AND`)** giữa hai thực thể độc lập là lịch tuần `schedule` (`domain/schedule.py`) và phiên học chủ động `StudySession` (`domain/study_session.py`). Hình 8 mô tả vòng đời tương tác đầy đủ của một phiên học từ lúc người dùng mở trang đến khi kết thúc.

![Vòng đời sử dụng phiên học trên giao diện](figures/06-luong-su-dung-web.png)

*Hình 8. Sơ đồ trình tự tương tác một vòng đời phiên học giữa người dùng, giao diện và vòng lặp biên*

Cổng điều kiện cuối cùng `session_active` chỉ mang giá trị `True` khi người dùng đã bấm **Bắt đầu học** (`StudySession` ở trạng thái `running`) **và** thời điểm hiện tại nằm trong khung giờ cho phép của `schedule` (hoặc `schedule.enabled: false` nghĩa là không giới hạn khung giờ). Sự khác biệt rõ rệt về các thành phần được phép chạy ở hai chế độ trong phiên và ngoài phiên được quy định tại Bảng 22.

*Bảng 22. Trạng thái kích hoạt của từng thành phần hệ thống khi ở ngoài phiên học và trong phiên học*

| Thành phần xử lý trong `MonitorRunner` | Trạng thái **Ngoài phiên học** | Trạng thái **Trong phiên học** | Lý do thiết kế kỹ thuật |
|---|---|---|---|
| Luồng đọc camera RTSP và phát `/stream`, `/api/frame` | **Chạy liên tục** | **Chạy liên tục** | Người dùng luôn cần xem hình ảnh trực tiếp để chỉnh ghế ngồi và xoay góc PTZ trước khi bấm học |
| Nhận diện khuôn mặt định kỳ (`YuNet + SFace` mỗi `2 s`) | **Chạy liên tục** | **Chạy liên tục** | Giúp giao diện biết sẵn ai đang ngồi trước bàn để chọn đúng tên người học trước khi mở phiên |
| Mô hình `YOLO11n-pose`, kiểm tra hiện diện & máy trạng thái | **Tắt hoàn toàn** | **Chạy mỗi khung** | Giải phóng tải CPU cho Raspberry Pi 4 khi không trong giờ học; không gọi `update_signals(presence=...)` giả |
| Mô hình `YOLO11n` detect điện thoại cách khung | **Tắt hoàn toàn** | **Chạy `1/2` khung** | Chỉ tiêu tốn ngân sách suy luận vật thể khi phiên học thực sự diễn ra |
| Đánh giá `should_alert`, phát loa camera và ghi `SQLite` | **Tắt hoàn toàn** | **Kích hoạt đầy đủ** | Đảm bảo tuyệt đối không phát âm thanh cảnh báo và không ghi rác vào cơ sở dữ liệu ngoài phiên học |

Trong quá trình hiện thực hóa `StudySession`, hai lỗi vi tế về thời gian thực đã được phát hiện và xử lý triệt để:

1. **Đảm bảo thông báo âm thanh `"Hết giờ học"` phát đúng một lần duy nhất:** Máy trạng thái phiên học có ba trạng thái là `idle` (chưa mở hoặc vừa bấm dừng tay), `running` (đang đếm ngược) và `finished` (đã hết thời lượng và tự động đóng). Trạng thái `finished` được tách riêng khỏi `idle` để giao diện hiển thị rõ thông báo hoàn thành phiên thay vì nhảy về màn hình trống. Đặc biệt, vì cả vòng lặp chính lẫn các truy vấn HTTP `GET /api/session` mỗi giây đều gọi hàm kiểm tra đồng hồ, nếu điều kiện phát loa dựa trên dấu hiệu *"lần gọi này vừa làm đổi trạng thái sang `finished`"* thì một truy vấn HTTP từ trình duyệt chạm đúng mili-giây hết giờ sẽ làm đổi trạng thái trước và nuốt mất sự kiện phát loa của vòng lặp chính. Do đó, điều kiện phát loa được thiết kế lại thành bất biến trạng thái: *"phiên đang ở `finished` **và** cờ `end_announced` còn bằng `False`"*, đảm bảo câu báo hết giờ luôn phát ra loa đúng một lần.
2. **Xóa sạch toàn bộ bộ đếm tích lũy tại biên chuyển trạng thái phiên:** Bất cứ khi nào cờ `session_active` chuyển đổi (từ tắt sang bật hoặc từ bật sang tắt), `MonitorRunner` thực hiện đặt lại toàn bộ bộ lọc trung vị, máy trạng thái, bộ đếm vắng mặt `presence`, bộ đếm chạm điện thoại và các mốc `cooldown`. Nếu thiếu bước làm sạch này, một chuỗi vắng mặt dở dang từ cuối phiên trước sẽ tồn đọng trên RAM và gây báo động oan ngay ở khung hình đầu tiên của phiên học mới.

### 8.5. Kiến trúc Ứng dụng di động React Native / Expo SDK 58

Mặc dù Web Dashboard đã hỗ trợ giao diện di động qua trình duyệt, trải nghiệm thực tế tại bàn học cho thấy việc mở một ứng dụng chuyên dụng ngay trên màn hình chính điện thoại tiện lợi và trực quan hơn nhiều so với việc gõ địa chỉ IP trên trình duyệt web mỗi tối. Do máy tính phát triển của dự án chạy hệ điều hành Windows (không có macOS và Xcode để biên dịch mã gốc Swift/iOS hay Flutter iOS tại chỗ), nền tảng **React Native (`0.88.1`) kết hợp hệ sinh thái Expo SDK `58.0.24` (chạy qua Expo Go)** được lựa chọn làm giải pháp tối ưu nhất: viết một cơ sở mã TypeScript duy nhất và chạy mượt trực tiếp trên điện thoại thật cùng mạng Wi-Fi LAN với Raspberry Pi 4.

Ứng dụng đặt tại thư mục `apps/mobile/` đóng vai trò một khách hàng HTTP thuần khiết, không gánh bất kỳ mô hình AI nào trên điện thoại để giữ nguyên kiến trúc "một nguồn sự thật duy nhất trên thiết bị biên". Toàn bộ mã nguồn ứng dụng tuân thủ ba nguyên tắc kiến trúc nghiêm ngặt:

- **Một cổng giao tiếp mạng duy nhất (`src/api/client.ts`):** Không một màn hình giao diện nào được phép tự gọi hàm `fetch()`. Lớp `client.ts` quản lý tập trung cả `10 endpoint HTTP`, đọc phản hồi qua `response.text()` trước khi phân tích JSON (nhằm xử lý an toàn cả các lỗi HTML ngoài tiền tố `/api/`), áp đặt hạn chờ cứng bằng `AbortController` (`5 giây` cho JSON, `10 giây` cho ảnh JPEG) và ánh xạ mọi mã lỗi HTTP/mạng sang thông báo tiếng Việt có hướng dẫn khắc phục cụ thể (`src/api/errors.ts`).
- **Hủy thật kết nối mạng khi chuyển màn hình (`src/hooks/usePoll.ts`):** Hook lấy mẫu định kỳ `2 giây` chỉ kích hoạt khi tab đang được mở (`focused = true`) và gọi trực tiếp phương thức **`AbortController.abort()`** ngay khoảnh khắc người dùng chuyển sang tab khác hoặc đóng màn hình, giải phóng lập tức socket kết nối cho máy chủ Flask trên Raspberry Pi 4.
- **Tách biệt hoàn toàn tầng xử lý dữ liệu khỏi thư viện giao diện:** Toàn bộ sáu tệp chuẩn hóa dữ liệu trong `src/api/` (`client.ts`, `payload.ts`, `format.ts`, `url.ts`, `errors.ts`, `framePolicy.ts`) không chứa bất kỳ lệnh `import` nào tới `react-native`, cho phép thực thi kiểm thử đơn vị trực tiếp bằng trình thông dịch Node.js thuần ở tốc độ cao.

### 8.6. Hệ thiết kế Nocturne Telemetry (Google Stitch) và hợp nhất 3 tín hiệu người học trong tab Camera

Ở phiên bản sơ khởi đầu tiên, ứng dụng di động từng chia nhỏ giao diện thành `8 tab` rời rạc (`Trạng thái`, `Camera`, `Phiên học`, `Tín hiệu`, `Điều khiển`, `Giọng đọc`, `Vi phạm`, `Kết nối`). Quá trình sử dụng thực tế đã bộc lộ hai nhược điểm lớn của bố cục 8 tab: thanh điều hướng dưới đáy bị chật cứng (mỗi nút chỉ rộng khoảng `39 pt` dễ bấm nhầm), và nghiêm trọng hơn là người học không thể vừa nhìn khung hình camera vừa quan sát ba thông số nhận diện cốt lõi mà phải bấm chuyển qua lại giữa ba tab khác nhau.

Để giải quyết triệt để vấn đề trải nghiệm người dùng này, toàn bộ giao diện ứng dụng đã được thiết kế lại thông qua công cụ **Google Stitch** theo ngôn ngữ thiết kế **Nocturne Telemetry** và hiện thực hóa đồng bộ trong mã nguồn `apps/mobile/src/`. Hình 9 trình bày bố cục màn hình `Camera` hợp nhất và kiến trúc phân lớp của ứng dụng sau khi tái thiết kế.

![Bố cục màn hình Camera hợp nhất và kiến trúc ứng dụng di động](figures/11-bo-cuc-app-di-dong.png)

*Hình 9. Bố cục màn hình Camera hợp nhất 3 tín hiệu người học (Nocturne Telemetry) và kiến trúc phân lớp của `apps/mobile/`*

Như minh họa trên Hình 9, hệ thiết kế **Nocturne Telemetry** sử dụng nền than chì sâu (`#0F141A`) chống mỏi mắt khi đặt điện thoại cạnh đèn bàn học buổi tối, kết hợp bảng màu ngữ nghĩa đồng bộ tuyệt đối với Web Dashboard (`#34D399` xanh ngọc = ổn định, `#FBBF24` vàng hổ phách = cảnh báo/chưa rõ, `#F87171` đỏ san hô = vi phạm, luôn đi kèm biểu tượng và nhãn chữ) cùng thuộc tính chữ số `tabular-nums` giữ cố định độ rộng con số ở mỗi nhịp làm mới `2 giây`.

Thay đổi quan trọng nhất về mặt cấu trúc thông tin là **hợp nhất trọn vẹn ba tầng quan sát thời gian thực vào ngay tab đầu tiên (`Camera`) theo trật tự thị giác từ trên xuống dưới**:

1. **Khung quan sát Camera tỷ lệ `4:3` (trên cùng):** Trang bị thanh chuyển chế độ giữa **Trực tiếp** (`WebView` hiển thị luồng MJPEG `/stream` mượt tương đương trình duyệt máy tính) và **Ảnh tĩnh** (`<Image>` tải `/api/frame` mỗi `300 ms`), kèm huy hiệu HUD báo trạng thái luồng. Khi máy chủ tắt `stream_enabled` hoặc `WebView` báo lỗi kết nối, màn hình tự động lùi về chế độ Ảnh tĩnh kèm thông báo tiếng Việt rõ ràng thay vì để khung trắng.
2. **Cụm 3 Tín hiệu người học trực tiếp (`LearnerSignalsSection` đặt ngay sát dưới khung Camera):** Sử dụng lưới **Bento 2+1** giúp người dùng vừa nhìn hình ảnh camera bên trên vừa theo dõi tức thì cả ba thông số nghiệp vụ cốt lõi ngay trong một tầm mắt mà không cần chuyển tab hay cuộn sâu:
   - *Ô trái hàng trên - **Có mặt** (phát hiện người trong khung hình):* Hiển thị `Đang trong khung hình` hoặc `Không thấy ai`.
   - *Ô phải hàng trên - **Điện thoại** (phát hiện sử dụng điện thoại):* Hiển thị `Không dùng` hoặc `Đang dùng`.
   - *Ô rộng toàn hàng dưới - **Người đang học · Danh tính**:* Hiển thị huy hiệu chữ cái đầu tên người học cùng kết luận `Đúng người (<Tên>)`, `Khác người` hoặc `Chưa nhận ra`. Hễ cờ `fresh = false`, ô tương ứng tự động chuyển sang `"Chưa có dữ liệu mới"` kèm nhãn `Cũ`.
3. **Banner Trạng thái tư thế và Lưới thông số Bento 2×2 (`PostureStatusSection`):** Hiển thị trạng thái tổng hợp của vòng lặp, điểm tư thế trên **thang `100`**, thời gian **Đã ngồi**, **Khoảng cách** và nút bấm trực tiếp **Tiếng cảnh báo** (`POST /api/mute` đồng bộ hai chiều với Web Dashboard).

Nhờ hợp nhất ba màn hình quan sát làm một, thanh điều hướng đáy rút gọn xuống còn **6 tab rộng rãi (`~62 pt/tab`)**, được mô tả chi tiết tại Bảng 23.

*Bảng 23. Cấu trúc 6 tab điều hướng của ứng dụng di động và các endpoint API sử dụng*

| Thứ tự | Tên Tab | Chức năng hiển thị và tương tác chính | Các endpoint HTTP sử dụng |
|---|---|---|---|
| **Tab 1** | **Camera** *(Màn chính gộp)* | Xem camera 4:3 (MJPEG / Ảnh tĩnh) + **Cụm 3 tín hiệu người học Bento 2+1** (`Có mặt`, `Điện thoại`, `Người đang học`) + **Trạng thái tư thế Bento 2×2** + Bật/tắt tiếng nhanh | `GET /stream`, `GET /api/frame`, `GET /api/signals`, `GET /api/status`, `POST /api/mute` |
| **Tab 2** | **Phiên học** | Nhập số phút mục tiêu, bấm **Bắt đầu học / Dừng học**, theo dõi đồng hồ đếm ngược thời gian thực | `GET /api/session`, `POST /api/session/start`, `POST /api/session/stop` |
| **Tab 3** | **Điều khiển** | Công tắc bật/tắt tiếng loa cảnh báo và bàn phím 4 hướng xoay camera **PTZ** (khóa chéo chống bấm trùng khi đang xoay) | `GET /api/status`, `POST /api/mute`, `POST /api/ptz` |
| **Tab 4** | **Giọng đọc** | Lựa chọn giữa **Giọng Nam**, **Giọng Nữ** và **Giọng Máy**, kèm cảnh báo nếu giọng chọn thiếu tệp thu âm `.wav` | `GET /api/voice`, `POST /api/voice` |
| **Tab 5** | **Vi phạm** | Tra cứu danh sách lịch sử 3 loại vi phạm (`ABSENT`, `PHONE_USE`, `IMPOSTOR`) kèm dấu thời gian và thời lượng | `GET /api/violations?limit=200` |
| **Tab 6** | **Kết nối** | Cấu hình địa chỉ LAN của Raspberry Pi (`AsyncStorage`), cảnh báo sớm bẫy nhập nhầm `localhost` / `127.0.0.1` trên điện thoại và kiểm tra kết nối | `GET /api/status` |

Để phục vụ ứng dụng di động này, phía máy chủ Flask đã được bổ sung hai endpoint chuyên dụng là `GET /api/frame` (do thành phần `<Image>` gốc của React Native không đọc được luồng đa phần MJPEG vô hạn) và `GET /api/violations` (lọc sạch các sự kiện kỹ thuật nội bộ như `SPEAK_OK`, `alert_start`, chỉ trích xuất đúng 3 loại vi phạm nghiệp vụ kèm nhãn tiếng Việt `kind_text` thống nhất từ máy chủ), đồng thời phát hiện và sửa triệt để một lỗi truy cập SQLite xuyên luồng chỉ xuất hiện khi nhiều luồng worker HTTP truy vấn đồng thời với vòng lặp ghi.

### 8.7. Kịch bản vận hành đầu-cuối và các khoảng trống giao diện đã ghi nhận

Khi triển khai hoàn chỉnh hệ thống tại bàn học, quy trình vận hành chuẩn từ lúc cấp nguồn đến khi kết thúc một buổi học diễn ra mạch lạc qua bảy bước như trình bày trong Bảng 24.

*Bảng 24. Kịch bản vận hành và trình diễn (Demo) hệ thống đầu-cuối trên phần cứng thật*

| Bước | Thao tác của người học | Xử lý nội bộ trên Raspberry Pi 4 & Camera IP | Phản hồi quan sát được trên Web / Mobile & Loa |
|---|---|---|---|
| **1** | Cấp nguồn Raspberry Pi 4 và camera IP; khởi chạy lệnh `posture_monitor run` | Nạp cấu hình `config.yaml`, mở kết nối RTSP `/1/2`, khởi tạo SQLite `WAL` và mở máy chủ Flask cổng `8000` | Nhật ký báo sẵn sàng; luồng camera hiện trực tiếp trên Web và tab `Camera` của App di động |
| **2** | Mở Web Dashboard, bấm **Thêm người** và làm theo 5 hướng dẫn góc mặt (`~7,5 s`) | `EnrollmentTracker` thu 5 vector SFace 128 chiều, ghi nguyên tử vào `faces.json` và tự suy ngưỡng cosine | Thanh tiến độ chạy đủ 5 bước; tên người học mới xuất hiện trong danh sách và được chọn làm người đang học |
| **3** | Dùng nút **PTZ** trên App di động chỉnh góc camera thấy rõ mặt và mặt bàn | Gửi xung `continuous_move` `0,4 s` qua ONVIF cổng `80` và khóa `stop()` an toàn | Khung hình camera dịch chuyển mượt; ô `Người đang học` báo xanh **`Đúng người (<Tên>)`** |
| **4** | Sang tab **Phiên học**, nhập `45 phút` và bấm **Bắt đầu học** | Cổng `session_active` bật sang `True`; kích hoạt `YOLO11n-pose` (mỗi khung) và `YOLO11n` detect (`1/2` khung) | Đồng hồ bắt đầu đếm ngược; cả 3 ô `Có mặt`, `Điện thoại`, `Người đang học` đều chuyển sang trạng thái tươi màu xanh |
| **5** | Người học cầm điện thoại lên lướt quá `1,0 giây` | Khoảng cách cổ tay - hộp `cell phone` `< 1,0 × vai`, vượt qua `phone_like_filter` và đủ `hold_s = 1,0 s` | Loa camera phát giọng tiếng Việt nhắc cất điện thoại; ô `Điện thoại` trên App đổi đỏ **`Đang dùng`**; ghi bản ghi `PHONE_USE` |
| **6** | Người học đứng dậy rời khỏi bàn quá `5,0 giây` (hoặc nhờ người khác ngồi vào ghế) | Keypoint thân trên `< 2` điểm quá hạn (hoặc SFace báo `MISMATCH` quá `5,0 s`) | Loa camera phát câu nhắc quay lại bàn (hoặc cảnh báo sai người học theo thứ tự ưu tiên cao nhất); ghi sự kiện vào SQLite |
| **7** | Hết thời lượng phiên học hoặc bấm **Dừng học**; mở tab **Vi phạm** | `StudySession` chuyển sang `finished`, phát câu báo hết giờ đúng 1 lần, tắt mô hình pose/phone và xả lô SQLite | Loa báo hoàn thành phiên học; tab `Vi phạm` trên điện thoại liệt kê đầy đủ các lần rời bàn và dùng điện thoại trong phiên |

Bên cạnh các tính năng đã vận hành trọn vẹn ở trên, tuân thủ nguyên tắc minh bạch kỹ thuật, đề tài cũng ghi nhận rõ bốn điểm trên giao diện Web hiện chưa nối hoàn chỉnh với tầng xử lý bên dưới để người phát triển kế tiếp nắm bắt chính xác, tổng hợp tại Bảng 25.

*Bảng 25. Ghi nhận trung thực các điểm lệch giữa giao diện Web hiện tại và mã xử lý hậu trường*

| STT | Thành phần trên giao diện / API | Hành vi thực tế hiện tại trong mã nguồn | Hướng xử lý đề xuất |
|---|---|---|---|
| 1 | Nút **"Hiệu chỉnh lại"** trên thanh tiêu đề Web | `POST /api/calibrate` đặt cờ thành công, nhưng `MonitorRunner` đọc cờ chỉ ghi dòng hướng dẫn chạy lệnh CLI `posture_monitor calibrate` chứ chưa hiệu chỉnh trực tiếp trên luồng sống | Tích hợp hàm chụp mốc bề rộng vai chuẩn trực tiếp vào vòng lặp `MonitorRunner` |
| 2 | Dòng mô tả **"Làm mờ người khác trong khung"** ở thẻ An toàn dữ liệu | Lớp `ObjectBlurrer` chỉ mới có trong tài liệu thiết kế sơ bộ, chưa hiện thực trong `vision/overlay.py` (hiện chỉ vẽ hộp bao người đang khóa) | Sửa lại câu mô tả trên HTML cho khớp thực tế hoặc bổ sung bước làm mờ Gaussian các hộp `person` phụ |
| 3 | Ba endpoint `GET /api/history`, `POST /api/speak`, `PUT /api/schedule` | Đã lập trình hoàn chỉnh và có bài kiểm thử tự động phía máy chủ, nhưng giao diện Web hiện chưa gắn nút gọi trực tiếp | Bổ sung biểu đồ lịch sử và khung chỉnh giờ học trực quan trên trang quản trị |
| 4 | Lưu cấu hình lịch học qua `PUT /api/schedule` | Thay đổi có hiệu lực ngay trên đối tượng RAM nhưng chưa ghi đè ngược lại tệp `config.yaml`, khởi động lại tiến trình sẽ quay về lịch gốc | Ghi tách phần lịch động ra tệp `data/schedule.json` bằng `atomic_io` tương tự `voice.json` |

### 8.8. Kết chương

Chương 8 đã trình bày chi tiết toàn bộ tầng giao tiếp người dùng và điều phối vận hành của hệ thống: từ máy chủ Flask 24 route giao tiếp không chặn qua `DashboardState`, luồng MJPEG chuẩn giao thức, giao diện Web tiếng Việt offline-first, cơ chế cổng phiên học hai lớp cho đến ứng dụng di động React Native/Expo SDK 58 mang ngôn ngữ thiết kế *Nocturne Telemetry* hợp nhất khung hình camera với cụm 3 tín hiệu người học ngay trên một màn hình duy nhất.

Để khẳng định chất lượng phần mềm của 9 phân hệ Python cùng ứng dụng di động, đồng thời đánh giá khách quan hiệu năng thời gian thực đạt được trên phần cứng Raspberry Pi 4, Chương 9 tiếp theo sẽ trình bày toàn bộ hệ thống kiểm thử tự động, kết quả đo ngân sách thời gian, bảng đối chiếu nghiệm thu và phân tích so sánh kỹ thuật.

## CHƯƠNG 9. KIỂM THỬ HỆ THỐNG, ĐO LƯỜNG HIỆU NĂNG VÀ ĐÁNH GIÁ TỔNG HỢP

### 9.1. Thiết lập môi trường kiểm thử tự động hai nền tảng không cần phần cứng

Một trong những mục tiêu kỹ thuật trọng tâm của đề tài (mục tiêu **MT7**) là toàn bộ logic tính toán hình học, máy trạng thái thời gian, giao thức API, cơ sở dữ liệu và giao diện di động đều phải kiểm chứng được tự động bằng một lệnh chạy duy nhất trên máy tính cá nhân (Windows/Linux) mà không cần cắm camera thật hay bo mạch Raspberry Pi 4. Khả năng này đạt được nhờ thiết kế tiêm phụ thuộc xuyên suốt kết hợp ba kỹ thuật giả lập chuẩn xác: sinh luồng video kiểm thử bằng `cv2.VideoWriter`, thay thế dịch vụ nhận diện bằng kho vector giả lập trên RAM và gắn nhà máy chân `gpiozero.pins.mock.MockFactory`. Quy mô và kết quả thực thi của toàn bộ hệ thống kiểm thử tự động được tổng hợp trong Bảng 26.

*Bảng 26. Tổng hợp quy mô và kết quả thực thi bộ kiểm thử tự động trên cả Backend Python và Mobile App*

| Nhóm kiểm thử / Thư mục | Số tệp kiểm thử | Số kịch bản kiểm thử | Kết quả chạy thực tế | Trọng tâm kiểm chứng kỹ thuật |
|---|---|---|---|---|
| `tests/core/` · `tests/storage/` · `tests/hardware/` · `tests/camera/` | `18 tệp` | `412 bài` | `100% PASS` | Phân tích `config.yaml`, ghi nguyên tử `fsync`, che mật khẩu RTSP, SQLite `WAL` xuyên luồng, GPIO mock, đóng gói RTP/PCMA và ONVIF PTZ |
| `tests/vision/` | `14 tệp` | `486 bài` (`4 bài` tự `skip` khi máy test không đặt tệp `.onnx`/`.pt` nặng) | `482 PASS`, `4 SKIPPED` | Khoảng cách điểm - hộp điện thoại, 3 bộ lọc chống nhầm gọng kính, ánh xạ tọa độ khuôn mặt, kiểm tra không sinh bất kỳ tệp ảnh nào trên đĩa |
| `tests/domain/` · `tests/alerts/` | `13 tệp` | `398 bài` | `100% PASS` | Khóa `track id`, `presence` thân trên, lịch tuần vắt qua nửa đêm, `StudySession` (44 bài), thứ tự ưu tiên loa và rơi dự phòng 3 tầng âm thanh |
| `tests/web/` · `tests/cli/` · `tests/integration/` | `15 tệp` | `366 bài` | `100% PASS` | Đầy đủ 24 route HTTP, lọc `scrub_biometrics`, luồng MJPEG, nối dây `MonitorRunner` với `StudySession` và hàng rào chống số liệu bịa |
| **Tổng cộng Backend Python (`pytest tests/`)** | **`60 tệp`** | **`1.662 bài`** | **`1.658 PASS` · `0 FAIL`** | Bao phủ toàn bộ 9 phân hệ một chiều trong `src/posture_monitor/` |
| **Mobile Tầng 1 - Logic thuần (`npm test`)** | `7 tệp` | `160 bài` | `160/160 PASS` | Chạy trực tiếp trên Node.js `>= 22.18`: chuẩn hóa URL LAN, phân tích payload, định dạng số, ánh xạ lỗi tiếng Việt, chính sách tải khung |
| **Mobile Tầng 2 - Giao diện DOM (`npm run verify`)** | `2 tệp` | `29 bài` | `29/29 PASS` (`tsc` `0 lỗi`) | Dựng cây component thật trên `jsdom` + `react-native-web`: kiểm tra thứ tự `Camera -> 3 Tín hiệu -> Trạng thái`, tự lùi `/api/frame`, gọi `AbortController.abort()` |
| **Tổng cộng Ứng dụng di động (`apps/mobile/`)** | **`9 tệp`** | **`189 bài`** | **`189/189 PASS`** | Tái lập hoàn toàn từ kho mã nguồn bằng một lệnh `npm run verify:all` |

Tổng cộng toàn dự án sở hữu **`1.851 kịch bản kiểm thử tự động`** (`1.662` bài Python + `189` bài TypeScript/React Native), đóng vai trò lưới an toàn vững chắc trong suốt quá trình tái cấu trúc mã nguồn từ kiến trúc phẳng ban đầu sang 9 phân hệ chuyên biệt và nâng cấp giao diện *Nocturne Telemetry*.

### 9.2. Công cụ đo kiểm hiệu năng (`benchmark`) và ba hồ sơ đo chuẩn hóa

Để đo lường hiệu năng thực tế trên Raspberry Pi 4 một cách khách quan và tái lập được, phân hệ `src/posture_monitor/cli/benchmark/` cung cấp lệnh dòng lệnh chuyên dụng `python -m posture_monitor benchmark`. Công cụ này đo đồng thời bốn nhóm đại lượng trong suốt thời gian chạy: (1) phân bố độ trễ từng khâu (`count`, `min`, `median`, `p95`, `max`, `mean`), (2) nhiệt độ CPU và thanh ghi `get_throttled` lấy mẫu mỗi `5 giây`, (3) mức tiêu thụ bộ nhớ vật lý `RSS` (đầu kỳ, cuối kỳ, đỉnh cực đại), và (4) định danh rõ loại nguồn khung hình (`camera`, `video`, `image`, `synthetic`: trong đó nếu đo trên ảnh tĩnh thì báo cáo tự in dòng chữ in hoa nhắc nhở đây không phải tốc độ FPS camera thật).

Công cụ hỗ trợ ba hồ sơ đo (`--profile`) đóng kín gồm: **`pose`** (chỉ chạy thu hình + ước lượng khung xương + bộ luật), **`pose_phone`** (ghép thêm phát hiện điện thoại cách khung) và **`pose_phone_face`** (cấu hình đầy đủ cả ba nhánh mô hình). Nếu người dùng truyền sai tên hồ sơ hoặc thiếu mô-đun phụ thuộc, công cụ lập tức từ chối thực thi kèm mã thoát `2` và thông báo tiếng Việt rõ ràng chứ tuyệt đối không âm thầm rơi về hồ sơ nhẹ hơn làm sai lệch kết luận đo.

### 9.3. Phân tích ngân sách thời gian một khung hình và tốc độ FPS trên Raspberry Pi 4

Hình 10 trực quan hóa ngân sách thời gian của từng khâu xử lý đo trực tiếp trên bo mạch Raspberry Pi 4 Model B của dự án đặt cạnh đường ngưỡng mục tiêu `200 ms` (tương ứng tốc độ `5,0 FPS`).

![Ngân sách thời gian xử lý một khung hình trên Pi 4](figures/03-ngan-sach-thoi-gian.png)

*Hình 10. Ngân sách thời gian các khâu xử lý đo thực tế trên Raspberry Pi 4 so với ngưỡng mục tiêu 200 ms (5 FPS)*

Toàn bộ các con số độ trễ thành phần và tốc độ đường ống đã đo trên phần cứng thật được tổng hợp chi tiết cùng điều kiện đo trong Bảng 27.

*Bảng 27. Tổng hợp kết quả đo độ trễ suy luận và tốc độ đường ống trên Raspberry Pi 4*

| Hạng mục phép đo thực nghiệm | Giá trị đo được | Điều kiện thực hiện phép đo | Nhãn bằng chứng |
|---|---|---|---|
| Suy luận thuần `YOLO11n-pose` NCNN (`imgsz = 320`) | `min` **105,5 ms** · `median` **107,3 ms** · `p95` **116,2 ms** | Lặp `549 lượt` liên tiếp trên ảnh tĩnh `640×480` | **ĐÃ ĐO** |
| Tốc độ suy luận thuần từ trung vị pose | **9,32 FPS** (`= 1000 / 107,3`) | Chỉ phản ánh tốc độ mạng nơ-ron đơn lẻ, chưa có chi phí đọc camera | **TÍNH TỪ ĐO** |
| Phát hiện mặt `YuNet` trên khung gốc `704×576` | **99,9 ms / lượt** | Đo trực tiếp trên khung hình thật từ camera RTSP | **ĐÃ ĐO** |
| Phát hiện mặt `YuNet` khi thu nhỏ về `320×262` + `CLAHE` | `YuNet` **19,3 ms** + `CLAHE` **11,4 ms** | Nhanh gấp `~5 lần` nhưng làm giảm tỷ lệ bắt mặt ở ngưỡng cao (xem mục 3.4) | **ĐÃ ĐO** |
| Trọn đường ống khuôn mặt (`thu nhỏ + CLAHE + YuNet + alignCrop + SFace`) | **86,1 ms / lượt** (`~11,6 lượt/giây`) | Chạy định kỳ mỗi `2,0 giây` nên chi phí trung bình mỗi giây rất nhỏ | **ĐÃ ĐO** |
| Suy luận thuần `YOLO11n` detect NCNN (`imgsz = 320`) | **98,6 ms / lượt** (lần chạy lặp lại đạt `98,7 ms`) | Đo trên khung tổng hợp `640×480` độc lập vòng lặp | **ĐÃ ĐO** |
| **Đường ống thực tế trọn vẹn (chỉ bật `pose` trên camera RTSP thật)** | **`pipeline_total = 199,25 ms`** (`capture = 65,93 ms` + `pose_detect = 133,32 ms`, riêng suy luận `100,51 ms`) | Chạy liên tục **`60 giây`** (`~301 khung`), `throttled = 0x0`, nhiệt cực đại `58,9 °C` | **ĐÃ ĐO** |
| **Tốc độ FPS đường ống thực tế (cấu hình chỉ `pose`)** | **5,02 FPS** (`= 1000 / 199,25`) | Chạm sát ngưỡng mục tiêu `5,0 FPS` với biên dư chỉ `0,75 ms/khung` | **TÍNH TỪ ĐO** |

Để kiểm tra độ ổn định lặp lại của con số `5,02 FPS` khi mạng nội bộ và bộ giải mã HEVC dao động tự nhiên, dự án đã thực hiện tiếp **8 lượt chạy lặp lại độc lập** của cùng cấu hình đường ống chỉ pose trên camera thật. Kết quả phân bố của 8 lượt đo được biểu diễn trên Hình 11.

![Kết quả 8 lượt đo lặp lại tốc độ FPS đường ống](figures/04-fps-tam-lan-do.png)

*Hình 11. Phân bố tốc độ FPS qua 8 lượt đo lặp lại trên camera RTSP thật (trung vị xấp xỉ 4,96 FPS)*

Quan sát Hình 11, có đúng **4/8 lượt chạy đạt từ `5,0 FPS` trở lên** và 4/8 lượt nằm ngay sát dưới mốc `5,0 FPS` với giá trị trung vị đạt xấp xỉ **`4,96 FPS`**. Kết quả này cho thấy ngay ở cấu hình cơ sở chỉ chạy một mô hình pose, tốc độ hệ thống dao động ngay trên đường biên `5 FPS` chứ chưa có khoảng dư lớn. Khi ghép thêm chi phí suy luận của mô hình phát hiện điện thoại (`98,6 ms/lượt`) vào phép đo đường ống thật `199,25 ms` theo các tần suất chạy cách khung khác nhau, tốc độ kỳ vọng suy ra bằng toán học được trình bày tại Bảng 28.

*Bảng 28. Phân tích tốc độ FPS kỳ vọng khi ghép thêm nhánh phát hiện điện thoại vào đường ống thật (`TÍNH TỪ ĐO`)*

| Tần suất gọi `YOLO11n` detect | Công thức tính thời gian trung bình mỗi khung (`ms`) | Tốc độ FPS suy ra | Đánh giá so với mốc `>= 5,0 FPS` |
|---|---|---|---|
| Chạy mỗi khung (`1/1`) | `199,25 + 98,60 = 297,85 ms` | **`3,36 FPS`** | **Chưa đạt** |
| Chạy cách khung (`1/2` - *đang cấu hình*) | `199,25 + (98,60 / 2) = 248,55 ms` | **`4,02 FPS`** | **Chưa đạt** (đủ mượt cho bộ lọc giữ `1,0 s`) |
| Chạy mỗi 3 khung (`1/3`) | `199,25 + (98,60 / 3) = 232,12 ms` | **`4,31 FPS`** | **Chưa đạt** |
| Chạy mỗi 4 khung (`1/4`) | `199,25 + (98,60 / 4) = 223,90 ms` | **`4,47 FPS`** | **Chưa đạt** |

Từ Bảng 28, báo cáo rút ra kết luận kỹ thuật hoàn toàn trung thực: với phần cứng CPU thuần của Raspberry Pi 4 ở độ phân giải mô hình `imgsz = 320`, khi bật đồng thời cả pose và detect điện thoại cách khung (`1/2`), tốc độ tính toán hợp lý nằm quanh mức **`~4,0 FPS`** chứ không đạt `5,0 FPS`, và cấu hình đầy đủ cả ba nhánh chạy đồng thời (`pose_phone_face`) hiện mang nhãn **`CHƯA ĐO` trọn một lượt benchmark chính thức**. Trong trường hợp cần ép tốc độ thực tế vượt qua mốc `5,0 FPS`, tài liệu thiết kế đã chuẩn bị sẵn bậc thang giảm tải có thứ tự đóng: (1) giãn `face.interval_s` lên `3-5 giây` -> (2) giãn detect lên `1/3` hoặc `1/4` khung -> (3) hạ kích thước đầu vào `model.imgsz` từ `320` xuống `256` -> (4) điều chỉnh chỉ tiêu `target_fps` về `4 FPS` phù hợp bản chất bài toán giám sát hành vi tĩnh tại bàn học.

### 9.4. Đối chiếu kết quả thực tế với bộ tiêu chí nghiệm thu hệ thống

Tổng hợp toàn bộ kết quả kiểm chứng phần mềm và phần cứng đối chiếu trực tiếp với các tiêu chí kỹ thuật đặt ra từ đầu dự án được trình bày trong Bảng 29.

*Bảng 29. Bảng đối chiếu tổng hợp kết quả thực hiện với bộ tiêu chí nghiệm thu của đề tài*

| Tiêu chí kỹ thuật | Ngưỡng mục tiêu đặt ra | Trạng thái và số liệu kiểm chứng thực tế | Kết luận đối chiếu |
|---|---|---|---|
| Vận hành đầu-cuối trên phần cứng thật | Camera RTSP -> AI biên -> Web/App -> Loa camera -> SQLite | Đã chạy thông suốt toàn chuỗi trên Raspberry Pi 4 + Camera IP `704×576` + iPhone/Android qua Expo Go | **Đạt hoàn chỉnh** |
| Nhiệt độ CPU khi vận hành có tải | `< 80,0 °C` (không bị hãm xung) | Đạt `55,0 -> 58,0 °C`, cực đại **`58,9 °C`** ở bài đo 60 giây (**ĐÃ ĐO**) | **Đạt với biên an toàn rộng** |
| Trạng thái nguồn và xung nhịp (`throttle`) | Thanh ghi `get_throttled == 0x0` | Đạt **`0x0`** tại tất cả các điểm lấy mẫu (**ĐÃ ĐO**) | **Đạt tuyệt đối** |
| Dung lượng bộ nhớ RAM tiêu thụ | `< 1.024 MiB` (`1 GB`) | Đỉnh `RSS` chỉ hết **`464,0 MiB`** cho cấu hình pose (**ĐÃ ĐO**), còn trống hơn `3,2 GB` trên bo mạch 4 GB | **Đạt với biên an toàn rộng** |
| Tốc độ xử lý đường ống chỉ `pose` | `>= 5,0 FPS` | Lần đo gốc đạt **`5,02 FPS`** (`199,25 ms`), lặp 8 lần đạt trung vị **`4,96 FPS`** (`4/8` lần `>= 5 FPS`) | **Đạt sát biên (chưa dư ổn định)** |
| Tốc độ đường ống đa mô hình (`pose_phone_face`) | `>= 5,0 FPS` | Ghép số đo `pose + phone (1/2)` cho **`4,02 FPS`** (**TÍNH TỪ ĐO**); trọn 3 mô hình đồng thời **CHƯA ĐO** | **Chưa đạt mốc 5 FPS (~4 FPS)** |
| Bảo vệ quyền riêng tư không lưu ảnh | `0 tệp ảnh` sinh ra trên đĩa; không lộ vector ra API | Đã khóa bằng kiểm thử quét thư mục và bộ lọc `scrub_biometrics` | **Đạt tuyệt đối** |
| Kiểm thử tự động tái lập được trên PC | Toàn bộ module cốt lõi có unit/integration/UI test | **`1.662 bài`** Python (`0 fail`) + **`189 bài`** Mobile (`0 fail`, `tsc` `0 lỗi`) | **Đạt vượt mức yêu cầu** |

### 9.5. Phân tích so sánh lựa chọn mô hình và công nghệ với các phương án thay thế

Để làm rõ tính hợp lý của bộ giải pháp công nghệ đã chọn trên thiết bị biên Raspberry Pi 4, Bảng 30 thực hiện phân tích đối sánh trực tiếp giữa lựa chọn của đề tài với các phương án phổ biến khác ở cả bốn khía cạnh: mô hình khung xương/vật thể, nhận diện khuôn mặt, kênh phát âm thanh và nền tảng ứng dụng di động.

*Bảng 30. So sánh giải pháp công nghệ của đề tài với các phương án thay thế trên thiết bị biên*

| Hạng mục kỹ thuật | Giải pháp chọn trong đề tài | Các phương án thay thế phổ biến | Lý do kỹ thuật quyết định lựa chọn của đề tài |
|---|---|---|---|
| **Ước lượng tư thế & Phát hiện điện thoại** | **YOLO11n-pose + YOLO11n detect** xuất sang **NCNN (`imgsz = 320`)** | Faster R-CNN (hai giai đoạn); MediaPipe Pose/Hands; chạy trực tiếp PyTorch `.pt` | Faster R-CNN quá nặng không thể chạy thời gian thực trên CPU Cortex-A72; MediaPipe không có sẵn bộ phát hiện vật thể `cell phone` đồng nhất tọa độ; định dạng NCNN tối ưu tập lệnh ARM NEON vượt trội so với `.pt` thuần |
| **Phát hiện & Nhận diện khuôn mặt** | **YuNet + SFace** tích hợp gốc trong `opencv-python 5.0` | `dlib` (`face_recognition` ResNet-34); `InsightFace` (`ArcFace` qua `onnxruntime`) | Cặp YuNet + SFace có sẵn ngay trong thư viện `cv2` đang dùng cho camera, không cần biên dịch C++ nặng nề như `dlib` và không gây xung đột phụ thuộc trên Python `3.13` ARM64, chỉ tốn `86,1 ms` |
| **Kênh cảnh báo âm thanh tại bàn học** | **RTSP Backchannel G.711 PCMA 8 kHz** phát thẳng ra loa Camera IP | Loa vi tính cắm cổng 3.5mm của Pi; còi chip buzzer đơn âm trên GPIO | Tận dụng ngay loa có sẵn trên camera đặt đối diện người học, không phải kéo dây âm thanh từ bo mạch Pi đặt góc phòng và truyền đạt được thông điệp tiếng Việt rõ nghĩa thay vì tiếng bíp đơn điệu |
| **Nền tảng Ứng dụng di động** | **React Native `0.88` + Expo SDK `58` (Expo Go)** thiết kế với Google Stitch | Ứng dụng gốc Swift (iOS) / Kotlin (Android); Flutter; chỉ dùng Web PWA | Cho phép phát triển và chạy thử trực tiếp trên iPhone thật từ máy tính Windows mà không bắt buộc phải có máy Mac/Xcode, đồng thời mang lại trải nghiệm điều hướng tab gốc mượt mà |

### 9.6. Phân tích các tình huống nhận diện đúng/sai điển hình và bài học quản trị trung thực số liệu

Trong quá trình chạy thực nghiệm với người học thật trước camera, hệ thống ghi nhận rõ các tình huống hoạt động chính xác cũng như các trường hợp biên dễ gây nhầm lẫn được tổng hợp tại Bảng 31.

*Bảng 31. Phân tích các tình huống nhận diện đúng và tình huống biên dễ nhầm trong thực tế vận hành*

| Nhóm tình huống thực tế | Phản ứng của hệ thống | Nguyên nhân kỹ thuật và cơ chế xử lý |
|---|---|---|
| Người học đeo kính cận gọng đen và đưa tay lên đẩy gọng kính hoặc chống cằm | **Nhận diện ĐÚNG (Không báo nhầm điện thoại)** | Dù YOLO11n bắt nhầm gọng kính là `cell phone` (`conf ~0,05`), bộ lọc `phone_like_filter` loại sạch `24/24` hộp nằm cao hơn đường vai quá `10 px` |
| Người học giơ chiếc điện thoại lên cao ngang mặt để xem video / chụp ảnh | **Nhận diện ĐÚNG (Báo dùng điện thoại sau `1,0 s`)** | Điện thoại gần ống kính có cạnh dài vượt `2,25 × bề rộng vai` (`oversize_ratio`), kích hoạt van an toàn giữ hộp lại bất chấp vị trí cao hơn vai |
| Người học cúi đầu thấp ghi chép vào vở làm khuất mặt trong `10-20 giây` | **Nhận diện ĐÚNG (Giữ có mặt, không báo người lạ)** | Vẫn còn 2 vai và đỉnh đầu (`>= 2` keypoint thân trên) nên `presence = co_mat`; YuNet không thấy mặt nên trả `UNKNOWN` (giữ yên trạng thái, không kích hoạt `MISMATCH`) |
| Người thứ hai đi ngang qua phía sau ghế khi chủ nhân vừa đứng dậy ra ngoài | **Nhận diện ĐÚNG (Tiếp tục đếm vắng mặt)** | Cơ chế khóa `track id` giữ nguyên mã của chủ nhân trong `120 giây`, từ chối nhảy khóa sang hộp bao của người đi ngang |
| Điện thoại đặt ngửa sát cạnh vở viết và cổ tay tỳ sát bên cạnh máy lâu hơn `1 s` | **Tình huống biên có thể BÁO NHẦM** | Trên mặt phẳng chiếu 2D không có chiều sâu, khoảng cách Euclid từ cổ tay tới hộp điện thoại nhỏ hơn `1,0 × vai` liên tục nên thỏa điều kiện chạm |
| Căn phòng tắt đèn trần, chỉ bật đèn bàn rọi ngược mạnh từ phía sau màn hình | **Tình huống biên GIẢM ĐỘ NHẠY mặt** | Khuôn mặt bị tối sẫm do ngược sáng khiến YuNet trả kết quả `UNKNOWN` nhiều hơn bình thường do chưa bật tiền xử lý cân bằng sáng cục bộ trên đường chạy chính |

Song song với các đánh giá thuật toán, đề tài còn rút ra một **bài học kỹ thuật đặc biệt quan trọng về quản trị tính trung thực của số liệu thực nghiệm**. Trong giai đoạn phát triển trước đây, tài liệu nội bộ từng xuất hiện một số con số hiệu năng được gắn nhãn đo thật nhưng khi rà soát chéo toàn bộ kho nhật ký thì không truy xuất được nguồn gốc, cụ thể được đối chiếu minh bạch tại Bảng 32.

*Bảng 32. Hậu kiểm sự cố số liệu nội bộ và cơ chế kiểm thử tự động chặn tái phát*

| Con số sai lệch từng xuất hiện trước khi hậu kiểm | Bản chất sai sót phát hiện qua kiểm toán kho mã | Biện pháp khắc phục quy trình và khóa cứng bằng kiểm thử tự động |
|---|---|---|
| Dải thời gian pose `"105,5 - 112,5 ms"` | `105,5 ms` là giá trị cực tiểu (`min`) của 549 lần đo ảnh tĩnh, còn con số `112,5 ms` không tồn tại trong bất kỳ tệp kết quả đo nào | Xóa bỏ hoàn toàn số không có nguồn; công bố đầy đủ bộ ba thống kê `min 105,5 / median 107,3 / p95 116,2 ms` |
| Tốc độ `"4,74 FPS"` và `"6,18 FPS"` cho cấu hình có detect | Được tính nhẩm từ con số `112,5 ms` không có thật và bỏ sót hoàn toàn `65,93 ms` chi phí thu nhận khung hình từ camera RTSP | Chuẩn hóa lại toàn bộ phép tính dựa trên phép đo đường ống thật duy nhất `199,25 ms -> 5,02 FPS` (cho ra `4,02 FPS` ở chế độ cách khung, kết luận trung thực là **chưa đạt 5 FPS**) |
| Nguy cơ con số suy diễn quay trở lại khi chỉnh sửa tài liệu/cấu hình | Sửa thủ công bằng tay dễ bị ghi đè lại trong các đợt gộp nhánh sau | Viết mới hai tệp kiểm thử tự động **`tests/vision/test_phone_docs.py`** và **`tests/cli/test_benchmark_profile.py`** quét trực tiếp văn bản `config.yaml`, mã nguồn và cấu hình để báo lỗi `FAIL` ngay lập tức nếu bất kỳ con số không nguồn gốc nào xuất hiện lại |

Bài học cốt lõi từ Bảng 32 là một con số hiệu năng không truy xuất được nguồn đo còn nguy hiểm hơn việc thẳng thắn ghi nhận `CHƯA ĐO`, bởi con số sai sẽ dẫn dắt sai toàn bộ quyết định chọn chu kỳ mô hình ở phía sau. Việc biến quy tắc trung thực số liệu thành các bài `pytest` tự động chính là điểm sáng về mặt kỹ thuật phần mềm của đề tài.

### 9.7. Kết chương

Chương 9 đã trình bày toàn diện bức tranh kiểm chứng chất lượng của hệ thống thông qua `1.851` bài kiểm thử tự động trên cả hai nền tảng Python và Mobile, phân tích chi tiết ngân sách độ trễ từng mili-giây trên Raspberry Pi 4, đối chiếu minh bạch các chỉ tiêu nghiệm thu và so sánh giải pháp lựa chọn với các công nghệ thay thế.

Trên cơ sở toàn bộ các kết quả lý thuyết, kiến trúc, triển khai thực tế và đánh giá thực nghiệm từ Chương 1 đến Chương 9, Chương 10 tiếp theo sẽ tổng kết lại những đóng góp đạt được của đề tài, nhìn nhận thẳng thắn các hạn chế còn tồn tại và vạch ra lộ trình phát triển cụ thể theo từng phân hệ.

## CHƯƠNG 10. KẾT LUẬN VÀ HƯỚNG PHÁT TRIỂN

### 10.1. Kết luận chung

Đề tài **Hệ thống giám sát học tập trên Raspberry Pi 4 kết hợp Camera IP và Ứng dụng di động** đã hoàn thành mục tiêu xây dựng một giải pháp IoT kết hợp trí tuệ nhân tạo tại biên (Edge AI) hoạt động khép kín đầu-cuối trên phần cứng thực tế. Không cần phụ thuộc vào máy chủ đám mây hay bộ xử lý đồ họa rời đắt tiền, hệ thống đã chứng minh khả năng tiếp nhận trực tiếp luồng hình ảnh RTSP `704×576` từ camera IP phổ thông, vận hành phối hợp bốn mô hình thị giác máy tính pretrained (YOLO11n-pose, YOLO11n detect, YuNet, SFace) theo lịch trình đa chu kỳ hợp lý, phát lời nhắc tiếng Việt rõ ràng trực tiếp ra loa tích hợp của camera qua giao thức RTSP backchannel, điều khiển xoay góc ống kính qua ONVIF và cung cấp trải nghiệm giám sát đồng bộ trên cả Web Dashboard lẫn Ứng dụng di động React Native/Expo.

Giá trị kỹ thuật cốt lõi của công trình không dừng ở việc gọi chạy được các mô hình học sâu trên bo mạch nhúng, mà nằm ở **nghệ thuật kỹ thuật hệ thống (`systems engineering`)**: từ thuật toán xả đệm `grab()` ngưỡng `30 ms` chặn đứng hiện tượng trôi độ trễ RTSP, quy tắc khoảng cách cổ tay chuẩn hóa theo bề rộng vai kết hợp bộ lọc đường vai triệt tiêu lỗi nhầm gọng kính, thiết kế danh tính ba trạng thái ưu tiên không kết tội oan người học, kiến trúc 9 phân hệ một chiều giao tiếp qua khe hẹp `DashboardState` hoàn toàn không lưu ảnh thô ra đĩa, cho đến kỷ luật minh bạch số liệu ba nhãn được bảo vệ bằng kiểm thử tự động.

### 10.2. Những kết quả đạt được

Các kết quả cụ thể mà đề tài đã hoàn thiện và kiểm chứng được tổng hợp hệ thống theo từng mảng kỹ thuật trong Bảng 33.

*Bảng 33. Tổng hợp các kết quả kỹ thuật đã đạt được của đề tài theo từng phân hệ*

| Mảng kỹ thuật | Kết quả đạt được cụ thể | Mức độ hoàn thiện và bằng chứng kiểm chứng |
|---|---|---|
| **Kiến trúc phần mềm & Kiểm thử** | Tái cấu trúc sạch toàn bộ gói `src/posture_monitor/` thành 9 phân hệ một chiều chuẩn `pyproject.toml`, tách riêng thư mục `models/` và 10 thư mục `tests/` | Đạt **`1.662 bài test Python`** (`1.658 PASS`, `0 FAIL`) và **`189 bài test Mobile`** (`100% PASS`, `tsc --noEmit` `0 lỗi`) chạy độc lập phần cứng |
| **Thu nhận Camera & Phần cứng biên** | Giải mã ổn định luồng phụ RTSP `704×576` HEVC có luồng nền và xả đệm `30 ms`; phát giọng Việt qua RTSP backchannel PCMA 8 kHz (STOI `0,958-0,972`); xoay ONVIF PTZ 4 hướng; hỗ trợ GPIO `gpiozero` và SQLite `WAL` | Đã chạy thực tế trên Raspberry Pi 4 Rev 1.5 (`58,9 °C` cực đại, `throttled = 0x0`, RAM đỉnh `464 MiB`) và camera IP thật |
| **Tầng nhận thức AI biên** | Tích hợp hoàn chỉnh khóa `track id` + hiện diện thân trên (`YOLO11n-pose`), phát hiện cầm điện thoại cách khung có lọc gọng kính (`YOLO11n`), đăng ký 5 góc mặt & xác thực 3 trạng thái (`YuNet + SFace`) | Giữ `8/8` hộp điện thoại thật, loại `24/24` hộp giả gọng kính; phát hiện mặt `10/10` ảnh sạch ở ngưỡng `0,7`; không ghi bất kỳ tệp ảnh nào ra đĩa |
| **Web Dashboard & Cổng phiên học** | Xây dựng máy chủ Flask 24 route an toàn luồng, luồng MJPEG không vỡ khung, trang quản trị tiếng Việt offline-first và cơ chế cổng hội hai lớp `StudySession AND schedule` | Vận hành ổn định trong mạng LAN trên cả trình duyệt máy tính (`1440×1000`) và trình duyệt di động (`780×1688`) |
| **Ứng dụng di động Expo SDK 58** | Thiết kế lại giao diện chuẩn **Nocturne Telemetry** qua Google Stitch, rút gọn thanh đáy còn 6 tab và gộp luồng Camera 4:3 + **3 Tín hiệu người học Bento 2+1** + **Trạng thái tư thế Bento 2×2** vào ngay màn hình chính | Chạy mượt trên điện thoại qua Expo Go, tự động lùi `/stream -> /api/frame` và hủy sạch request bằng `AbortController` |

### 10.3. Những hạn chế còn tồn tại

Bên cạnh những kết quả đã đạt được, đề tài nhìn nhận thẳng thắn sáu hạn chế kỹ thuật hiện còn tồn tại:

1. **Ngân sách tốc độ khi bật đồng thời đa mô hình trên CPU thuần:** Đường ống chỉ pose đạt `5,02 FPS` (trung vị 8 lần chạy `4,96 FPS`), nhưng khi ghép thêm mô hình detect điện thoại cách khung thì tốc độ tính toán lùi về mức `~4,02 FPS` và cấu hình chạy đồng thời cả ba nhánh (`pose_phone_face`) chưa được chạy trọn bài đo chuẩn 60 giây trên Pi 4.
2. **Thiếu tham số hạn chờ mạng cứng (`timeout`/`stimeout`) ở tầng FFmpeg RTSP:** Nếu camera IP bị rút dây mạng đột ngột giữa phiên, lệnh đọc luồng nền có nguy cơ bị chặn lâu trước khi cơ chế kết nối lại kịp kích hoạt.
3. **Chưa có cơ chế chống giả mạo sinh trắc học (`Face Anti-spoofing`):** Bộ nhận diện khuôn mặt hiện làm việc trên đặc trưng 2D tĩnh nên chưa phân biệt được khuôn mặt người thật với ảnh chụp chất lượng cao đưa ra trước camera.
4. **Giới hạn hình học 2D đối với điện thoại đặt sát cổ tay và điều kiện ngược sáng gắt:** Phép đo khoảng cách trên mặt phẳng ảnh có thể báo chạm khi tay đặt đè sát cạnh điện thoại nằm yên trên bàn; đồng thời đường chạy chính chưa bật bước cân bằng sáng cục bộ cho khuôn mặt ngược sáng mạnh.
5. **Bốn điểm giao diện Web chưa nối hết xuống hậu trường:** Gồm nút hiệu chỉnh trực tiếp từ trình duyệt, tính năng làm mờ người phụ trong khung hình, giao diện xem lịch sử/sửa lịch học bền vững xuống đĩa và việc hiệu chuẩn thực nghiệm 4 hằng số `reacquire`.
6. **Phụ thuộc môi trường Expo Go trong quá trình triển khai di động thử nghiệm:** Do phát triển trên Windows không có Xcode, ứng dụng hiện phân phối nội bộ qua Expo Go nên phụ thuộc vào phiên bản SDK hiện hành của Expo Go trên kho ứng dụng.

### 10.4. Hướng phát triển cho tầng mô hình AI biên

Trong giai đoạn tiếp theo, tầng nhận thức thị giác trên thiết bị biên định hướng nâng cấp theo bốn hạng mục trọng tâm: (1) thực hiện ngay bài đo chuẩn `benchmark --profile pose_phone_face --seconds 60` ba lượt liên tiếp trên Raspberry Pi 4 để chốt bảng số liệu thực nghiệm đầy đủ và thử nghiệm xuất mô hình ở kích thước `imgsz = 256` hoặc lượng tử hóa `INT8` nhằm đưa tốc độ toàn phần vượt ổn định trên mốc `5-6 FPS`; (2) chạy công cụ `scripts/face_threshold_probe.py` và `scripts/calibrate_reacquire.py` với tập người dùng thực tế để thay thế các ngưỡng tự suy bằng hằng số thực nghiệm chuẩn xác; (3) tích hợp bước tiền xử lý `CLAHE` có điều kiện (chỉ kích hoạt khi độ sáng trung bình vùng mặt thấp) để tăng độ bền nhận diện ngược sáng; và (4) bổ sung kiểm tra chớp mắt tự nhiên từ điểm mốc mắt hoặc mô hình chống giả mạo nhẹ (`MiniFASNet` định dạng ONNX) cho bài toán xác thực danh tính.

### 10.5. Hướng phát triển cho tầng phần cứng và giao thức truyền thông

Ở tầng phần cứng nhúng và giao thức camera mạng, các cải tiến ưu tiên bao gồm: (1) cấu hình tường minh cặp tham số `stimeout` và `rw_timeout` vào tùy chọn mở luồng FFmpeg của `RTSPSource`, đặt trần thời gian đọc cứng dưới `2,0 giây` để vòng lặp tự động khởi tạo lại phiên RTSP ngay khi rớt gói Wi-Fi; (2) tích hợp kiểm tra đồng bộ đồng hồ thời gian thực `NTP` lúc khởi động hệ thống để lịch học theo tuần không bị lệch giờ khi Raspberry Pi mất nguồn lâu ngày (do bo mạch Pi 4 không có pin CMOS RTC tích hợp); (3) nghiên cứu tích hợp bộ tổng hợp tiếng nói tiếng Việt mạng nơ-ron cục bộ siêu nhẹ (`Piper TTS` chạy ONNX trên ARM64) thay cho `espeak-ng`, nâng cao độ tự nhiên cho các câu thông báo động mà vẫn giữ nguyên cam kết không gửi dữ liệu ra đám mây; và (4) mã hóa tệp `data/faces.json` trên thẻ nhớ bằng chuẩn đối xứng `AES-GCM` thông qua thư viện `cryptography`.

### 10.6. Hướng phát triển cho tầng Web Dashboard và Ứng dụng di động

Đối với tầng dịch vụ và trải nghiệm người dùng, hướng hoàn thiện tập trung vào bốn điểm: (1) hoàn tất nối dây nút `"Hiệu chỉnh lại"` trực tiếp vào `MonitorRunner`, lưu bền vững lịch học sửa từ `PUT /api/schedule` xuống `data/schedule.json` và hiện thực hóa bộ làm mờ Gaussian cho những người đi ngang không phải đối tượng khóa; (2) bổ sung cơ chế xác thực mã PIN hoặc mật khẩu nội bộ nhẹ cho các thao tác quản trị nhạy cảm (thêm/xóa hồ sơ khuôn mặt, tắt lịch cảnh báo) trong mạng Wi-Fi dùng chung nhiều người; (3) đóng gói ứng dụng di động thành bản cài đặt độc lập (`.apk` cho Android và Development Build qua dịch vụ đám mây `EAS Build` cho iOS) kèm cấu hình `NSAllowsLocalNetworking` riêng để không còn phụ thuộc chu kỳ nâng cấp của ứng dụng Expo Go; và (4) bổ sung biểu đồ thống kê tỷ lệ tập trung theo tuần ngay trên cả Web lẫn Ứng dụng di động từ bảng dữ liệu `minute_stats` sẵn có.

### 10.7. Lộ trình phát triển tổng hợp và tổng kết chương

Để thuận tiện cho việc triển khai kế thừa, toàn bộ các hướng phát triển nêu trên được phân kỳ theo ba giai đoạn ưu tiên rõ ràng trong Bảng 34.

*Bảng 34. Lộ trình phát triển tổng hợp của hệ thống theo ba giai đoạn ngắn hạn, trung hạn và dài hạn*

| Giai đoạn | Hạng mục nâng cấp kỹ thuật trọng tâm | Phân hệ tác động | Kết quả đầu ra kỳ vọng |
|---|---|---|---|
| **Ngắn hạn** *(Ưu tiên ngay)* | Chạy benchmark 3 mô hình `pose_phone_face`; đặt `stimeout` cho FFmpeg RTSP; nối hoàn chỉnh nút hiệu chỉnh & lưu lịch học JSON; đo chốt ngưỡng cosine & `reacquire` | `cli/benchmark/`, `camera/`, `web/`, `config.yaml` | Đóng kín toàn bộ nhãn `CHƯA ĐO` và xóa sạch 4 điểm lệch giao diện Web |
| **Trung hạn** | Đóng gói bản cài đặt Mobile độc lập qua `EAS Build`; bật cân bằng sáng `CLAHE` thích ứng cho khuôn mặt; mã hóa kho `faces.json` và thêm lớp bảo vệ mã PIN quản trị LAN | `apps/mobile/`, `vision/faces.py`, `storage/`, `web/` | Sẵn sàng triển khai thực tế dài ngày tại gia đình và phòng tự học nhóm nhỏ |
| **Dài hạn** | Tích hợp chống giả mạo khuôn mặt (`MiniFASNet`); thay `espeak-ng` bằng `Piper TTS` tiếng Việt cục bộ; tự động bám góc PTZ theo vị trí ngồi và mở rộng giám sát nhiều bàn học | `vision/`, `alerts/`, `camera/control.py`, `domain/` | Trở thành trạm trợ lý tự học thông minh hoàn chỉnh tại biên |

Khép lại Chương 10, có thể khẳng định đề tài đã giải quyết trọn vẹn và thực chất bài toán đặt ra từ đầu: tạo dựng một hệ thống IoT thị giác máy tính chạy thật trên Raspberry Pi 4, tôn trọng tuyệt đối quyền riêng tư người học, kết nối mạch lạc từ cảm biến camera mạng, loa cảnh báo đến ứng dụng di động hiện đại và được bảo chứng bằng một nền tảng kiểm thử tự động nghiêm ngặt. Các chương cuối cùng tiếp theo (Chương 11 và Chương 12) cung cấp danh mục tài liệu tham khảo chính thống cùng toàn bộ phụ lục cấu trúc mã nguồn, phiên bản thư viện, đặc tả API và cấu hình vận hành của dự án.

## CHƯƠNG 11. TÀI LIỆU THAM KHẢO

### 11.1. Nhóm tài liệu về mô hình AI và thị giác máy tính

[1] Glenn Jocher, Jing Qiu và cộng sự (2024), *Ultralytics YOLO11: Pose Estimation and Object Detection Technical Documentation*, Ultralytics Docs, truy cập tại: https://docs.ultralytics.com/tasks/pose/.

[2] Tencent Nihui và cộng sự (2025), *ncnn: High-performance neural network inference computing framework optimized for mobile and ARM platforms*, Kho mã nguồn chính thức GitHub, truy cập tại: https://github.com/Tencent/ncnn.

[3] Wei Wu, Hanyang Peng, Shiqi Yu (2023), *YuNet: A Fast and Accurate CNN-based Face Detector*, Tạp chí Machine Intelligence Research, Tập 20, tr. 656-665, mô hình chính thức trong OpenCV Zoo (`face_detection_yunet_2023mar.onnx`).

[4] Yaoyao Zhong, Weihong Deng và cộng sự (2021), *SFace: Sigmoid-Constrained Hypersphere Loss for Robust Face Recognition*, IEEE Transactions on Image Processing, Tập 30, tr. 2587-2598, mô hình chính thức trong OpenCV Zoo (`face_recognition_sface_2021dec.onnx`).

[5] Tsung-Yi Lin và cộng sự (2014), *Microsoft COCO: Common Objects in Context*, Kỷ yếu Hội nghị European Conference on Computer Vision (ECCV), Springer, tr. 740-755.

[6] OpenCV Team (2025), *OpenCV Objdetect Module: DNN-based Face Detection And Recognition (`cv::FaceDetectorYN` & `cv::FaceRecognizerSF`)*, Tài liệu tham chiếu OpenCV 5.x, truy cập tại: https://docs.opencv.org/.

### 11.2. Nhóm tài liệu về hệ thống nhúng, giao thức camera và phần cứng

[7] Raspberry Pi Ltd (2024), *Raspberry Pi 4 Model B Datasheet & Frequency Management / Thermal Throttling Documentation*, Raspberry Pi Official Documentation, truy cập tại: https://www.raspberrypi.com/documentation/computers/raspberry-pi.html.

[8] ONVIF Forum (2022), *ONVIF Streaming Specification & Profile T Specification (RTSP Audio Backchannel and PTZ Service)*, Open Network Video Interface Forum, truy cập tại: https://www.onvif.org/profiles/profile-t/.

[9] Henning Schulzrinne và cộng sự (1998, cập nhật RFC 7826), *Real Time Streaming Protocol (RTSP) & RTP Payload for ITU-T Recommendation G.711 Audio (PCMA/PCMU)*, Internet Engineering Task Force (IETF).

[10] Ben Nuttall, Dave Jones (2024), *gpiozero: A simple interface to GPIO devices with Raspberry Pi (including MockFactory testing architecture)*, Tài liệu chính thức ReadTheDocs, truy cập tại: https://gpiozero.readthedocs.io/.

[11] Cees H. Taal, Richard C. Hendriks, Richard Heusdens, Jesper Jensen (2011), *An Algorithm for Intelligibility Prediction of Time-Frequency Weighted Noisy Speech (STOI)*, IEEE Transactions on Audio, Speech, and Language Processing, Tập 19, Số 7, tr. 2125-2136.

### 11.3. Nhóm tài liệu về Web Backend, Ứng dụng di động và Quy định pháp lý

[12] Pallets Projects (2025), *Flask 3.1 Web Development Framework Documentation*, truy cập tại: https://flask.palletsprojects.com/.

[13] D. Richard Hipp và SQLite Consortium (2025), *Write-Ahead Logging (`WAL`) & Threading Modes in SQLite*, SQLite Official Documentation, truy cập tại: https://www.sqlite.org/wal.html.

[14] Meta Platforms & Expo Team (2026), *React Native 0.88 & Expo SDK 58 Technical Documentation*, Expo Docs, truy cập tại: https://docs.expo.dev/.

[15] Chính phủ nước Cộng hòa Xã hội Chủ nghĩa Việt Nam (2023), *Nghị định số 13/2023/NĐ-CP ngày 17/04/2023 về Bảo vệ dữ liệu cá nhân* (quy định về dữ liệu cá nhân nhạy cảm và dữ liệu sinh trắc học).

## CHƯƠNG 12. PHỤ LỤC

### 12.1. Phụ lục A: Cấu trúc thư mục chính của dự án

Dưới đây là cấu trúc cây thư mục thực tế của toàn bộ kho mã nguồn dự án sau khi chuẩn hóa gói Python theo `pyproject.toml` và tích hợp ứng dụng di động:

```text
Cuoiki/
├── pyproject.toml                      # Khai báo gói posture-monitor và cấu hình pytest
├── requirements.txt                    # Danh sách khóa cứng phiên bản thư viện trên Pi 4
├── config.yaml                         # Toàn bộ tham số cấu hình và chú thích nguồn đo
├── models/                             # Thư mục lưu trữ tập trung 4 mô hình AI pretrained
│   ├── yolo11n-pose.pt                 # Trọng số gốc ước lượng 17 khớp xương (xuất NCNN)
│   ├── yolo11n.pt                      # Trọng số gốc phát hiện lớp cell phone (xuất NCNN)
│   ├── yunet.onnx                      # Mô hình phát hiện khuôn mặt và 5 điểm mốc
│   └── sface.onnx                      # Mô hình trích xuất đặc trưng mặt 128 chiều
├── src/posture_monitor/                # Mã nguồn chính chia làm 9 phân hệ một chiều
│   ├── core/                           # config, labels, atomic_io, credentials, logging
│   ├── camera/                         # capture (RTSP xả đệm), control (PTZ), audio (RTP)
│   ├── hardware/                       # gpio_real, gpio_mock (MockFactory), sensors
│   ├── storage/                        # sqlite_store (chế độ WAL, gom lô 10 giây)
│   ├── vision/                         # yolo_loader, pose, phone_detector, phone, faces
│   ├── domain/                         # presence, study_session, schedule, people_service
│   ├── alerts/                         # speaker_alert, espeak_synth, voice_library
│   ├── web/                            # app, context, state, streaming, privacy, routes/
│   └── cli/                            # parser, monitor_runner, cmd_*, benchmark/
├── apps/mobile/                        # Ứng dụng di động React Native / Expo SDK 58
│   ├── App.tsx                         # SafeArea -> AppProvider -> TabNavigator (6 tab)
│   ├── src/api/                        # client.ts, payload.ts, format.ts, errors.ts
│   ├── src/components/                 # ui.tsx, LearnerSignalsSection, PostureStatusSection
│   ├── src/hooks/                      # usePoll.ts (AbortController), useAsyncAction.ts
│   ├── src/screens/                    # CameraScreen (màn gộp) và 5 màn chức năng
│   └── test/                           # 160 bài test Node thuần + 29 bài test giao diện UI
├── scripts/                            # camera_probe, hw_selftest, face_threshold_probe
├── tests/                              # 60 tệp kiểm thử Python chia theo 10 thư mục con
├── docs/                               # SPEC_V2, SPEC_V3, WEB_DASHBOARD, MODELS
└── BaoCao/                             # Mã nguồn báo cáo, hình vẽ và trình xuất .docx
```

### 12.2. Phụ lục B: Cấu hình thư viện Backend Python và hệ thống Raspberry Pi

Các gói hệ thống cài đặt qua `apt` trên Raspberry Pi OS Trixie (`aarch64`, tạo môi trường ảo bắt buộc kèm cờ `--system-site-packages` để kế thừa trình điều khiển phần cứng):

```bash
sudo apt install -y python3-picamera2 python3-lgpio python3-numpy ffmpeg espeak-ng
python3 -m venv --system-site-packages venv
```

Danh sách phiên bản thư viện Python khóa cứng trong `requirements.txt` đã kiểm chứng thực tế trên vi xử lý Cortex-A72 (Python `3.13.5`):

```text
ultralytics==8.4.191
torch==2.7.1
torchvision==0.22.1
ncnn==1.0.20261020
pnnx==20260526
opencv-python==5.0.0.93
numpy==2.2.4
PyYAML>=6.0
Flask==3.1.3
gpiozero==2.0.1.post3
psutil>=6.0
rtsp-backchannel==0.5.2
```

### 12.3. Phụ lục C: Cấu hình thư viện Ứng dụng di động React Native / Expo

Trích tệp cấu hình `apps/mobile/package.json` quy định các gói chạy ứng dụng trên Expo SDK 58 và bộ công cụ kiểm thử giao diện hai tầng:

```json
{
  "name": "posture-mobile",
  "version": "1.0.0",
  "scripts": {
    "start": "expo start",
    "test": "node --import ./test/register-ts.mjs --test --test-isolation=none \"test/*.test.mjs\"",
    "verify": "node --import ./test/register-ts.mjs --test --test-isolation=none \"test/ui/*.test.mjs\"",
    "verify:all": "npm run test && npm run verify",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@react-native-async-storage/async-storage": "2.2.0",
    "expo": "~58.0.24",
    "expo-status-bar": "~58.0.5",
    "react": "19.3.0",
    "react-native": "0.88.1",
    "react-native-safe-area-context": "~5.11.1",
    "react-native-webview": "14.0.1"
  },
  "devDependencies": {
    "@types/react": "~19.3.0",
    "jsdom": "^29.1.1",
    "react-dom": "19.3.0",
    "react-native-web": "~0.21.0",
    "typescript": "~6.0.3"
  }
}
```

### 12.4. Phụ lục D: Danh mục đầy đủ các API của Backend Flask

Bảng 35 tổng hợp toàn bộ các endpoint HTTP do phân hệ `web/routes/` phục vụ cho cả Web Dashboard và Ứng dụng di động.

*Bảng 35. Danh mục tổng hợp các endpoint API của máy chủ Flask trên cổng 8000*

| Nhóm mô-đun | Phương thức & Đường dẫn | Kiểu trả về | Chức năng xử lý chính và mã trạng thái đặc biệt |
|---|---|---|---|
| `routes/core.py` | `GET /` | `text/html` | Trả giao diện trang quản trị tiếng Việt offline-first (`200 OK`) |
| `routes/core.py` | `GET /api/status` | `application/json` | Trạng thái tổng hợp vòng lặp, điểm tư thế, `stale`, `muted` và các cờ cấu hình |
| `routes/core.py` | `GET /api/history` | `application/json` | Dữ liệu thống kê theo khung giờ/ngày từ SQLite (`400` sai tham số, `503` thiếu DB) |
| `routes/core.py` | `POST /api/calibrate` | `application/json` | Đặt cờ yêu cầu hiệu chỉnh một lần xuống `DashboardState` |
| `routes/core.py` | `POST /api/mute` | `application/json` | Đảo hoặc đặt trực tiếp trạng thái tắt tiếng cảnh báo (`muted`) |
| `routes/media.py` | `GET /stream` | `multipart/x-mixed-replace` | Luồng video MJPEG trực tiếp từ RAM (`403` nếu `web.stream_enabled: false`) |
| `routes/media.py` | `GET /api/frame` | `image/jpeg` | Trả một khung ảnh JPEG đơn lẻ kèm `Cache-Control: no-store` cho App di động (`403` / `503`) |
| `routes/diagnostics.py` | `POST /api/ptz` | `application/json` | Điều khiển xoay camera 4 hướng qua ONVIF (`400`, `501` không hỗ trợ, `502` lỗi mạng, `503`) |
| `routes/diagnostics.py` | `POST /api/speak` | `application/json` | Phát thử âm thanh ra loa camera qua RTSP backchannel (`403` tắt loa, `409` loa bận, `503`) |
| `routes/diagnostics.py` | `GET · POST /api/voice` | `application/json` | Truy vấn danh sách giọng hoặc đổi giọng cảnh báo (`giongnam`, `giongnu`, `espeak`) |
| `routes/session.py` | `GET /api/session` | `application/json` | Đọc trạng thái phiên học (`idle`, `running`, `finished`) và số giây còn lại |
| `routes/session.py` | `POST /api/session/start` · `/stop` | `application/json` | Mở phiên học mới theo số phút yêu cầu (`400` sai thời lượng) hoặc dừng phiên hiện tại |
| `routes/session.py` | `GET · PUT /api/schedule` | `application/json` | Đọc hoặc cập nhật khung giờ cho phép cảnh báo theo các thứ trong tuần |
| `routes/session.py` | `GET /api/violations` | `application/json` | Truy vấn danh sách vi phạm (`ABSENT`, `PHONE_USE`, `IMPOSTOR`) đã lọc sạch sự kiện kỹ thuật |
| `routes/people.py` | `GET · POST · DELETE /api/people` | `application/json` | Liệt kê hồ sơ (đã qua `scrub_biometrics`), khởi tạo quét người mới hoặc xóa người học (`404`, `503`) |
| `routes/people.py` | `GET /api/enroll/<id>` · `POST .../cancel` | `application/json` | Theo dõi tiến độ 5 bước quét khuôn mặt hoặc hủy phiên quét đang diễn ra |
| `routes/people.py` | `POST /api/select` | `application/json` | Chọn mã định danh người học đang ngồi học trong phiên |
| `routes/people.py` | `GET /api/signals` | `application/json` | Trả bộ 3 tín hiệu nghiệp vụ (`presence`, `phone`, `identity`) kèm tuổi `age_s` và cờ `fresh` |

### 12.5. Phụ lục E: Mẫu dữ liệu JSON trả về từ các API trọng tâm

Mẫu phản hồi thực tế từ endpoint `GET /api/signals` khi người học đã đăng ký đang ngồi học nghiêm túc trong phiên:

```json
{
  "ok": true,
  "selected_person": {
    "id": "p_01",
    "name": "Phan Gia Bảo"
  },
  "signals": {
    "presence": {
      "value": "co_mat",
      "age_s": 0.18,
      "fresh": true
    },
    "phone": {
      "value": "khong",
      "age_s": 0.18,
      "fresh": true
    },
    "identity": {
      "value": "MATCH",
      "matched_name": "Phan Gia Bảo",
      "reason": null,
      "age_s": 0.94,
      "fresh": true
    }
  }
}
```

Mẫu phản hồi thực tế từ endpoint `GET /api/violations?limit=2` phục vụ màn hình lịch sử vi phạm trên ứng dụng di động:

```json
{
  "ok": true,
  "items": [
    {
      "id": 42,
      "session_id": 7,
      "ts": 1764073820.5,
      "kind": "PHONE_USE",
      "kind_text": "Dùng điện thoại",
      "duration_s": 4.2
    },
    {
      "id": 41,
      "session_id": 7,
      "ts": 1764073510.0,
      "kind": "ABSENT",
      "kind_text": "Rời khỏi bàn học",
      "duration_s": 8.5
    }
  ]
}
```

### 12.6. Phụ lục F: Trích cấu hình chuẩn `config.yaml` và các lệnh vận hành

Đoạn cấu hình chuẩn trong `config.yaml` (thông tin nhạy cảm của đường dẫn camera được truyền qua biến môi trường hoặc che tự động, tuyệt đối không lưu mật khẩu thật trong kho mã):

```yaml
camera:
  source: "rtsp://admin:***@192.168.17.106:554/1/2"
  width: 704
  height: 576
  view: front
  onvif:
    enabled: auto
    host: ""
    port: 80
  speaker:
    enabled: true
    port: 554
    stream_path: "/1/2"

model:
  name: yolo11n-pose
  format: ncnn
  imgsz: 320
  target_fps: 5
  kp_conf_min: 0.5

phone:
  enabled: true
  detect_every_n_frames: 2
  conf_threshold: 0.06
  wrist_conf_min: 0.25
  shoulder_ratio: 1.0
  box_ttl_s: 0.5
  hold_s: 1.0
  miss_tolerance_frames: 4

face:
  enabled: true
  detector: models/yunet.onnx
  recognizer: models/sface.onnx
  interval_s: 2.0
  score_threshold: 0.7
  match_threshold: null

session:
  default_minutes: 60
  auto_start: false

web:
  host: 0.0.0.0
  port: 8000
  stream_enabled: true
```

Danh mục các câu lệnh chuẩn để khởi chạy, đo kiểm và kiểm thử toàn bộ hệ thống:

```bash
# 1. Cài đặt gói ở chế độ phát triển và chạy toàn bộ bộ kiểm thử Python
pip install -e .
python -m pytest tests/ -q

# 2. Vận hành hệ thống giám sát thực tế và các công cụ phần cứng trên Raspberry Pi 4
python -m posture_monitor run --no-gpio
python -m posture_monitor run
python -m posture_monitor speak-test --speed 0.85
python -m posture_monitor benchmark --seconds 60 --profile pose_phone_face
python scripts/camera_probe.py
python scripts/face_threshold_probe.py --name "Chính chủ" --name2 "Người khác" --samples 10

# 3. Kiểm tra kiểu tĩnh, chạy 189 bài kiểm thử và mở máy chủ Expo cho Ứng dụng di động
cd apps/mobile
npm run typecheck
npm run verify:all
npx expo start --lan
```
