/**
 * Nạp môi trường để chạy app React Native thật trong Node (không cần Metro,
 * không cần máy ảo, không cần iPhone).
 *
 * Vì sao có tệp này: các bài kiểm trong `test/ui/` phải **tái lập được** —
 * người khác clone repo, `npm install`, `npm run verify` là chạy ra cùng kết
 * quả. Trước đây những bài này nằm trong `.scratch/` (bị gitignore) nên con số
 * "N/N PASS" không ai kiểm lại được; đó là lỗi bị đánh giá ở vòng 3.
 *
 * Cách làm:
 * - Hook `require` của Babel biên dịch `.ts`/`.tsx` tại chỗ (app dùng import
 *   không đuôi như Metro vẫn hiểu).
 * - `react-native` được trỏ sang `react-native-web` để chạy trong Node.
 * - `react-native-safe-area-context` được thay bằng bản giả: gói thật là
 *   native module, không có cửa sổ để hỏi inset.
 * - jsdom cung cấp DOM để `useEffect`/`setInterval` thật sự chạy.
 */
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import Module from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
export const APP = path.resolve(HERE, '..', '..');

/**
 * Báo lỗi bằng câu tiếng Việt nếu thiếu gói, thay vì stack trace
 * `Cannot find module 'jsdom'` — người chạy chỉ cần biết phải `npm install`.
 */
export function requireDep(name) {
  try {
    return require(path.join(APP, 'node_modules', name));
  } catch {
    throw new Error(
      `Thiếu gói "${name}" để chạy kiểm thử giao diện. Chạy "npm install" trong ` +
        `apps/mobile trước (các gói này nằm trong devDependencies).`,
    );
  }
}

const babel = requireDep('@babel/core');

// 1) Biên dịch TS/TSX khi require.
for (const ext of ['.ts', '.tsx']) {
  Module._extensions[ext] = function (module, filename) {
    const src = fs.readFileSync(filename, 'utf8');
    const out = babel.transformSync(src, {
      filename,
      babelrc: false,
      configFile: false,
      presets: [
        [
          require.resolve(path.join(APP, 'node_modules/@babel/preset-typescript')),
          { isTSX: true, allExtensions: true },
        ],
        [
          require.resolve(path.join(APP, 'node_modules/@babel/preset-react')),
          { runtime: 'automatic' },
        ],
      ],
      plugins: [
        require.resolve(
          path.join(APP, 'node_modules/@babel/plugin-transform-modules-commonjs'),
        ),
      ],
    });
    module._compile(out.code, filename);
  };
}

// 2) `react-native` → `react-native-web`; gói nào không có thì dùng stub.
const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, parent, ...rest) {
  if (request === 'react-native-safe-area-context') {
    return path.join(HERE, 'safe-area-stub.cjs');
  }
  // `react-native-webview` phân nhánh nền tảng bằng file không đuôi
  // (`require("./WebView")` trong lib/index.js). Metro hiểu, Node thuần thì
  // không — nên thay bằng stub. Không được sửa CameraScreen để né lỗi này.
  if (request === 'react-native-webview') {
    return path.join(HERE, 'webview-stub.cjs');
  }
  if (request === 'react-native') {
    return path.join(APP, 'node_modules/react-native-web/dist/cjs/index.js');
  }
  if (request.startsWith('react-native/')) {
    const sub = request.replace('react-native/', '');
    const rnw = path.join(APP, 'node_modules/react-native-web/dist');
    for (const c of [
      path.join(rnw, sub),
      path.join(rnw, sub) + '.js',
      path.join(rnw, sub, '/index.js'),
    ]) {
      if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
    }
    return path.join(HERE, 'rn-stub.cjs');
  }
  return origResolve.call(this, request, parent, ...rest);
};

