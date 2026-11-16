/**
 * Màn 5 — Điều khiển.
 *
 * `POST /api/mute` (`app.py:535-555`) và `POST /api/ptz` (`app.py:688-744`).
 *
 * Hai điểm bắt buộc:
 * 1. **Nút PTZ gửi đúng `{"direction": "...", "duration": 0.5}`** — server
 *    kiểm hướng trước khi chạm camera và trả 400 với câu tiếng Việt
 *    (`app.py:711-717`). App gửi đúng hằng số ở đây thay vì để mỗi nút tự
 *    ghép thân request.
 * 2. **Không chồng request:** bấm liên tiếp chỉ tạo tối đa một request đang
 *    chạy (`busy` khoá cả bốn nút). Camera PTZ thật sự xoay, hai lệnh chồng
 *    nhau sẽ làm camera dừng ở chỗ không ai muốn.
 * 3. Lỗi hiện **đúng câu server gửi**. "Camera không hỗ trợ PTZ." khác hẳn
 *    "Lỗi" chung, và người dùng cần biết là do camera hay do mạng.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { PtzDirection } from '../api/client';
import type { ApiError } from '../api/errors';
import { normalizeStatus } from '../api/payload';
import { Button, Card, Divider, ErrorBanner, Label, Notice, Screen } from '../components/ui';
import { useApp } from '../context/AppContext';
import { usePoll, type PollResult } from '../hooks/usePoll';
import { colors, radius, spacing, type as typo } from '../theme';

/** Thời gian xoay mỗi cú bấm, khớp `PTZ_DEFAULT_DURATION_S` của server. */
const PTZ_DURATION_S = 0.5;

/** Bốn hướng, nhãn tiếng Việt lấy từ `PTZ_DIRECTION_TEXT` (`app.py:69-74`). */
const PTZ_BUTTONS: ReadonlyArray<{ direction: PtzDirection; label: string; glyph: string }> = [
  { direction: 'up', label: 'Lên', glyph: '↑' },
  { direction: 'left', label: 'Trái', glyph: '←' },
  { direction: 'down', label: 'Xuống', glyph: '↓' },
  { direction: 'right', label: 'Phải', glyph: '→' },
];

type Status = { muted: boolean };

/**
 * Lệnh vừa thất bại, để nút "Gửi lại" làm lại **đúng** việc đó.
 *
 * Vì sao cần: bấm "Tắt tiếng" mà lỗi, nút cũ chỉ gọi `refresh()` — tức tải lại
 * trạng thái, **không** gửi lại lệnh. Người dùng bấm "Thử lại", thấy dải lỗi
 * biến mất, và tin rằng tiếng đã tắt trong khi thực ra chưa có lệnh nào được
 * gửi lại. Đây là kiểu lỗi khiến người dùng mất niềm tin vào cả app.
 */
type LastAction = { kind: 'mute' } | { kind: 'ptz'; direction: PtzDirection };

