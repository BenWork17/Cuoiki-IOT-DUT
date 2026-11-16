/**
 * Điều hướng bằng thanh tab **tự viết**.
 *
 * Vì sao không dùng `@react-navigation/bottom-tabs` (yêu cầu cho phép chọn
 * phương án ít phụ thuộc nhất, và phải nêu lý do):
 * 1. `@react-navigation/native` + `bottom-tabs` kéo thêm `react-native-screens`,
 *    `@react-navigation/elements`, `use-latest-callback`… Mỗi gói là một chỗ
 *    có thể lệch phiên bản với Expo Go — mà lệch phiên bản trong Expo Go là
 *    lỗi cài đặt, không phải lỗi mã. App chỉ có **7 màn cố định, không tham
 *    số route**, nên toàn bộ máy móc đó không đổi lấy được gì.
 * 2. Chỉ màn đang hiện được mount. Nhờ vậy vòng tự làm mới của màn khác
 *    **dừng hẳn** khi chuyển tab (không còn request nền), đúng yêu cầu §5.2
 *    mà không cần thêm logic "huỷ khi mất focus" ở từng màn.
 * 3. Muốn đổi sang react-navigation sau này thì chỉ cần thay tệp này: mỗi màn
 *    đã nhận `focused` qua prop, không phụ thuộc thư viện điều hướng nào.
 *
 * Đổi lại, app phải tự lo phần SafeArea — dùng `react-native-safe-area-context`
 * (đã có sẵn trong Expo Go, không cần dev build).
 */
import React, { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CameraScreen } from '../screens/CameraScreen';
import { ControlScreen } from '../screens/ControlScreen';
import { SessionScreen } from '../screens/SessionScreen';
import { SettingsScreen } from '../screens/SettingsScreen';
import { SignalsScreen } from '../screens/SignalsScreen';
import { StatusScreen } from '../screens/StatusScreen';
import { VoiceScreen } from '../screens/VoiceScreen';
import { ViolationsScreen } from '../screens/ViolationsScreen';
import { colors, spacing, type as typo } from '../theme';

/**
 * Khoá tab; thứ tự trong mảng là thứ tự trên thanh tab.
 *
 * **Tám tab là giới hạn thực tế của thanh tab này.** iOS Human Interface
 * Guidelines khuyến nghị 3–5 tab; 8 tab trên iPhone SE (bề rộng 320 pt) chỉ
 * còn ~37 pt cho nhãn mỗi tab. Con số đã đo, không phải ước lượng:
 *
 * - 7 tab: 320 pt / 7 ≈ 44,6 pt mỗi tab (trừ 2 pt padding ⇒ ~42,6 pt cho nhãn)
 * - 8 tab: 320 pt / 8 = 39,0 pt mỗi tab (trừ 2 pt padding ⇒ ~37,0 pt cho nhãn)
 *
 * Vì vậy nhãn phải ngắn, cỡ 10 pt, **và** phải cho co: `minWidth: 0` trên tab
 * để nhãn không đẩy tab rộng ra, cộng `numberOfLines={1}` +
 * `adjustsFontSizeToFit` + `minimumFontScale={0.8}` trên nhãn (thu nhỏ tới 8 pt
 * thay vì cắt chữ — cắt chữ thì người dùng đọc thành một từ khác nghĩa).
 *
 * Thêm tab thứ 9 thì phải đổi cách trình bày (menu "Thêm" hoặc thanh cuộn),
 * không chỉ thêm một entry vào mảng này.
 *
 * Glyph: mỗi tab một hình **khác nhau thật sự**. Đã đo và loại `☰` (U+2630,
 * TRIGRAM FOR HEAVEN) vì nó gần trùng `≡` (U+2261, IDENTICAL TO) — cả hai là
 * ba đường ngang, ở cỡ 17 pt không phân biệt được bằng mắt.
 */
type TabKey =
  | 'status'
  | 'camera'
  | 'session'
  | 'signals'
  | 'control'
  | 'voice'
  | 'violations'
  | 'settings';

type TabDef = {
  key: TabKey;
  /** Nhãn ngắn trên thanh tab (phải vừa 8 tab trên iPhone SE — 320 pt). */
  label: string;
  /** Ký tự dấu hiệu; chữ hình học chứ không phải emoji (emoji đổi hình theo
   * hệ điều hành và đọc thành biểu tượng cảm xúc). */
  glyph: string;
  render: (props: { focused: boolean }) => React.ReactElement;
};

