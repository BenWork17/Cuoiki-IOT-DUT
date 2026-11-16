// Bản thay thế tối thiểu của react-native-safe-area-context cho môi trường
// Node: không có cửa sổ/thiết bị nào để hỏi inset. Chỉ dùng trong kiểm thử.
const path = require('path');
const React = require(path.join(__dirname, '..', '..', 'node_modules', 'react'));

const INSETS = { top: 59, left: 0, right: 0, bottom: 34 };
const FRAME = { x: 0, y: 0, width: 402, height: 874 };

function SafeAreaProvider({ children }) {
  return children;
}
function SafeAreaView({ children }) {
  return children;
}
function useSafeAreaInsets() {
  return INSETS;
}
function useSafeAreaFrame() {
  return FRAME;
}
function useSafeArea() {
  return { insets: INSETS, frame: FRAME };
}
function withSafeAreaInsets(C) {
  return C;
}

module.exports = {
  SafeAreaProvider,
  SafeAreaView,
  SafeAreaInsetsContext: React.createContext(INSETS),
  SafeAreaFrameContext: React.createContext(FRAME),
  SafeAreaConsumer: ({ children }) => children(INSETS),
  useSafeAreaInsets,
  useSafeAreaFrame,
  useSafeArea,
  withSafeAreaInsets,
  initialWindowMetrics: { insets: INSETS, frame: FRAME },
};