/** `focused` do thanh tab truyền vào: màn chỉ hỏi máy chủ khi đang được hiện. */
export function ControlScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();

  const [muteBusy, setMuteBusy] = useState(false);
  const [ptzBusy, setPtzBusy] = useState<PtzDirection | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [lastAction, setLastAction] = useState<LastAction | null>(null);
  const [message, setMessage] = useState('');
  /** Muted cục bộ, cập nhật ngay sau phản hồi server để không phải chờ nhịp sau. */
  const [mutedOverride, setMutedOverride] = useState<boolean | null>(null);

  /**
   * Đã unmount chưa. Mọi `setState` sau `await` đều phải kiểm cờ này: người
   * dùng bấm lệnh rồi chuyển tab ngay là chuyện thường, và setState trên
   * component đã unmount là rò rỉ + cảnh báo trong log.
   */
  const mounted = useRef(true);
  /** Request đang chạy của lệnh, để huỷ khi rời màn. */
  const actionController = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // Huỷ lệnh đang chờ: máy chủ Pi không phải xử lý một lệnh mà không ai
      // còn xem kết quả, và promise không cố setState sau unmount.
      actionController.current?.abort();
      actionController.current = null;
    };
  }, []);

  const fetcher = useCallback(
    async (signal: AbortSignal): Promise<PollResult<Status>> => {
      const result = await api.getStatus({ signal });
      if (result.ok) {
        return {
          ok: true,
          data: { muted: normalizeStatus(result.data).muted },
          ignored: false,
        };
      }
      if (result.error.kind === 'cancelled') {
        return { ok: false, error: result.error, ignored: true };
      }
      return { ok: false, error: result.error, ignored: false };
    },
    [api],
  );

  const { data, error: pollError, loading, refresh } = usePoll(fetcher, {
    enabled: focused && !configLoading && !!baseUrl,
  });

  const muted = mutedOverride ?? data?.muted ?? false;

  const toggleMute = useCallback(async (): Promise<void> => {
    // Huỷ lệnh trước nếu còn treo, để hai lần bấm không tạo hai request.
    actionController.current?.abort();
    const controller = new AbortController();
    actionController.current = controller;
    setMuteBusy(true);
    setError(null);
    setLastAction(null);
    setMessage('');
    // Gửi giá trị đích thay vì để server đảo: nếu hai lần bấm chen nhau, đảo
    // trạng thái hai lần cho kết quả sai mà không ai thấy.
    const result = await api.setMuted(!muted, { signal: controller.signal });
    if (!mounted.current || controller.signal.aborted) return;
    setMuteBusy(false);
    if (result.ok) {
      const next = typeof result.data?.muted === 'boolean' ? result.data.muted : !muted;
      setMutedOverride(next);
      setMessage(
        typeof result.data?.message === 'string'
          ? result.data.message
          : next
            ? 'Đã tắt tiếng cảnh báo.'
            : 'Đã bật lại tiếng cảnh báo.',
      );
      return;
    }
    if (result.error.kind === 'cancelled') return;
    setError(result.error);
    // Nhớ **đúng** lệnh vừa hỏng để nút "Gửi lại" gửi lại nó, không phải chỉ
    // tải lại trạng thái.
    setLastAction({ kind: 'mute' });
  }, [api, muted]);

  const movePtz = useCallback(
    async (direction: PtzDirection): Promise<void> => {
      if (ptzBusy) return;
      actionController.current?.abort();
      const controller = new AbortController();
      actionController.current = controller;
      setPtzBusy(direction);
      setError(null);
      setLastAction(null);
      setMessage('');
      const result = await api.movePtz(direction, PTZ_DURATION_S, {
        signal: controller.signal,
      });
      if (!mounted.current || controller.signal.aborted) return;
      setPtzBusy(null);
      if (result.ok) {
        setMessage(
          typeof result.data?.message === 'string'
            ? result.data.message
            : `Đã xoay camera sang ${labelOf(direction)}.`,
        );
        return;
      }
      if (result.error.kind === 'cancelled') return;
      setError(result.error);
      setLastAction({ kind: 'ptz', direction });
    },
    [api, ptzBusy],
  );

  /** Gửi lại **đúng** lệnh vừa hỏng (mute hoặc PTZ cùng hướng). */
  const retryAction = useCallback((): void => {
    if (!lastAction) return;
    if (lastAction.kind === 'mute') void toggleMute();
    else void movePtz(lastAction.direction);
  }, [lastAction, toggleMute, movePtz]);

  /** Chỉ dùng cho lỗi của vòng đọc trạng thái — tải lại, không gửi lệnh. */
  const retryPoll = useCallback((): void => {
    refresh();
  }, [refresh]);

  return (
    <Screen title="Điều khiển" subtitle="Tắt tiếng cảnh báo và xoay camera">
      {!baseUrl ? (
        <Notice
          title="Chưa cấu hình máy chủ"
          body="Mở tab Kết nối, nhập IP LAN của máy chạy dashboard rồi lưu lại."
          tone="warn"
        />
      ) : null}

      {pollError ? (
        <ErrorBanner message={pollError.message} onRetry={retryPoll} retrying={loading} />
      ) : null}

      {error ? (
        <ErrorBanner
          title="Không gửi được lệnh"
          message={error.message}
          retryLabel="Gửi lại"
          onRetry={retryAction}
          retrying={muteBusy || ptzBusy !== null}
        />
      ) : null}

      {message ? (
        <View style={styles.success}>
          <Text style={[typo.body, { color: colors.good }]}>{message}</Text>
        </View>
      ) : null}

      <Card>
        <Label>Tiếng cảnh báo</Label>
        <Text style={[typo.heading, { color: muted ? colors.warn : colors.good }]}>
          {muted ? 'Đang tắt tiếng' : 'Đang bật tiếng'}
        </Text>
        <Text style={[typo.caption, styles.muted]}>
          Tắt tiếng chỉ bỏ loa/buzzer; hệ thống vẫn phân tích và ghi nhận như bình thường.
        </Text>
        <Button
          label={muted ? 'Bật lại tiếng cảnh báo' : 'Tắt tiếng cảnh báo'}
          onPress={() => void toggleMute()}
          variant={muted ? 'primary' : 'secondary'}
          busy={muteBusy}
          disabled={!baseUrl}
        />
      </Card>

      <Divider />

      <Card>
        <Label>Xoay camera (PTZ)</Label>
        <Text style={[typo.caption, styles.muted]}>
          Mỗi lần bấm xoay {PTZ_DURATION_S.toString().replace('.', ',')} giây.
        </Text>

        <View style={styles.ptzGrid}>
          <View style={styles.ptzRow}>
            <PtzButton
              entry={PTZ_BUTTONS[0]!}
              onPress={movePtz}
              busyWith={ptzBusy}
              disabled={!baseUrl}
            />
          </View>
          <View style={styles.ptzRow}>
            <PtzButton
              entry={PTZ_BUTTONS[1]!}
              onPress={movePtz}
              busyWith={ptzBusy}
              disabled={!baseUrl}
            />
            <PtzButton
              entry={PTZ_BUTTONS[2]!}
              onPress={movePtz}
              busyWith={ptzBusy}
              disabled={!baseUrl}
            />
            <PtzButton
              entry={PTZ_BUTTONS[3]!}
              onPress={movePtz}
              busyWith={ptzBusy}
              disabled={!baseUrl}
            />
          </View>
        </View>

        <Text style={[typo.caption, styles.faint]}>
          Camera không hỗ trợ PTZ sẽ báo bằng câu tiếng Việt của máy chủ, không phải lỗi
          chung.
        </Text>
      </Card>
    </Screen>
  );
}

