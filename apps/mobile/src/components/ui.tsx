/**
 * Các khối giao diện dùng chung. Tách khỏi màn hình để bố cục và màu chỉ có
 * một nguồn — và để `Screen` lo phần an toàn (SafeArea) một lần cho cả app.
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

import { colors, radius, spacing, type as typo } from '../theme';
import type { Tone } from '../api/payload';

/** Một màn hình: tiêu đề, mô tả ngắn, vùng cuộn có chừa chỗ cho thanh tab. */
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
  const body = (
    <View style={styles.screenBody}>
      <View style={styles.screenHead}>
        <View style={styles.screenHeadText}>
          <Text style={typo.title}>{title}</Text>
          {subtitle ? <Text style={[typo.caption, styles.subtitle]}>{subtitle}</Text> : null}
        </View>
        {right}
      </View>
      {children}
    </View>
  );

  return (
    <View style={[styles.screen, { paddingTop: insets.top + spacing.md }]}>
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
  return <View style={[styles.card, style]}>{children}</View>;
}

/** Nhãn in hoa nhỏ phía trên một giá trị. */
export function Label({ children }: { children: React.ReactNode }): React.ReactElement {
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
  return (
    <View style={styles.stat}>
      <Label>{label}</Label>
      <Text style={[typo.number, { color: toneColor(tone) }]} numberOfLines={2}>
        {value}
      </Text>
      {hint ? <Text style={[typo.caption, styles.statHint]}>{hint}</Text> : null}
    </View>
  );
}

/** Màu chữ tương ứng tông trạng thái. */
export function toneColor(tone: Tone): string {
  switch (tone) {
    case 'good':
      return colors.good;
    case 'warn':
      return colors.warn;
    case 'bad':
      return colors.bad;
    default:
      return colors.text;
  }
}

/** Màu nền nhạt của tông, dùng cho chip và dải cảnh báo. */
export function toneSurface(tone: Tone): string {
  switch (tone) {
    case 'good':
      return 'rgba(95,224,176,0.12)';
    case 'warn':
      return 'rgba(240,180,41,0.14)';
    case 'bad':
      return 'rgba(255,107,94,0.14)';
    default:
      return colors.surfaceRaised;
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
  return (
    <View
      style={[
        styles.chip,
        { backgroundColor: toneSurface(tone), borderColor: toneBorder(tone) },
      ]}
    >
      <Text style={[styles.chipText, { color: toneColor(tone) }]}>{text}</Text>
    </View>
  );
}

/** Viền chip rõ hơn nền một chút, để chip không "dính" vào thẻ. */
function toneBorder(tone: Tone): string {
  switch (tone) {
    case 'good':
      return 'rgba(95,224,176,0.35)';
    case 'warn':
      return 'rgba(240,180,41,0.38)';
    case 'bad':
      return 'rgba(255,107,94,0.38)';
    default:
      return colors.border;
  }
}

/**
 * Nút bấm với 3 mức nhấn mạnh.
 *
 * `disabled` phải chặn cả `onPress` **và** đổi màu: nút trông bấm được mà
 * không có tác dụng là lỗi tệ hơn nút xám.
 */
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
  /**
   * Nhãn cho trình đọc màn hình khi `label` một mình không đủ nghĩa.
   *
   * Ví dụ: danh sách giọng đọc có nhiều nút cùng chữ "Chọn" — trình đọc màn
   * hình đọc ba lần "Chọn" liền nhau và người dùng khiếm thị không biết nút
   * nào đổi sang giọng nào. Truyền "Chọn giọng nữ" vào đây.
   */
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
}): React.ReactElement {
  const inactive = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      // `accessibilityState` một mình không đủ: react-native-web không dịch
      // nó thành `aria-disabled`/`disabled` trên phần tử DOM, nên trình đọc
      // màn hình và các bài kiểm tự động vẫn thấy nút "bấm được". Đặt thêm
      // `accessibilityState` (cho iOS/Android thật) và `disabled` của
      // Pressable (cho web + để chặn tương tác ở tầng nền tảng).
      accessibilityState={{ disabled: inactive, busy }}
      disabled={inactive}
      onPress={inactive ? undefined : onPress}
      style={({ pressed }) => [
        styles.button,
        buttonVariantStyle(variant, inactive),
        pressed && !inactive ? styles.buttonPressed : null,
        style,
      ]}
    >
      {busy ? (
        <ActivityIndicator size="small" color={variant === 'primary' ? colors.onAccent : colors.text} />
      ) : (
        <Text style={[typo.button, { color: buttonTextColor(variant, inactive) }]}>{label}</Text>
      )}
    </Pressable>
  );
}

