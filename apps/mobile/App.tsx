/**
 * Gốc app: SafeArea + bọc ngữ cảnh + thanh trạng thái thích ứng Sáng/Tối + thanh tab.
 */
import React from 'react';
import { StyleSheet, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AppProvider, useTheme } from './src/context/AppContext';
import { TabNavigator } from './src/navigation/TabNavigator';

function AppShell(): React.ReactElement {
  const { isDark, palette } = useTheme();
  return (
    <View style={[styles.root, { backgroundColor: palette.background }]}>
      {/* Chế độ tối dùng chữ sáng ("light"), chế độ sáng dùng chữ đậm ("dark")
          để đồng hồ và pin ở thanh trạng thái luôn đọc rõ. */}
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <TabNavigator />
    </View>
  );
}

export default function App(): React.ReactElement {
  return (
    <SafeAreaProvider>
      <AppProvider>
        <AppShell />
      </AppProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
});
