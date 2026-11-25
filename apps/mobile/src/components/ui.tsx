/**
 * Các khối giao diện dùng chung, tự động thích ứng với cả hai chế độ Sáng & Tối.
 */
import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { Tone } from '../api/payload';
import { useTheme } from '../context/AppContext';
import { darkColors, radius, spacing, type ThemePalette } from '../theme';

/** Nút gạt nhanh chế độ Sáng / Tối ngay góc trên màn hình. */
export function ThemeTogglePill(): React.ReactElement {
  const { isDark, palette, toggleThemeMode } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={
        isDark ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'
      }
      onPress={() => void toggleThemeMode()}
      style={({ pressed }) => [
        styles.themePill,
        {
          backgroundColor: palette.surfaceElevated,
          borderColor: palette.border,
        },
        pressed ? styles.buttonPressed : null,
      ]}
    >
      <Text style={[styles.themePillGlyph, { color: isDark ? palette.warn : palette.accent }]}>
        {isDark ? '☀' : '☾'}
      </Text>
      <Text style={[styles.themePillText, { color: palette.textMuted }]}>
        {isDark ? 'Sáng' : 'Tối'}
      </Text>
    </Pressable>
  );
}

/** Một màn hình: tiêu đề, mô tả ngắn, công tắc Sáng/Tối, vùng cuộn có chừa chỗ cho thanh tab. */
export function Screen({
  title,
  subtitle,
  children,
  right,
  scroll = true,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  right?: React.ReactNode;
  scroll?: boolean;
}): React.ReactElement {
  const insets = useSafeAreaInsets();
  const { palette, typo } = useTheme();
  const body = (
    <View style={styles.screenBody}>
      <View style={styles.screenHead}>
        <View style={styles.screenHeadText}>
          <Text style={typo.title}>{title}</Text>
          {subtitle ? (
            <Text style={[typo.caption, { color: palette.textMuted }]}>{subtitle}</Text>
          ) : null}
        </View>
        <View style={styles.screenHeadRight}>
          {right}
          <ThemeTogglePill />
        </View>
      </View>
      {children}
    </View>
  );

  return (
    <View
      style={[
        styles.screen,
        { backgroundColor: palette.background, paddingTop: insets.top + spacing.md },
      ]}
    >
      {scroll ? (
        <ScrollView
          contentContainerStyle={{ paddingBottom: insets.bottom + 96 }}
          showsVerticalScrollIndicator={false}
        >
          {body}
        </ScrollView>
      ) : (
        <View style={{ flex: 1, paddingBottom: insets.bottom + 72 }}>{body}</View>
      )}
    </View>
  );
}

/** Một thẻ nội dung. */
export function Card({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}): React.ReactElement {
  const { palette } = useTheme();
  return (
    <View
      style={[
        styles.card,
        { backgroundColor: palette.surface, borderColor: palette.border },
        style,
      ]}
    >
      {children}
    </View>
  );
}

/** Nhãn in hoa nhỏ phía trên một giá trị. */
export function Label({ children }: { children: React.ReactNode }): React.ReactElement {
  const { typo } = useTheme();
  return <Text style={typo.label}>{children}</Text>;
}

