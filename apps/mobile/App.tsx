/**
 * Gốc app: SafeArea + bọc ngữ cảnh + thanh tab.
 *
 * Không có provider điều hướng nào ở đây vì điều hướng là thanh tab tự viết
 * (`src/navigation/TabNavigator.tsx`) — xem lý do trong tệp đó.
 */
import React from 'react';
import { StyleSheet, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AppProvider } from './src/context/AppContext';
import { TabNavigator } from './src/navigation/TabNavigator';
import { colors } from './src/theme';

export default function App(): React.ReactElement {
  return (
    <SafeAreaProvider>
      <AppProvider>
        <View style={styles.root}>
          {/* Chữ sáng trên nền than: giao diện vốn đã tối, để thanh trạng thái
              sáng sẽ làm mất chỗ đọc giờ pin ở góc màn hình.

              Không còn prop ``backgroundColor``: ``expo-status-bar`` từ SDK 58
              đã bỏ nó (Android 15+ vẽ thanh trạng thái trong suốt và lấy màu
              từ nền của ``View`` bọc ngoài). Nền than đã do ``styles.root``
              đặt, nên bỏ prop này không đổi giao diện. */}
          <StatusBar style="light" />
          <TabNavigator />
        </View>
      </AppProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.background,
  },
});
