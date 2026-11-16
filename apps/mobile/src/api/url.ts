/**
 * Dựng và kiểm tra địa chỉ máy chủ Pi. **Không import react-native** — nhờ vậy
 * tệp này chạy được bằng Node thuần trong `apps/mobile/test`.
 *
 * Vì sao phải có lớp này thay vì nối chuỗi ở màn hình:
 * - Địa chỉ do người dùng gõ tay. Gõ `192.168.x.x:8000` (không có scheme) là
 *   chuyện bình thường với người quen nhìn `ipconfig`, nhưng `fetch` của
 *   React Native sẽ từ chối; im lặng báo "lỗi mạng" thì người dùng không biết
 *   sửa gì.
 * - `localhost` là bẫy thật: trên iPhone nó trỏ vào **chính iPhone**, không
 *   phải máy chạy dashboard, nên mọi request hỏng ngay lập tức. App vẫn cho
 *   nhập (có người dùng giả lập iOS chạy cùng máy) nhưng phải cảnh báo rõ.
 * - Đường dẫn `/api/...` phải được ghép đúng một chỗ, để đổi tiền tố hay
 *   thêm query chỉ có một nơi sửa.
 */

/** Kết quả chuẩn hoá: hoặc địa chỉ dùng được, hoặc câu tiếng Việt nói vì sao không. */
export type BaseUrlResult =
  | {
      ok: true;
      /** Địa chỉ đã chuẩn hoá, **không** có dấu `/` ở cuối. */
      baseUrl: string;
      /** Cảnh báo không chặn (ví dụ dùng `localhost`). Rỗng nếu không có gì. */
      warnings: string[];
    }
  | { ok: false; message: string };

/** Scheme duy nhất được phép: dashboard trong LAN không có TLS (xem README §ATS). */
const ALLOWED_PROTOCOLS = ['http:', 'https:'];

/** Tên máy luôn trỏ về thiết bị đang chạy app, không phải máy chủ dashboard. */
const LOOPBACK_HOSTS = ['localhost', '127.0.0.1', '::1', '0.0.0.0'];

/**
 * Mẫu địa chỉ dùng trong **câu hướng dẫn cho người dùng**. Cố ý để dạng
 * `192.168.x.x` chứ không phải một IP cụ thể: một IP trông như thật, nằm trong
 * thông điệp lỗi, rất dễ bị đọc nhầm thành "app mặc định gọi địa chỉ này".
 * Mọi giá trị máy chủ thật đều do người dùng nhập và lưu trong AsyncStorage.
 */
const EXAMPLE_URL = 'http://192.168.x.x:8000';

/**
 * Chuẩn hoá chuỗi người dùng nhập thành địa chỉ gốc dùng được.
 *
 * Chấp nhận: `192.168.x.x:8000`, `pi.local:8000`, `https://ten-may:8443`.
 * Từ chối: chuỗi rỗng, scheme lạ (`ftp://`), địa chỉ có đường dẫn
 * (`.../api/status`) vì app tự ghép đường dẫn, và địa chỉ có query/hash.
 *
 * Không bao giờ tự thêm cổng: đoán sai cổng sẽ tạo ra lỗi mạng khó hiểu hơn
 * là để người dùng tự nhập, và cổng thật nằm trong `config.yaml` của họ.
 */
export function normalizeBaseUrl(raw: string): BaseUrlResult {
  const trimmed = String(raw ?? '').trim();
  if (!trimmed) {
    return { ok: false, message: 'Chưa nhập địa chỉ máy chủ.' };
  }

  // Người dùng hay dán kèm khoảng trắng/dấu xuống dòng từ clipboard.
  const compact = trimmed.replace(/\s+/g, '');
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(compact)
    ? compact
    : `http://${compact}`;

  let parsed: URL;
  try {
    parsed = new URL(withScheme);
  } catch {
    return {
      ok: false,
      message:
        `Địa chỉ "${trimmed}" không đọc được. Nhập dạng ${EXAMPLE_URL} ` +
        '(IP LAN của máy chạy dashboard và cổng, thường là 8000).',
    };
  }

  if (!ALLOWED_PROTOCOLS.includes(parsed.protocol)) {
    return {
      ok: false,
      message:
        `Địa chỉ dùng "${parsed.protocol}//" nhưng app chỉ gọi được http:// ` +
        'hoặc https://.',
    };
  }

  if (!parsed.hostname) {
    return {
      ok: false,
      message: `Địa chỉ "${trimmed}" thiếu tên máy hoặc IP.`,
    };
  }

  // App tự ghép `/api/...`, nên một đường dẫn kèm theo chắc chắn sẽ tạo ra
  // URL sai kiểu `.../api/status/api/status`. Nói thẳng thay vì đoán ý.
  const path = parsed.pathname.replace(/\/+$/, '');
  if (path) {
    return {
      ok: false,
      message:
        `Chỉ nhập địa chỉ gốc, không kèm đường dẫn (đang có "${parsed.pathname}"). ` +
        `Ví dụ đúng: ${EXAMPLE_URL}`,
    };
  }

  if (parsed.search || parsed.hash) {
    return {
      ok: false,
      message: 'Địa chỉ không được kèm "?" hay "#". Chỉ nhập IP và cổng.',
    };
  }

  const warnings: string[] = [];
  if (LOOPBACK_HOSTS.includes(parsed.hostname.toLowerCase())) {
    warnings.push(
      'Địa chỉ này trỏ vào chính chiếc điện thoại, không phải máy chạy dashboard. ' +
        `Trên iPhone, hãy dùng IP LAN của máy/Pi (ví dụ ${EXAMPLE_URL}).`,
    );
  }

  // `URL` đã bỏ `/` cuối và hạ scheme/host về chữ thường; ghép lại thủ công
  // để giữ nguyên chữ hoa trong tên máy nếu người dùng cố ý viết.
  const baseUrl = `${parsed.protocol}//${parsed.host}`;
  return { ok: true, baseUrl, warnings };
}

/** Tham số query; `undefined`/`null` bị bỏ qua thay vì in ra "undefined". */
export type QueryValue = string | number | boolean | null | undefined;

/**
 * Ghép đường dẫn API vào địa chỉ gốc.
 *
 * `path` phải bắt đầu bằng `/`; hàm tự thêm nếu thiếu để lời gọi ở màn hình
 * không phải nhớ quy ước. Không dùng `new URL(path, base)` vì React Native
 * (Hermes) có bản `URL` rút gọn, hành vi ghép đường dẫn không đáng tin — nối
 * chuỗi ở đây là hành vi kiểm thử được bằng Node.
 */
export function buildUrl(
  baseUrl: string,
  path: string,
  query?: Record<string, QueryValue>,
): string {
  const root = String(baseUrl ?? '').replace(/\/+$/, '');
  const suffix = path.startsWith('/') ? path : `/${path}`;
  const pairs: string[] = [];
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
    }
  }
  const search = pairs.length ? `?${pairs.join('&')}` : '';
  return `${root}${suffix}${search}`;
}

/**
 * Địa chỉ rút gọn để hiện trong thông điệp lỗi: bỏ scheme cho dễ đọc, giữ
 * cổng. Chỉ dùng cho chữ hiển thị, không dùng để gọi mạng.
 */
export function displayHost(baseUrl: string): string {
  return String(baseUrl ?? '')
    .replace(/^https?:\/\//i, '')
    .replace(/\/+$/, '');
}
