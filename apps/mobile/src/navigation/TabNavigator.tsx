/**
 * Thanh điều hướng 6 tab hỗ trợ cả hai chế độ Sáng & Tối:
 * 1. `Camera` — Khung hình trực tiếp + 3 Tín hiệu + Trạng thái tư thế Bento 2×2
 * 2. `Người học` — Chọn người đang học, thêm người mới (quét khuôn mặt 5 bước) & xoá
 * 3. `Phiên học` — Bắt đầu / dừng phiên đếm ngược
 * 4. `Điều khiển` — Bật/tắt tiếng, xoay camera PTZ & chọn giọng đọc cảnh báo
 * 5. `Vi phạm` — Nhật ký rời bàn, dùng điện thoại, sai người học
 * 6. `Kết nối` — Địa chỉ máy chủ LAN & chế độ giao diện Sáng / Tối
 */
import React, { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '../context/AppContext';
import { CameraScreen } from '../screens/CameraScreen';
import { ControlScreen } from '../screens/ControlScreen';
import { PeopleScreen } from '../screens/PeopleScreen';
import { SessionScreen } from '../screens/SessionScreen';
import { SettingsScreen } from '../screens/SettingsScreen';
import { ViolationsScreen } from '../screens/ViolationsScreen';
import { spacing } from '../theme';

export type TabKey =
  | 'camera'
  | 'people'
  | 'session'
  | 'control'
  | 'violations'
  | 'settings';

type TabDef = {
  key: TabKey;
  label: string;
  glyph: string;
  render: (props: { focused: boolean; navigate: (to: TabKey) => void }) => React.ReactElement;
};

export const TABS: readonly TabDef[] = [
  {
    key: 'camera',
    label: 'Camera',
    glyph: '▣',
    render: ({ focused, navigate }) => (
      <CameraScreen focused={focused} onOpenPeople={() => navigate('people')} />
    ),
  },
  {
    key: 'people',
    label: 'Người học',
    glyph: '◉',
    render: ({ focused }) => <PeopleScreen focused={focused} />,
  },
  {
    key: 'session',
    label: 'Phiên học',
    glyph: '◷',
    render: ({ focused }) => <SessionScreen focused={focused} />,
  },
  {
    key: 'control',
    label: 'Điều khiển',
    glyph: '✛',
    render: ({ focused }) => <ControlScreen focused={focused} />,
  },
  {
    key: 'violations',
    label: 'Vi phạm',
    glyph: '⊞',
    render: ({ focused }) => <ViolationsScreen focused={focused} />,
  },
  {
    key: 'settings',
    label: 'Kết nối',
    glyph: '⚙',
    render: () => <SettingsScreen />,
  },
];

export function TabNavigator(): React.ReactElement {
  const [active, setActive] = useState<TabKey>('camera');
  const insets = useSafeAreaInsets();
  const { palette, typo } = useTheme();
  const current = useMemo(
    () => TABS.find((tab) => tab.key === active) ?? TABS[0]!,
    [active],
  );

  return (
    <View style={[styles.root, { backgroundColor: palette.background }]}>
      <View style={styles.content}>
        {current.render({ focused: true, navigate: setActive })}
      </View>

      <View
        style={[
          styles.tabBar,
          {
            backgroundColor: palette.tabBar,
            borderTopColor: palette.border,
            paddingBottom: Math.max(insets.bottom, spacing.sm),
          },
        ]}
      >
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
                  { color: selected ? palette.accent : palette.textFaint },
                ]}
              >
                {tab.glyph}
              </Text>
              <Text
                style={[
                  typo.caption,
                  styles.tabLabel,
                  { color: selected ? palette.accent : palette.textMuted },
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
                  selected ? { backgroundColor: palette.accent } : null,
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
  },
  content: {
    flex: 1,
  },
  tabBar: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    borderTopWidth: StyleSheet.hairlineWidth,
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
});
