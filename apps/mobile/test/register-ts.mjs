/**
 * Nạp TypeScript thuần bằng Node, không cần `node_modules` của app.
 *
 * Bối cảnh: máy dev này (Windows) không build native iOS, và yêu cầu là test
 * phải chạy được **không cần build**. Node có "type stripping" nên
 * `import './x.ts'` chạy trực tiếp được, nhưng mã nguồn app viết import kiểu
 * TypeScript quen thuộc (`import './x'`, không đuôi) — Metro của Expo giải
 * được kiểu đó, Node thì không.
 *
 * Thay vì ép mã nguồn app mang đuôi `.ts` trong mọi câu import (Metro chấp
 * nhận, nhưng đó là quy ước lạ và dễ bị sửa nhầm), tệp này cài một hook
 * `resolve` nhỏ: gặp specifier tương đối không có đuôi thì thử thêm `.ts`.
 *
 * Chỉ dùng API công khai của Node (`module.registerHooks`) và **không** đụng
 * vào `node_modules` của app — nhờ vậy `npm test` chạy được cả khi chưa
 * `npm install`, miễn Node đủ mới.
 */
import { registerHooks } from 'node:module';
import { existsSync } from 'node:fs';

// Kiểm tra phiên bản TRƯỚC khi dùng `registerHooks`.
//
// Vì sao cần: `module.registerHooks` chỉ có từ Node 22.18 (trước đó là
// `--experimental-loader` / API khác). Trên Node cũ, dòng `import` ở trên vẫn
// chạy (import tên không tồn tại chỉ thành `undefined`), rồi lời gọi
// `registerHooks(...)` ném "registerHooks is not a function" — một thông điệp
// không nói gì về nguyên nhân thật. Một câu tiếng Việt nói đúng việc phải làm
// rẻ hơn nhiều so với việc người dùng đọc stack trace.
if (typeof registerHooks !== 'function') {
  throw new Error(
    `Cần Node ≥ 22.18 để chạy test (đang dùng ${process.version}). ` +
      'Bản này dùng module.registerHooks để nạp TypeScript không cần build. ' +
      'Hãy nâng Node lên 22.18 trở lên (hoặc 24 LTS) rồi chạy lại `npm test`.',
  );
}

const RESOLVABLE_TS = /\.(ts|tsx)$/;

registerHooks({
  resolve(specifier, context, nextResolve) {
    const isRelative = specifier.startsWith('./') || specifier.startsWith('../');
    const hasExtension = /\.[cm]?[jt]sx?$/.test(specifier);
    if (isRelative && !hasExtension && context.parentURL) {
      // Chỉ thử `.ts`: logic thuần của app không có tệp `.tsx` nào, và giữ
      // danh sách này ngắn để lỗi gõ tên tệp vẫn nổ ra ngay.
      const candidate = new URL(`${specifier}.ts`, context.parentURL);
      if (existsSync(candidate)) {
        return { url: candidate.href, shortCircuit: true, format: 'module-typescript' };
      }
    }
    const resolved = nextResolve(specifier, context);
    if (resolved.url.startsWith('file:') && RESOLVABLE_TS.test(resolved.url)) {
      return { ...resolved, format: 'module-typescript' };
    }
    return resolved;
  },
});
