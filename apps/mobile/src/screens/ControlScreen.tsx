/**
 * Màn 5 — Điều khiển.
 *
 * `POST /api/mute` (`app.py:535-555`) và `POST /api/ptz` (`app.py:688-744`).
 *
 * Ba điểm bắt buộc:
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
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { PtzDirection } from '../api/client';
import type { ApiError } from '../api/errors';
import { formatDecimal } from '../api/format';
import { normalizeStatus } from '../api/payload';
import {
  Button,
  Card,
  Divider,
  ErrorBanner,
  Label,
  Screen,
  SuccessBanner,
  UnconfiguredNotice,
} from '../components/ui';
import { useApp } from '../context/AppContext';
import { useAsyncAction } from '../hooks/useAsyncAction';
import { toPollFetcher, usePoll } from '../hooks/usePoll';
import { colors, spacing, type as typo } from '../theme';

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
 */
type LastAction = { kind: 'mute' } | { kind: 'ptz'; direction: PtzDirection };

/** `focused` do thanh tab truyền vào: màn chỉ hỏi máy chủ khi đang được hiện. */
export function ControlScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();
  const { run: runAction } = useAsyncAction();

  const [muteBusy, setMuteBusy] = useState(false);
  const [ptzBusy, setPtzBusy] = useState<PtzDirection | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [lastAction, setLastAction] = useState<LastAction | null>(null);
  const [message, setMessage] = useState('');
  /** Muted cục bộ, cập nhật ngay sau phản hồi server để không phải chờ nhịp sau. */
  const [mutedOverride, setMutedOverride] = useState<boolean | null>(null);

  const fetcher = useMemo(
    () =>
      toPollFetcher(
        (signal) => api.getStatus({ signal }),
        (raw): Status => ({ muted: normalizeStatus(raw).muted }),
      ),
    [api],
  );

  const { data, error: pollError, loading, refresh } = usePoll(fetcher, {
    enabled: focused && !configLoading && !!baseUrl,
  });

  // Khi vòng poll đem dữ liệu mới từ `/api/status` về, xoá giá trị ghi đè cục bộ
  // để thao tác bật/tắt tiếng trên dashboard web được phản ánh đúng trên điện thoại.
  useEffect(() => {
    setMutedOverride(null);
  }, [data]);

  const muted = mutedOverride ?? data?.muted ?? false;

  const toggleMute = useCallback(
    (): Promise<void> =>
      runAction(async ({ signal, isActive }) => {
        setMuteBusy(true);
        setError(null);
        setLastAction(null);
        setMessage('');
        // Gửi giá trị đích thay vì để server đảo: nếu hai lần bấm chen nhau, đảo
        // trạng thái hai lần cho kết quả sai mà không ai thấy.
        const result = await api.setMuted(!muted, { signal });
        if (!isActive()) return;
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
        setLastAction({ kind: 'mute' });
      }),
    [api, muted, runAction],
  );

  const movePtz = useCallback(
    async (direction: PtzDirection): Promise<void> => {
      if (ptzBusy) return;
      await runAction(async ({ signal, isActive }) => {
        setPtzBusy(direction);
        setError(null);
        setLastAction(null);
        setMessage('');
        const result = await api.movePtz(direction, PTZ_DURATION_S, { signal });
        if (!isActive()) return;
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
      });
    },
    [api, ptzBusy, runAction],
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
      {!baseUrl ? <UnconfiguredNotice /> : null}

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

      {message ? <SuccessBanner message={message} /> : null}

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
          Mỗi lần bấm xoay {formatDecimal(PTZ_DURATION_S, 1)} giây.
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
  muted: {
    color: colors.textMuted,
  },
  faint: {
    color: colors.textFaint,
  },
});
