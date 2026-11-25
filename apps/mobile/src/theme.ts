/**
 * Hệ thống thiết kế kép cho iOS/Android:
 * 1. "Nocturne Telemetry" (`dark`): nền Slate/Charcoal dịu mắt cho bàn học buổi tối.
 * 2. "Daylight Studio" (`light`): nền xám lạnh sáng (`#F0F2F5`) + thẻ trắng (`#FFFFFF`)
 *    + xanh điểm nhấn (`#1877F2`), đồng bộ trực tiếp với bảng điều khiển Web Dashboard.
 *
 * Kết hợp chữ số đơn cách `tabular-nums` cỡ lớn đọc rõ ở khoảng cách cánh tay
 * và 4 sắc thái ngữ nghĩa đảm bảo độ tương phản chuẩn WCAG AA trên cả hai nền.
 */
import { Platform } from 'react-native';
import type { TextStyle } from 'react-native';
import type { ThemeMode } from './storage/theme';

export type ThemePalette = {
  /** Nền toàn app (L0 Canvas Base). */
  background: string;
  /** Nền khung video (luôn giữ tối sâu để hình ảnh camera nổi bật). */
  surfaceLowest: string;
  /** Nền thẻ tiêu chuẩn (L1 Container Layer). */
  surface: string;
  /** Nền thẻ nổi bật (Status Hero Banner). */
  surfaceElevated: string;
  /** Nền khối tương tác / rãnh chuyển chế độ / ô nhập phụ. */
  surfaceRaised: string;
  /** Đường viền mảnh định hình khối Bento. */
  border: string;
  borderStrong: string;
  /** Chữ chính. */
  text: string;
  /** Chữ phụ / nhãn. */
  textMuted: string;
  /** Chữ mờ / chú thích phụ. */
  textFaint: string;
  /** Tư thế tốt / đang bật / có mặt. */
  good: string;
  onGood: string;
  goodWash: string;
  goodBorder: string;
  /** Cần chú ý / dữ liệu cũ / tắt tiếng. */
  warn: string;
  warnWash: string;
  warnBorder: string;
  /** Sai tư thế / vắng / người lạ / lỗi. */
  bad: string;
  onBad: string;
  badWash: string;
  badBorder: string;
  /** Điều khiển chính & tab đang chọn. */
  accent: string;
  /** Chữ trên nền `accent`. */
  onAccent: string;
  accentWash: string;
  accentBorder: string;
  /** Thanh điều hướng đáy. */
  tabBar: string;
  /** Lớp phủ HUD nằm đè lên khung video (luôn tối bán trong suốt). */
  hudBg: string;
  hudBorder: string;
  hudText: string;
};

export const darkColors: ThemePalette = {
  background: '#0F141A',
  surfaceLowest: '#0A0F14',
  surface: '#171C22',
  surfaceElevated: '#1B222B',
  surfaceRaised: '#252D38',
  border: '#273240',
  borderStrong: '#384657',
  text: '#E6ECF4',
  textMuted: '#94A3B8',
  textFaint: '#64748B',
  good: '#34D399',
  onGood: '#00291B',
  goodWash: 'rgba(52,211,153,0.14)',
  goodBorder: 'rgba(52,211,153,0.36)',
  warn: '#FBBF24',
  warnWash: 'rgba(251,191,36,0.14)',
  warnBorder: 'rgba(251,191,36,0.38)',
  bad: '#F87171',
  onBad: '#07192E',
  badWash: 'rgba(248,113,113,0.14)',
  badBorder: 'rgba(248,113,113,0.38)',
  accent: '#60A5FA',
  onAccent: '#07192E',
  accentWash: 'rgba(96,165,250,0.14)',
  accentBorder: 'rgba(96,165,250,0.38)',
  tabBar: '#0C1117',
  hudBg: 'rgba(10, 15, 20, 0.78)',
  hudBorder: 'rgba(255, 255, 255, 0.08)',
  hudText: '#E6ECF4',
};

export const lightColors: ThemePalette = {
  background: '#F0F2F5',
  surfaceLowest: '#0D1116',
  surface: '#FFFFFF',
  surfaceElevated: '#FFFFFF',
  surfaceRaised: '#E8ECF2',
  border: '#D8DEE6',
  borderStrong: '#B8C2CF',
  text: '#0F172A',
  textMuted: '#475569',
  textFaint: '#64748B',
  good: '#15803D',
  onGood: '#FFFFFF',
  goodWash: '#E7F6EC',
  goodBorder: 'rgba(21,128,61,0.32)',
  warn: '#B45309',
  warnWash: '#FDF4E3',
  warnBorder: 'rgba(180,83,9,0.34)',
  bad: '#DC2626',
  onBad: '#FFFFFF',
  badWash: '#FDEAEA',
  badBorder: 'rgba(220,38,38,0.34)',
  accent: '#1877F2',
  onAccent: '#FFFFFF',
  accentWash: '#E7F0FE',
  accentBorder: 'rgba(24,119,242,0.34)',
  tabBar: '#FFFFFF',
  hudBg: 'rgba(13, 17, 22, 0.76)',
  hudBorder: 'rgba(255, 255, 255, 0.14)',
  hudText: '#F8FAFC',
};

/** Giữ xuất mặc định `colors` (dark) cho tương thích ngược. */
export const colors = darkColors;

export function getPalette(mode: ThemeMode): ThemePalette {
  return mode === 'light' ? lightColors : darkColors;
}

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

export type ThemeTypography = {
  display: TextStyle;
  telemetry: TextStyle;
  number: TextStyle;
  title: TextStyle;
  heading: TextStyle;
  body: TextStyle;
  caption: TextStyle;
  label: TextStyle;
  button: TextStyle;
};

export function createTypography(palette: ThemePalette): ThemeTypography {
  return {
    display: {
      fontFamily: monoFamily,
      fontSize: 38,
      lineHeight: 44,
      fontWeight: '700',
      color: palette.text,
      fontVariant: ['tabular-nums'],
    },
    telemetry: {
      fontFamily: monoFamily,
      fontSize: 26,
      lineHeight: 31,
      fontWeight: '700',
      color: palette.text,
      letterSpacing: -0.5,
      fontVariant: ['tabular-nums'],
    },
    number: {
      fontFamily: monoFamily,
      fontSize: 20,
      lineHeight: 26,
      fontWeight: '600',
      color: palette.text,
      fontVariant: ['tabular-nums'],
    },
    title: {
      fontFamily: displayFamily,
      fontSize: 22,
      lineHeight: 28,
      fontWeight: '700',
      color: palette.text,
      letterSpacing: -0.3,
    },
    heading: {
      fontFamily: displayFamily,
      fontSize: 17,
      lineHeight: 22,
      fontWeight: '700',
      color: palette.text,
      letterSpacing: -0.2,
    },
    body: {
      fontFamily: displayFamily,
      fontSize: 14,
      lineHeight: 20,
      fontWeight: '400',
      color: palette.text,
    },
    caption: {
      fontFamily: displayFamily,
      fontSize: 12,
      lineHeight: 17,
      fontWeight: '400',
      color: palette.textMuted,
    },
    label: {
      fontFamily: displayFamily,
      fontSize: 11,
      lineHeight: 14,
      fontWeight: '700',
      color: palette.textMuted,
      letterSpacing: 0.9,
      textTransform: 'uppercase',
    },
    button: {
      fontFamily: displayFamily,
      fontSize: 14,
      lineHeight: 19,
      fontWeight: '700',
    },
  };
}

/** Giữ xuất mặc định `type` cho tương thích ngược. */
export const type = createTypography(darkColors);
