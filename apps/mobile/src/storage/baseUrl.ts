/**
 * Lưu địa chỉ máy chủ bằng AsyncStorage.
 *
 * Vì sao AsyncStorage mà không phải `expo-secure-store`: đây là **địa chỉ IP
 * trong LAN**, không phải bí mật. Secure-store kéo thêm một native module
 * (và trên iOS là Keychain) trong khi giá trị cần lưu không nhạy cảm. Đổi lại
 * AsyncStorage có sẵn trong Expo Go, không cần dev build.
 *
 * Khoá có tiền tố phiên bản để sau này đổi định dạng thì đọc được cả khoá cũ.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

import { normalizeBaseUrl } from '../api/url';
/** Khoá lưu địa chỉ gốc (đã chuẩn hoá, không có `/` cuối). */
export const BASE_URL_KEY = 'posture-mobile/base-url/v1';

/** Đọc địa chỉ đã lưu; `''` khi chưa có hoặc khi giá trị lưu hỏng. */
export async function loadBaseUrl(): Promise<string> {
  try {
    const stored = await AsyncStorage.getItem(BASE_URL_KEY);
    if (!stored) return '';
    // Chuẩn hoá lại lúc đọc: một giá trị lưu từ bản cũ (có `/` cuối, có
    // khoảng trắng) không được làm hỏng mọi lời gọi sau này.
    const normalized = normalizeBaseUrl(stored);
    return normalized.ok ? normalized.baseUrl : '';
  } catch {
    // Không đọc được bộ nhớ (hiếm) thì coi như chưa cấu hình; màn Kết nối sẽ
    // hiện ô nhập trống thay vì app chết lúc khởi động.
    return '';
  }
}

/**
 * Ghi địa chỉ; trả `false` khi ghi hỏng.
 *
 * Người gọi phải hiện lỗi khi nhận `false`: im lặng nuốt nghĩa là lần mở app
 * sau địa chỉ biến mất mà người dùng không biết vì sao.
 */
export async function saveBaseUrl(baseUrl: string): Promise<boolean> {
  try {
    await AsyncStorage.setItem(BASE_URL_KEY, baseUrl);
    return true;
  } catch {
    return false;
  }
}

/** Xoá địa chỉ đã lưu (nút "Xoá địa chỉ" ở màn Kết nối). */
export async function clearBaseUrl(): Promise<boolean> {
  try {
    await AsyncStorage.removeItem(BASE_URL_KEY);
    return true;
  } catch {
    return false;
  }
}