function PtzButton({
  entry,
  onPress,
  busyWith,
  disabled,
}: {
  entry: { direction: PtzDirection; label: string; glyph: string };
  onPress: (direction: PtzDirection) => Promise<void>;
  busyWith: PtzDirection | null;
  disabled: boolean;
}): React.ReactElement {
  // Khoá **cả bốn** nút khi một nút đang chạy: hai lệnh PTZ chồng nhau làm
  // camera dừng ở hướng không ai chọn.
  const busy = busyWith === entry.direction;
  const blocked = disabled || (busyWith !== null && !busy);
  return (
    <Button
      label={`${entry.glyph} ${entry.label}`}
      onPress={() => void onPress(entry.direction)}
      variant="secondary"
      busy={busy}
      disabled={blocked}
      style={styles.ptzButton}
    />
  );
}

/** Nhãn tiếng Việt của hướng, dùng cho câu dự phòng khi server không gửi. */
function labelOf(direction: PtzDirection): string {
  switch (direction) {
    case 'left':
      return 'trái';
    case 'right':
      return 'phải';
    case 'up':
      return 'lên';
    default:
      return 'xuống';
  }
}

const styles = StyleSheet.create({
  ptzGrid: {
    gap: spacing.sm,
    alignItems: 'center',
  },
  ptzRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    justifyContent: 'center',
    width: '100%',
  },
  ptzButton: {
    flex: 1,
    minWidth: 92,
  },
  success: {
    backgroundColor: 'rgba(95,224,176,0.10)',
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(95,224,176,0.35)',
    padding: spacing.lg,
  },
  muted: {
    color: colors.textMuted,
  },
  faint: {
    color: colors.textFaint,
  },
});