/** Một cặp nhãn + giá trị xếp dọc. */
export function Stat({
  label,
  value,
  hint,
  tone = 'idle',
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: Tone;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  return (
    <View style={styles.stat}>
      <Label>{label}</Label>
      <Text style={[typo.number, { color: toneColor(tone, palette) }]} numberOfLines={2}>
        {value}
      </Text>
      {hint ? (
        <Text style={[typo.caption, { color: palette.textFaint }]}>{hint}</Text>
      ) : null}
    </View>
  );
}

/** Màu chữ tương ứng tông trạng thái. */
export function toneColor(tone: Tone, palette: ThemePalette = darkColors): string {
  switch (tone) {
    case 'good':
      return palette.good;
    case 'warn':
      return palette.warn;
    case 'bad':
      return palette.bad;
    default:
      return palette.text;
  }
}

/** Màu nền nhạt của tông, dùng cho chip và dải cảnh báo. */
export function toneSurface(tone: Tone, palette: ThemePalette = darkColors): string {
  switch (tone) {
    case 'good':
      return palette.goodWash;
    case 'warn':
      return palette.warnWash;
    case 'bad':
      return palette.badWash;
    default:
      return palette.surfaceRaised;
  }
}

/** Viền chip rõ hơn nền một chút, để chip không "dính" vào thẻ. */
export function toneBorder(tone: Tone, palette: ThemePalette = darkColors): string {
  switch (tone) {
    case 'good':
      return palette.goodBorder;
    case 'warn':
      return palette.warnBorder;
    case 'bad':
      return palette.badBorder;
    default:
      return palette.border;
  }
}

/** Chip nhỏ: nhãn phân loại, trạng thái phụ. */
export function Chip({
  text,
  tone = 'idle',
}: {
  text: string;
  tone?: Tone;
}): React.ReactElement {
  const { palette } = useTheme();
  return (
    <View
      style={[
        styles.chip,
        {
          backgroundColor: toneSurface(tone, palette),
          borderColor: toneBorder(tone, palette),
        },
      ]}
    >
      <Text style={[styles.chipText, { color: toneColor(tone, palette) }]}>{text}</Text>
    </View>
  );
}

/** Nút bấm với 4 mức nhấn mạnh. */
export function Button({
  label,
  onPress,
  variant = 'secondary',
  disabled = false,
  busy = false,
  accessibilityLabel,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'quiet' | 'danger';
  disabled?: boolean;
  busy?: boolean;
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  const inactive = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: inactive, busy }}
      disabled={inactive}
      onPress={inactive ? undefined : onPress}
      style={({ pressed }) => [
        styles.button,
        buttonVariantStyle(variant, inactive, palette),
        pressed && !inactive ? styles.buttonPressed : null,
        style,
      ]}
    >
      {busy ? (
        <ActivityIndicator
          size="small"
          color={
            variant === 'primary'
              ? palette.onAccent
              : variant === 'danger'
                ? palette.onBad
                : palette.text
          }
        />
      ) : (
        <Text style={[typo.button, { color: buttonTextColor(variant, inactive, palette) }]}>
          {label}
        </Text>
      )}
    </Pressable>
  );
}

function buttonVariantStyle(
  variant: 'primary' | 'secondary' | 'quiet' | 'danger',
  inactive: boolean,
  palette: ThemePalette,
): ViewStyle {
  if (inactive) {
    return {
      backgroundColor: palette.surfaceRaised,
      borderColor: palette.border,
      opacity: 0.55,
    };
  }
  switch (variant) {
    case 'primary':
      return { backgroundColor: palette.accent, borderColor: palette.accent };
    case 'danger':
      return { backgroundColor: palette.bad, borderColor: palette.bad };
    case 'quiet':
      return { backgroundColor: 'transparent', borderColor: palette.border };
    default:
      return { backgroundColor: palette.surfaceRaised, borderColor: palette.borderStrong };
  }
}

function buttonTextColor(
  variant: 'primary' | 'secondary' | 'quiet' | 'danger',
  inactive: boolean,
  palette: ThemePalette,
): string {
  if (inactive) return palette.textMuted;
  if (variant === 'primary') return palette.onAccent;
  if (variant === 'danger') return palette.onBad;
  return palette.text;
}