const TABS: readonly TabDef[] = [
  { key: 'status', label: 'Trạng thái', glyph: '◉', render: ({ focused }) => <StatusScreen focused={focused} /> },
  { key: 'camera', label: 'Camera', glyph: '▣', render: ({ focused }) => <CameraScreen focused={focused} /> },
  { key: 'session', label: 'Phiên học', glyph: '◷', render: ({ focused }) => <SessionScreen focused={focused} /> },
  { key: 'signals', label: 'Tín hiệu', glyph: '≡', render: ({ focused }) => <SignalsScreen focused={focused} /> },
  { key: 'control', label: 'Điều khiển', glyph: '✛', render: ({ focused }) => <ControlScreen focused={focused} /> },
  { key: 'voice', label: 'Giọng đọc', glyph: '♪', render: ({ focused }) => <VoiceScreen focused={focused} /> },
  // `⊞` (U+229E SQUARED PLUS): ô vuông có chữ thập — đọc là "bảng/danh sách",
  // và không trùng glyph nào ở trên.
  { key: 'violations', label: 'Vi phạm', glyph: '⊞', render: ({ focused }) => <ViolationsScreen focused={focused} /> },
  { key: 'settings', label: 'Kết nối', glyph: '⚙', render: () => <SettingsScreen /> },
];
export function TabNavigator(): React.ReactElement {
  const [active, setActive] = useState<TabKey>('status');
  const insets = useSafeAreaInsets();
  const current = useMemo(() => TABS.find((tab) => tab.key === active) ?? TABS[0]!, [active]);

  return (
    <View style={styles.root}>
      {/* Chỉ mount màn đang hiện: vòng làm mới của màn khác dừng hẳn. */}
      <View style={styles.content}>{current.render({ focused: true })}</View>

      <View style={[styles.tabBar, { paddingBottom: Math.max(insets.bottom, spacing.sm) }]}>
        {TABS.map((tab) => {
          const selected = tab.key === active;
          return (
            <Pressable
              key={tab.key}
              accessibilityRole="tab"
              accessibilityState={{ selected }}
              accessibilityLabel={tab.label}
              onPress={() => setActive(tab.key)}
              style={({ pressed }) => [styles.tab, pressed ? styles.tabPressed : null]}
            >
              <Text
                style={[
                  styles.tabGlyph,
                  { color: selected ? colors.accent : colors.textFaint },
                ]}
              >
                {tab.glyph}
              </Text>
              <Text
                style={[
                  styles.tabLabel,
                  { color: selected ? colors.text : colors.textMuted },
                  selected ? styles.tabLabelSelected : null,
                ]}
                numberOfLines={1}
                // 7 tab trên iPhone SE (320 pt) chỉ còn ~45 pt mỗi tab. Nhãn
                // dài nhất ("Trạng thái", "Điều khiển") không vừa ở cỡ 10 pt
                // với bề rộng đó, nên cho iOS tự thu nhỏ thay vì cắt chữ —
                // cắt chữ thì người dùng đọc thành một từ khác nghĩa.
                adjustsFontSizeToFit
                minimumFontScale={0.8}
                allowFontScaling={false}
              >
                {tab.label}
              </Text>
              <View
                style={[
                  styles.tabMarker,
                  selected ? styles.tabMarkerActive : null,
                ]}
              />
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    flex: 1,
  },
  tabBar: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: colors.tabBar,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  tab: {
    flex: 1,
    // Chặn dưới 0: `flex: 1` chia đều nên với 7 tab trên màn 320 pt mỗi tab
    // còn ~45 pt; nhãn không được đẩy tab rộng ra và làm tràn thanh.
    minWidth: 0,
    alignItems: 'center',
    gap: 2,
    paddingBottom: spacing.xs,
    paddingHorizontal: 1,
  },
  tabPressed: {
    opacity: 0.7,
  },
  tabGlyph: {
    fontSize: 17,
    lineHeight: 20,
  },
  tabLabel: {
    ...typo.caption,
    fontSize: 10,
    lineHeight: 13,
    letterSpacing: 0,
  },
  tabLabelSelected: {
    fontWeight: '700',
  },
  tabMarker: {
    height: 2,
    width: 16,
    borderRadius: 1,
    marginTop: 2,
    backgroundColor: 'transparent',
  },
  tabMarkerActive: {
    backgroundColor: colors.accent,
  },
});
