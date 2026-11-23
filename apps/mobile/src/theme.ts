/**
 * Hệ thống thiết kế "Nocturne Telemetry" (sinh bởi Google Stitch cho iOS/Android).
 *
 * Bảng màu nền Slate/Charcoal dịu mắt cho bàn học buổi tối (#0F141A / #171C22),
 * kết hợp chữ số đơn cách `tabular-nums` cỡ lớn đọc rõ ở khoảng cách cánh tay
 * và 4 sắc thái ngữ nghĩa rõ ràng (Mint Emerald / Warm Amber / Coral Red / Sky Blue).
 */
import { Platform } from 'react-native';
import type { TextStyle } from 'react-native';

export const colors = {
  /** Nền toàn app (L0 Canvas Base — Slate tối sâu chống chói ban đêm). */
  background: '#0F141A',
  /** Nền khung video / vùng trũng sâu nhất. */
  surfaceLowest: '#0A0F14',
  /** Nền thẻ tiêu chuẩn (L1 Container Layer). */
  surface: '#171C22',
  /** Nền thẻ nổi bật (Status Hero Banner). */
  surfaceElevated: '#1B222B',
  /** Nền khối tương tác / rãnh chuyển chế độ (Segmented Track). */
  surfaceRaised: '#252D38',
  /** Đường viền mảnh định hình khối Bento trên màn OLED. */
  border: '#273240',
  borderStrong: '#384657',
  /** Chữ chính (Slate-100). */
  text: '#E6ECF4',
  /** Chữ phụ / nhãn (Slate-400). */
  textMuted: '#94A3B8',
  /** Chữ mờ / chú thích phụ (Slate-500). */
  textFaint: '#64748B',
  /** Tư thế tốt / đang bật / có mặt (Mint Emerald). */
  good: '#34D399',
  onGood: '#00291B',
  /** Cần chú ý / dữ liệu cũ / tắt tiếng (Warm Amber). */
  warn: '#FBBF24',
  /** Sai tư thế / vắng / người lạ / lỗi (Coral Red). */
  bad: '#F87171',
  /** Điều khiển chính & tab đang chọn (Sky Blue). */
  accent: '#60A5FA',
  /** Chữ trên nền Sky Blue có độ tương phản cao. */
  onAccent: '#07192E',
  /** Thanh điều hướng đáy. */
  tabBar: '#0C1117',
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
  lg: 16,
  xl: 20,
  pill: 999,
} as const;

const displayFamily = Platform.select({
  ios: 'System',
  android: 'sans-serif',
  default: 'System',
});

/** Font cho số liệu thời gian thực: mono + tabular-nums chống nhảy chữ. */
export const monoFamily = Platform.select({
  ios: 'Menlo',
  android: 'monospace',
  default: 'monospace',
});

export const type = {
  /** Số liệu lớn (đồng hồ phiên học). */
  display: {
    fontFamily: monoFamily,
    fontSize: 38,
    lineHeight: 44,
    fontWeight: '700',
    color: colors.text,
    fontVariant: ['tabular-nums'],
  } satisfies TextStyle,
  /** Số liệu Bento Telemetry đọc rõ trên bàn học (`telemetry-numeral`). */
  telemetry: {
    fontFamily: monoFamily,
    fontSize: 26,
    lineHeight: 31,
    fontWeight: '700',
    color: colors.text,
    letterSpacing: -0.5,
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
    fontSize: 22,
    lineHeight: 28,
    fontWeight: '700',
    color: colors.text,
    letterSpacing: -0.3,
  } satisfies TextStyle,
  /** Tiêu đề thẻ / trạng thái chính. */
  heading: {
    fontFamily: displayFamily,
    fontSize: 17,
    lineHeight: 22,
    fontWeight: '700',
    color: colors.text,
    letterSpacing: -0.2,
  } satisfies TextStyle,
  /** Chữ nội dung. */
  body: {
    fontFamily: displayFamily,
    fontSize: 14,
    lineHeight: 20,
    fontWeight: '400',
    color: colors.text,
  } satisfies TextStyle,
  /** Chữ phụ dưới một giá trị. */
  caption: {
    fontFamily: displayFamily,
    fontSize: 12,
    lineHeight: 17,
    fontWeight: '400',
    color: colors.textMuted,
  } satisfies TextStyle,
  /** Nhãn nhỏ in hoa trên các ô Bento (`label-sm`). */
  label: {
    fontFamily: displayFamily,
    fontSize: 11,
    lineHeight: 14,
    fontWeight: '700',
    color: colors.textMuted,
    letterSpacing: 0.9,
    textTransform: 'uppercase',
  } satisfies TextStyle,
  /** Nhãn trên nút. */
  button: {
    fontFamily: displayFamily,
    fontSize: 14,
    lineHeight: 19,
    fontWeight: '700',
  } satisfies TextStyle,
} as const;
