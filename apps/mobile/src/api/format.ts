/**
 * Các hàm định dạng số liệu và thời gian dùng chung cho toàn app.
 *
 * **Không import `react-native`** — chạy trực tiếp trong Node thuần (`npm test`).
 *
 * Gom về một tệp để mọi màn hình dùng chung một quy ước trình bày:
 * - Dấu thập phân kiểu Việt Nam (`,` thay vì `.`) cho điểm, tuổi tín hiệu, thời lượng.
 * - Đồng hồ giờ máy `HH:MM:SS` hai chữ số cố định, không lệ thuộc dữ liệu ICU
 *   đầy đủ hay rút gọn trên Hermes.
 */

/**
 * Định dạng số thực kiểu Việt Nam: dấu phẩy làm dấu thập phân, mặc định 1 chữ số.
 *
 * Dùng chung cho điểm và tuổi tín hiệu để màn hình không trộn hai quy ước
 * ("7.5" cạnh "1,4 s") — trộn như vậy trông như hai nguồn dữ liệu khác nhau.
 */
export function formatDecimal(value: number | null, digits = 1): string {
  if (value === null || !Number.isFinite(value)) return '–';
  return value.toFixed(digits).replace('.', ',');
}

/** "cập nhật 1,4 s trước" hoặc "–" — khớp `formatAge()` của `app.js:136-141`. */
export function formatAge(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '–';
  return `cập nhật ${formatDecimal(seconds)} s trước`;
}

/** "1 phút 20 giây" / "45 giây" — đọc được bằng lời, không phải "80.0 s". */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes === 0) return `${rest} giây`;
  if (rest === 0) return `${minutes} phút`;
  return `${minutes} phút ${rest} giây`;
}

/** "mm:ss" hai chữ số từ số giây; dùng cho đồng hồ đếm ngược (`05:00`). */
export function formatCountdown(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return '–';
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
}

/**
 * Giờ:phút:giây (`HH:MM:SS`) theo **múi giờ máy**.
 *
 * Ghép thủ công `padStart(2, '0')` thay vì `toLocaleTimeString('vi-VN')` để
 * kết quả luôn cố định 8 ký tự trên cả Hermes lẫn Node, và không ném lỗi khi
 * mốc thời gian không hợp lệ.
 */
export function formatClock(epochMs: number): string {
  if (!Number.isFinite(epochMs)) return '--:--:--';
  const d = new Date(epochMs);
  if (Number.isNaN(d.getTime())) return '--:--:--';
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

/**
 * Chữ cho một giá trị trạng thái mà app không có nhãn.
 *
 * Khớp `unknownText()` của `app.js:130-134`: hiện nguyên giá trị thô, không
 * im lặng đổi thành "Chưa rõ" trần.
 */
export function unknownText(rawState: unknown): string {
  if (rawState === null || rawState === undefined) {
    return 'Chưa rõ (server không gửi giá trị)';
  }
  const shown = String(rawState);
  if (!shown) return 'Chưa rõ (server không gửi giá trị)';
  return `Chưa rõ (${shown})`;
}
