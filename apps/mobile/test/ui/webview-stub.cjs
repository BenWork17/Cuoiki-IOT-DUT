// Bản giả `react-native-webview` cho kiểm thử giao diện bằng Node thuần.
//
// Vì sao cần: gói thật phân nhánh nền tảng bằng `lib/WebView.ios.js` /
// `lib/WebView.android.js` và `lib/index.js` gọi `require("./WebView")`
// **không kèm đuôi**. Metro của Expo phân giải được kiểu đó, còn Node thuần
// thì không — nên `npm run verify` chết ngay khi nạp `CameraScreen.tsx`
// (tệp có `import { WebView } from 'react-native-webview'`).
//
// Component giả vẽ ra một phần tử `div` để test DOM vẫn thấy "có WebView",
// kiểm được `source.uri`, và gọi được `WebView.__lastProps.onError()` để mô
// phỏng luồng `/stream` hỏng.
const React = require('react');

function WebView(props) {
  WebView.__lastProps = props;
  return React.createElement('div', {
    'data-testid': 'rn-webview',
    'data-uri': props && props.source ? props.source.uri : undefined,
  });
}
WebView.__lastProps = null;

module.exports = { WebView, default: WebView };
