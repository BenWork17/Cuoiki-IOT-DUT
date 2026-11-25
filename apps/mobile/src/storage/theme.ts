/**
 * Lưu chế độ giao diện Sáng / Tối (`light` | `dark`) bằng AsyncStorage.
 *
 * Mặc định lần đầu mở app là `'dark'` (Nocturne Telemetry) nếu người dùng chưa
 * từng chọn; khi đã chọn Sáng hoặc Tối, lựa chọn được giữ nguyên qua các lần mở lại.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

export type ThemeMode = 'dark' | 'light';

export const THEME_MODE_KEY = 'posture-mobile/theme-mode/v1';

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === 'dark' || value === 'light';
}

/** Đọc chế độ đã lưu; trả `null` nếu chưa lưu hoặc giá trị hỏng. */
export async function loadThemeMode(): Promise<ThemeMode | null> {
  try {
    const stored = await AsyncStorage.getItem(THEME_MODE_KEY);
    if (!stored) return null;
    const trimmed = stored.trim().toLowerCase();
    return isThemeMode(trimmed) ? trimmed : null;
  } catch {
    return null;
  }
}

/** Ghi chế độ giao diện xuống bộ nhớ; trả `false` nếu lỗi. */
export async function saveThemeMode(mode: ThemeMode): Promise<boolean> {
  try {
    await AsyncStorage.setItem(THEME_MODE_KEY, mode);
    return true;
  } catch {
    return false;
  }
}