/** Dải báo lỗi kèm nút **Thử lại**. */
export function ErrorBanner({
  title = 'Không lấy được dữ liệu',
  message,
  onRetry,
  retrying = false,
  retryLabel = 'Thử lại',
  hint,
}: {
  title?: string;
  message: string;
  onRetry: () => void;
  retrying?: boolean;
  retryLabel?: string;
  hint?: string;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  return (
    <View
      style={[
        styles.errorBanner,
        { backgroundColor: palette.badWash, borderColor: palette.badBorder },
      ]}
    >
      <View style={styles.errorTextBlock}>
        <Text style={[typo.heading, { color: palette.bad }]}>{title}</Text>
        <Text style={[typo.body, { color: palette.text }]}>{message}</Text>
        {hint ? (
          <Text style={[typo.caption, { color: palette.textMuted }]}>{hint}</Text>
        ) : null}
      </View>
      <Button label={retryLabel} onPress={onRetry} variant="quiet" busy={retrying} />
    </View>
  );
}

/** Dải thông tin trung tính (hướng dẫn, ghi chú). */
export function Notice({
  title,
  body,
  tone = 'warn',
}: {
  title: string;
  body: string;
  tone?: Tone;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  return (
    <View
      style={[
        styles.notice,
        {
          backgroundColor: toneSurface(tone, palette),
          borderColor: toneBorder(tone, palette),
        },
      ]}
    >
      <Text style={[typo.heading, { color: toneColor(tone, palette) }]}>{title}</Text>
      <Text style={[typo.body, { color: palette.text }]}>{body}</Text>
    </View>
  );
}

/** Trạng thái rỗng hướng dẫn người dùng làm gì tiếp. */
export function EmptyState({
  title,
  body,
  actionLabel,
  onAction,
}: {
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  return (
    <Card style={styles.empty}>
      <Text style={typo.heading}>{title}</Text>
      <Text style={[typo.body, { color: palette.textMuted }]}>{body}</Text>
      {actionLabel && onAction ? (
        <Button label={actionLabel} onPress={onAction} variant="primary" />
      ) : null}
    </Card>
  );
}

/** Hàng có nhãn bên trái và giá trị bên phải; dùng cho danh sách thông tin. */
export function KeyValue({
  label,
  value,
  tone = 'idle',
}: {
  label: string;
  value: string;
  tone?: Tone;
}): React.ReactElement {
  const { palette, typo } = useTheme();
  return (
    <View style={styles.keyValue}>
      <Text style={[typo.caption, styles.keyValueLabel]}>{label}</Text>
      <Text style={[typo.body, { color: toneColor(tone, palette) }]}>{value}</Text>
    </View>
  );
}

/** Vạch ngăn mảnh. */
export function Divider(): React.ReactElement {
  const { palette } = useTheme();
  return <View style={[styles.divider, { backgroundColor: palette.border }]} />;
}

/** Hướng dẫn dùng chung khi chưa lưu địa chỉ máy chủ. */
export function UnconfiguredNotice({
  body = 'Mở tab Kết nối, nhập IP LAN của máy chạy dashboard (ví dụ http://192.168.x.x:8000) rồi lưu lại.',
}: {
  body?: string;
} = {}): React.ReactElement {
  return <Notice title="Chưa cấu hình máy chủ" body={body} tone="warn" />;
}

/** Thẻ quay chờ phản hồi lần đầu từ máy chủ. */
export function LoadingCard({
  label = 'Đang hỏi máy chủ…',
}: {
  label?: string;
} = {}): React.ReactElement {
  const { palette, typo } = useTheme();
  return (
    <Card style={styles.loadingCard}>
      <ActivityIndicator color={palette.accent} />
      <Text style={[typo.caption, { color: palette.textMuted }]}>{label}</Text>
    </Card>
  );
}

/** Dải xác nhận thao tác thành công. */
export function SuccessBanner({ message }: { message: string }): React.ReactElement {
  const { palette, typo } = useTheme();
  return (
    <View
      style={[
        styles.successBanner,
        { backgroundColor: palette.goodWash, borderColor: palette.goodBorder },
      ]}
    >
      <Text style={[typo.body, { color: palette.good }]}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
  },
  screenBody: {
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
  },
  screenHead: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  screenHeadText: {
    flex: 1,
    gap: 2,
  },
  screenHeadRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    flexShrink: 0,
  },
  themePill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  themePillGlyph: {
    fontSize: 12,
    lineHeight: 15,
    fontWeight: '700',
  },
  themePillText: {
    fontSize: 11,
    lineHeight: 14,
    fontWeight: '700',
  },
  card: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.lg,
    gap: spacing.md,
  },
  stat: {
    gap: 2,
  },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    alignSelf: 'flex-start',
  },
  chipText: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  button: {
    minHeight: 46,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonPressed: {
    opacity: 0.75,
  },
  errorBanner: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.lg,
    gap: spacing.md,
  },
  errorTextBlock: {
    gap: 4,
  },
  notice: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.lg,
    gap: 6,
  },
  empty: {
    alignItems: 'flex-start',
    gap: spacing.md,
  },
  keyValue: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: spacing.md,
    paddingVertical: 2,
  },
  keyValueLabel: {
    flexShrink: 0,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
    marginVertical: spacing.xs,
  },
  loadingCard: {
    alignItems: 'center',
    gap: spacing.sm,
  },
  successBanner: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.lg,
  },
});
