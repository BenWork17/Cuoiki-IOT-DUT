// Module rỗng cho các import `react-native/...` không có tương ứng trong
// react-native-web. Chỉ dùng trong kiểm thử.
module.exports = new Proxy({}, { get: () => () => null });