// 3) DOM.
const { JSDOM } = requireDep('jsdom');
const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  pretendToBeVisual: true,
});
for (const key of [
  'window',
  'document',
  'navigator',
  'HTMLElement',
  'Node',
  'getComputedStyle',
  'ShadowRoot',
  'CSSStyleSheet',
  'Event',
  'MouseEvent',
  'MutationObserver',
]) {
  const value = dom.window[key] ?? dom.window;
  // `navigator` (và vài global khác) trên Node ≥ 22 là getter chỉ đọc trên
  // globalThis, nên gán thẳng sẽ ném "has only a getter". `defineProperty` ghi
  // đè được mà không phải xoá thuộc tính gốc.
  Object.defineProperty(globalThis, key, {
    value,
    writable: true,
    configurable: true,
    enumerable: false,
  });
}
globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 0);
globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
// React chỉ chạy `act()` khi cờ này bật; thiếu nó thì effect không được flush
// và mọi bài kiểm sẽ thấy màn hình trống.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

export const React = requireDep('react');
export const ReactDOM = requireDep('react-dom/client');
export const act = React.act;
export const SafeAreaProvider = require(path.join(HERE, 'safe-area-stub.cjs'))
  .SafeAreaProvider;

/* ------------------------------------------------------------------ helpers */

/** Chuẩn hoá khoảng trắng để so chuỗi trong DOM. */
export const norm = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();

/** Toàn bộ chữ nhìn thấy của một phần tử. */
export const textOf = (el) => norm(el.textContent);

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * AsyncStorage giả trong bộ nhớ, có sẵn địa chỉ máy chủ.
 *
 * `AppProvider` đọc địa chỉ từ đây; không thay thì mọi màn sẽ dừng ở trạng
 * thái "Chưa cấu hình máy chủ" và không có lời gọi mạng nào để kiểm.
 *
 * **Phải chạy TRƯỚC khi nạp `AppContext`**: `AppContext` giữ tham chiếu tới
 * module này ngay lúc import, nên thay cache sau đó là quá muộn.
 */
export function primeAsyncStorage(baseUrl = 'http://192.168.1.5:8000') {
  const asyncPath = path.join(
    APP,
    'node_modules/@react-native-async-storage/async-storage',
  );
  const store = new Map([['posture-mobile/base-url/v1', baseUrl]]);
  const resolved = require.resolve(asyncPath);
  require.cache[resolved] = {
    id: resolved,
    filename: resolved,
    loaded: true,
    exports: {
      __esModule: true,
      default: {
        getItem: async (k) => store.get(k) ?? null,
        setItem: async (k, v) => {
          store.set(k, v);
        },
        removeItem: async (k) => {
          store.delete(k);
        },
      },
    },
  };
  return store;
}

/**
 * `fetch` giả dùng chung cho mọi bài kiểm trong tiến trình.
 *
 * Vì sao không cấp một `fetch` riêng cho từng tệp test: `npm run verify` chạy
 * với `--test-isolation=none`, nên **tất cả tệp test sống trong cùng một tiến
 * trình**. Nếu mỗi tệp cài `globalThis.fetch` của riêng mình thì tệp nạp sau
 * ghi đè tệp nạp trước, và mảng `calls` của tệp kia vĩnh viễn rỗng — bài kiểm
 * đỏ với thông báo "0 lời gọi" trong khi app hoàn toàn đúng.
 *
 * Cách sửa: một kênh duy nhất. `setScenario()` đổi kịch bản, `calls` là mảng
 * ghi chung, và mỗi bài kiểm tự `resetFetchLog()` ở đầu bài.
 */
const fetchLog = [];
let activeScenario = {};

