// Bản giả `react-native-webview` cho kiểm thử giao diện bằng Node thuần.
//
// Vì sao cần: gói thật phân nhánh nền tảng bằng `lib/WebView.ios.js` /
// `lib/WebView.android.js` và `lib/index.js` gọi `require("./WebView")`
// **không kèm đuôi**. Metro của Expo phân giải được kiểu đó, còn Node thuần
// thì không — nên `npm run verify` chết ngay khi nạp `CameraScreen.tsx`
// (tệp có `import { WebView } from 'react-native-webview'`).
//
// Không sửa `CameraScreen.tsx` để né: mã sản phẩm phải giữ import thật. Chỉ
// thay gói ở tầng kiểm thử, đúng như cách `react-native` đã được trỏ sang
// `react-native-web` trong `env.mjs`.
//
// Component giả vẽ ra một phần tử `div` để test DOM vẫn thấy "có WebView" và
// vẫn kiểm được các prop quan trọng (source.uri, testID...) nếu cần.
const React = require('react');

function WebView(props) {
  return React.createElement('div', {
    'data-testid': 'rn-webview',
    'data-uri': props && props.source ? props.source.uri : undefined,
  });
}

module.exports = { WebView, default: WebView };
