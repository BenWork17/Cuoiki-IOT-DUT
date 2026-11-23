/**
 * Thanh điều hướng 6 tab theo thiết kế Nocturne Telemetry của Google Stitch.
 *
 * Tab đầu tiên (`Camera`) đóng vai trò màn hình giám sát trung tâm, gộp trọn vẹn:
 * - Khung hình Camera trực tiếp / ảnh tĩnh
 * - 3 Tín hiệu người học trực tiếp (`Có mặt`, `Điện thoại`, `Người đang học`)
 * - Trạng thái tư thế & lưới thông số Bento 2×2
 * Nhờ vậy thanh điều hướng rút gọn từ 8 tab xuống 6 tab thoáng, dễ bấm bằng một tay.
 */
import React, { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CameraScreen } from '../screens/CameraScreen';
import { ControlScreen } from '../screens/ControlScreen';
import { SessionScreen } from '../screens/SessionScreen';
import { SettingsScreen } from '../screens/SettingsScreen';
import { ViolationsScreen } from '../screens/ViolationsScreen';
import { VoiceScreen } from '../screens/VoiceScreen';
import { colors, spacing, type as typo } from '../theme';

export type TabKey =
  | 'camera'
  | 'session'
  | 'control'
  | 'voice'
  | 'violations'
  | 'settings';

type TabDef = {
  key: TabKey;
  label: string;
  glyph: string;
  render: (props: { focused: boolean }) => React.ReactElement;
};

export const TABS: readonly TabDef[] = [
  { key: 'camera', label: 'Camera', glyph: '▣', render: ({ focused }) => <CameraScreen focused={focused} /> },
  { key: 'session', label: 'Phiên học', glyph: '◷', render: ({ focused }) => <SessionScreen focused={focused} /> },
  { key: 'control', label: 'Điều khiển', glyph: '✛', render: ({ focused }) => <ControlScreen focused={focused} /> },
  { key: 'voice', label: 'Giọng đọc', glyph: '♪', render: ({ focused }) => <VoiceScreen focused={focused} /> },
  { key: 'violations', label: 'Vi phạm', glyph: '⊞', render: ({ focused }) => <ViolationsScreen focused={focused} /> },
  { key: 'settings', label: 'Kết nối', glyph: '⚙', render: () => <SettingsScreen /> },
];

export function TabNavigator(): React.ReactElement {
  const [active, setActive] = useState<TabKey>('camera');
  const insets = useSafeAreaInsets();
  const current = useMemo(() => TABS.find((tab) => tab.key === active) ?? TABS[0]!, [active]);

  return (
    <View style={styles.root}>
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
                  { color: selected ? colors.accent : colors.textMuted },
                  selected ? styles.tabLabelSelected : null,
                ]}
                numberOfLines={1}
                adjustsFontSizeToFit
                minimumFontScale={0.82}
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
    fontSize: 18,
    lineHeight: 21,
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
    width: 18,
    borderRadius: 1,
    marginTop: 2,
    backgroundColor: 'transparent',
  },
  tabMarkerActive: {
    backgroundColor: colors.accent,
  },
});