globalThis.fetch = async (url, init) => {
  const u = String(url).replace(/^https?:\/\/[^/]+/, '');
  const body = init && init.body ? init.body : null;
  fetchLog.push(`${init ? init.method : '?'} ${u}${body ? ' ' + body : ''}`);

  // Kịch bản được tra theo **đường dẫn không kèm query**, để
  // `setScenario({'/api/violations': …})` khớp cả `/api/violations?limit=200`.
  // Nếu tra bằng chuỗi đầy đủ, mọi route có tham số sẽ rơi vào 404 mặc định và
  // bài kiểm đỏ với thông báo "Không có API này" trong khi app gọi hoàn toàn
  // đúng — đúng cái bẫy đã làm đỏ 7 bài Vi phạm lần đầu.
  const pathOnly = u.split('?')[0];
  const respond =
    typeof activeScenario === 'function'
      ? activeScenario(pathOnly, u, init)
      : (activeScenario[pathOnly] ?? activeScenario[u]);
  if (!respond) {
    const text = '{"ok":false,"message":"Không có API này."}';
    return {
      ok: false,
      status: 404,
      headers: { get: () => 'application/json' },
      text: async () => text,
    };
  }
  const headers = respond.headers ?? 'application/json';
  const payload = respond.body;
  return {
    ok: respond.status >= 200 && respond.status < 300,
    status: respond.status,
    headers: { get: () => headers },
    text: async () => (typeof payload === 'string' ? payload : JSON.stringify(payload)),
    blob: async () => new Blob([JSON.stringify(payload)]),
  };
};

/** Mọi lời gọi mạng từ trước tới giờ, dạng `"METHOD /path body"`. */
export const calls = fetchLog;

/** Đổi kịch bản phản hồi (object theo đường dẫn, hoặc hàm nhận đường dẫn). */
export function setScenario(scenario) {
  activeScenario = scenario;
}

/** Xoá nhật ký lời gọi — gọi ở đầu mỗi bài kiểm để đếm chính xác. */
export function resetFetchLog() {
  fetchLog.length = 0;
}

/**
 * Dựng một màn hình vào DOM và trả handle.
 *
 * `errors` gom `console.error` (bỏ qua hai cảnh báo vô hại của môi trường
 * test: `act(...)` và `ResizeObserver`) — bất kỳ lỗi React thật nào cũng phải
 * làm bài kiểm đỏ.
 */
export async function mountScreen(Component, props = { focused: true }) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const root = ReactDOM.createRoot(host);
  const errors = [];
  const originalError = console.error;
  console.error = (...args) => {
    const s = args.join(' ');
    if (!s.includes('act(') && !s.includes('ResizeObserver')) errors.push(s);
  };
  try {
    await act(async () => {
      root.render(
        React.createElement(
          SafeAreaProvider,
          null,
          React.createElement(AppProvider, null, React.createElement(Component, props)),
        ),
      );
    });
    await act(async () => {
      await sleep(250);
    });
  } finally {
    console.error = originalError;
  }
  return {
    host,
    root,
    errors,
    text: () => textOf(host),
    /** Nút theo `aria-label` (ưu tiên) hoặc theo chữ hiển thị. */
    button(label) {
      const els = [...host.querySelectorAll('[role="button"], button')];
      return (
        els.find((e) => (e.getAttribute('aria-label') ?? '') === label) ??
        els.find((e) => textOf(e) === label) ??
        null
      );
    },
    async click(label) {
      const target = this.button(label);
      if (!target) return false;
      await act(async () => {
        target.dispatchEvent(
          new dom.window.MouseEvent('click', { bubbles: true, cancelable: true }),
        );
      });
      await act(async () => {
        await sleep(250);
      });
      return true;
    },
    async wait(ms) {
      await act(async () => {
        await sleep(ms);
      });
    },
    async unmount() {
      await act(async () => {
        root.unmount();
      });
      host.remove();
    },
  };
}

// Nạp AsyncStorage giả TRƯỚC khi `AppProvider` được require bên dưới.
const primedStore = primeAsyncStorage();
export { primedStore };

/** `AppProvider` — nạp sau khi hook resolve và AsyncStorage giả đã cài. */
export const AppProvider = require(path.join(APP, 'src/context/AppContext.tsx'))
  .AppProvider;