function buttonVariantStyle(
  variant: 'primary' | 'secondary' | 'quiet' | 'danger',
  inactive: boolean,
): ViewStyle {
  if (inactive) {
    return {
      backgroundColor: colors.surfaceRaised,
      borderColor: colors.border,
      opacity: 0.55,
    };
  }
  switch (variant) {
    case 'primary':
      return { backgroundColor: colors.accent, borderColor: colors.accent };
    case 'danger':
      return { backgroundColor: colors.bad, borderColor: colors.bad };
    case 'quiet':
      return { backgroundColor: 'transparent', borderColor: colors.border };
    default:
      return { backgroundColor: colors.surfaceRaised, borderColor: colors.borderStrong };
  }
}

function buttonTextColor(
  variant: 'primary' | 'secondary' | 'quiet' | 'danger',
  inactive: boolean,
): string {
  if (inactive) return colors.textMuted;
  if (variant === 'primary') return colors.onAccent;
  if (variant === 'danger') return colors.onAccent;
  return colors.text;
}

/**
 * Dải báo lỗi kèm nút **Thử lại**.
 *
 * Yêu cầu §5.2: không nuốt lỗi, mỗi lỗi phải có lý do + nút thử lại. Nên
 * `onRetry` là tham số **bắt buộc** — không có đường nào tạo ra một dải lỗi
 * mà người dùng không thoát ra được.
 */
export function ErrorBanner({
  title = 'Không lấy được dữ liệu',
  message,
  onRetry,
  retrying = false,
  retryLabel = 'Thử lại',
  hint,
}: {
  /**
   * Tiêu đề của dải lỗi. Mặc định nói về việc **đọc** dữ liệu; màn nào lỗi do
   * gửi lệnh (mute, PTZ, bắt đầu phiên) phải truyền tiêu đề riêng — nếu để
   * "Không lấy được dữ liệu" cho một lệnh gửi hỏng thì người dùng hiểu sai là
   * hệ thống không đọc được trạng thái, trong khi lệnh của họ mới là thứ hỏng.
   */
  title?: string;
  message: string;
  onRetry: () => void;
  retrying?: boolean;
  /** Nhãn nút. Lỗi khi gửi lệnh thì "Thử lại" nên nói rõ là gửi lại lệnh. */
  retryLabel?: string;
  hint?: string;
}): React.ReactElement {
  return (
    <View style={styles.errorBanner}>
      <View style={styles.errorTextBlock}>
        <Text style={[typo.heading, { color: colors.bad }]}>{title}</Text>
        <Text style={[typo.body, styles.errorMessage]}>{message}</Text>
        {hint ? <Text style={[typo.caption, styles.errorHint]}>{hint}</Text> : null}
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
  return (
    <View
      style={[
        styles.notice,
        { backgroundColor: toneSurface(tone), borderColor: toneBorder(tone) },
      ]}
    >
      <Text style={[typo.heading, { color: toneColor(tone) }]}>{title}</Text>
      <Text style={[typo.body, styles.noticeBody]}>{body}</Text>
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
  return (
    <Card style={styles.empty}>
      <Text style={typo.heading}>{title}</Text>
      <Text style={[typo.body, styles.emptyBody]}>{body}</Text>
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
  return (
    <View style={styles.keyValue}>
      <Text style={[typo.caption, styles.keyValueLabel]}>{label}</Text>
      <Text style={[typo.body, { color: toneColor(tone) }]}>{value}</Text>
    </View>
  );
}

/** Vạch ngăn mảnh. */
export function Divider(): React.ReactElement {
  return <View style={styles.divider} />;
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
  },
  screenBody: {
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
  },
  screenHead: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: spacing.md,
    marginBottom: spacing.xs,
  },
  screenHeadText: {
    flex: 1,
    gap: 2,
  },
  subtitle: {
    color: colors.textMuted,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.md,
  },
  stat: {
    gap: 2,
  },
  statHint: {
    color: colors.textFaint,
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
    backgroundColor: 'rgba(255,107,94,0.10)',
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(255,107,94,0.40)',
    padding: spacing.lg,
    gap: spacing.md,
  },
  errorTextBlock: {
    gap: 4,
  },
  errorMessage: {
    color: colors.text,
  },
  errorHint: {
    color: colors.textMuted,
  },
  notice: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.lg,
    gap: 6,
  },
  noticeBody: {
    color: colors.text,
  },
  empty: {
    alignItems: 'flex-start',
    gap: spacing.md,
  },
  emptyBody: {
    color: colors.textMuted,
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
    backgroundColor: colors.border,
    marginVertical: spacing.xs,
  },
});
