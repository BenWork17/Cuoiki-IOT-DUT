/**
 * Bảng màu, khoảng cách và kiểu chữ của app.
 *
 * Lý do chọn (xem README §"Vì sao giao diện trông như vậy"):
 * 1. Nền than chì ấm thay vì trắng: app dùng lúc học buổi tối, và khung ảnh
 *    camera là vùng sáng duy nhất cần mắt — nền trắng làm mắt mỏi và làm
 *    ảnh camera chìm đi.
 * 2. Ba màu trạng thái lấy đúng ngữ nghĩa của dashboard web (mint = đang ổn,
 *    hổ phách = cần chú ý, san hô = sai/vắng) để người dùng không phải học
 *    lại quy ước màu khi chuyển từ web sang điện thoại.
 * 3. Số liệu dùng font mono + `tabular-nums` cỡ lớn: điện thoại đặt trên bàn
 *    nên phải đọc được từ xa, và chữ số không được nhảy ngang mỗi lần làm
 *    mới 2 giây.
 */
import { Platform } from 'react-native';
import type { TextStyle } from 'react-native';

export const colors = {
  /** Nền toàn app (than chì ấm, không phải đen tuyệt đối để giảm chói). */
  background: '#12161B',
  /** Nền thẻ, sáng hơn nền một bậc. */
  surface: '#1A2028',
  /** Nền thẻ khi được chọn / đang hoạt động. */
  surfaceRaised: '#212A34',
  /** Đường viền mảnh, đủ thấy trên nền than. */
  border: '#2C3742',
  borderStrong: '#3B4956',
  /** Chữ chính. */
  text: '#E9EEF3',
  /** Chữ phụ (nhãn, ghi chú). */
  textMuted: '#93A1AF',
  /** Chữ mờ nhất, chỉ dùng cho thông tin không quan trọng. */
  textFaint: '#66737F',
  /** Đang ổn / có mặt / đúng người. */
  good: '#5FE0B0',
  /** Cần chú ý / dữ liệu cũ / chưa bật. */
  warn: '#F0B429',
  /** Sai tư thế / vắng / lỗi. */
  bad: '#FF6B5E',
  /** Hành động chính (nút Bắt đầu, Kiểm tra kết nối). */
  accent: '#6AA9FF',
  /** Chữ trên nền màu nhấn. */
  onAccent: '#0B1017',
  /** Lớp phủ mờ cho thanh tab. */
  tabBar: '#161C23',
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 18,
  pill: 999,
} as const;

/** Font hệ thống; tách ra để đổi một chỗ nếu sau này nhúng font riêng. */
const displayFamily = Platform.select({
  ios: 'System',
  android: 'sans-serif',
  default: 'System',
});

/** Font cho số liệu: mono, để chữ số không nhảy bề rộng khi giá trị đổi. */
export const monoFamily = Platform.select({
  ios: 'Menlo',
  android: 'monospace',
  default: 'monospace',
});

export const type = {
  /** Số liệu lớn (điểm, đồng hồ đếm ngược). */
  display: {
    fontFamily: monoFamily,
    fontSize: 40,
    lineHeight: 46,
    fontWeight: '700',
    color: colors.text,
    fontVariant: ['tabular-nums'],
  } satisfies TextStyle,
  /** Số liệu vừa. */
  number: {
    fontFamily: monoFamily,
    fontSize: 20,
    lineHeight: 26,
    fontWeight: '600',
    color: colors.text,
    fontVariant: ['tabular-nums'],
  } satisfies TextStyle,
  /** Tiêu đề màn hình. */
  title: {
    fontFamily: displayFamily,
    fontSize: 24,
    lineHeight: 30,
    fontWeight: '700',
    color: colors.text,
    letterSpacing: -0.4,
  } satisfies TextStyle,
  /** Tiêu đề thẻ. */
  heading: {
    fontFamily: displayFamily,
    fontSize: 16,
    lineHeight: 22,
    fontWeight: '600',
    color: colors.text,
  } satisfies TextStyle,
  /** Chữ nội dung. */
  body: {
    fontFamily: displayFamily,
    fontSize: 15,
    lineHeight: 21,
    fontWeight: '400',
    color: colors.text,
  } satisfies TextStyle,
  /** Chữ phụ dưới một giá trị. */
  caption: {
    fontFamily: displayFamily,
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '400',
    color: colors.textMuted,
  } satisfies TextStyle,
  /** Nhãn nhỏ in hoa, giãn chữ — dùng cho tên trường dữ liệu. */
  label: {
    fontFamily: displayFamily,
    fontSize: 11,
    lineHeight: 14,
    fontWeight: '700',
    color: colors.textMuted,
    letterSpacing: 1.2,
    textTransform: 'uppercase',
  } satisfies TextStyle,
  /** Nhãn trên nút. */
  button: {
    fontFamily: displayFamily,
    fontSize: 15,
    lineHeight: 20,
    fontWeight: '700',
  } satisfies TextStyle,
} as const;
