/**
 * Màn Điều khiển — Tắt tiếng cảnh báo, Xoay camera PTZ & Chọn giọng đọc cảnh báo.
 *
 * Khi gộp giọng đọc vào màn Điều khiển (để thanh điều hướng 6 tab dành chỗ cho
 * tab `Người học`), nếu máy chủ chưa có `/api/voice` (404 trong môi trường test
 * đơn lẻ) thì mục giọng đọc tự ẩn yên lặng mà không làm nhiễu phần tắt tiếng/PTZ.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { PtzDirection } from '../api/client';
import type { ApiError } from '../api/errors';
import { formatDecimal } from '../api/format';
import { normalizeStatus, normalizeVoice, type VoiceView } from '../api/payload';
import {
  Button,
  Card,
  Chip,
  Divider,
  ErrorBanner,
  Label,
  Notice,
  Screen,
  SuccessBanner,
  UnconfiguredNotice,
} from '../components/ui';
import { useApp, useTheme } from '../context/AppContext';
import { useAsyncAction } from '../hooks/useAsyncAction';
import { toPollFetcher, usePoll } from '../hooks/usePoll';
import { spacing } from '../theme';

const PTZ_DURATION_S = 0.5;

const PTZ_BUTTONS: ReadonlyArray<{ direction: PtzDirection; label: string; glyph: string }> = [
  { direction: 'up', label: 'Lên', glyph: '↑' },
  { direction: 'left', label: 'Trái', glyph: '←' },
  { direction: 'down', label: 'Xuống', glyph: '↓' },
  { direction: 'right', label: 'Phải', glyph: '→' },
];

type Status = { muted: boolean };

type LastAction =
  | { kind: 'mute' }
  | { kind: 'ptz'; direction: PtzDirection }
  | { kind: 'voice'; voiceId: string };

export function ControlScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();
  const { palette, typo } = useTheme();
  const { run: runAction } = useAsyncAction();

  const [muteBusy, setMuteBusy] = useState(false);
  const [ptzBusy, setPtzBusy] = useState<PtzDirection | null>(null);
  const [changingVoice, setChangingVoice] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [lastAction, setLastAction] = useState<LastAction | null>(null);
  const [message, setMessage] = useState('');
  const [mutedOverride, setMutedOverride] = useState<boolean | null>(null);
  const [voiceRouteMissing, setVoiceRouteMissing] = useState(false);

  useEffect(() => {
    setVoiceRouteMissing(false);
  }, [baseUrl]);

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

  const voiceFetcher = useMemo(
    () => toPollFetcher((signal) => api.getVoice({ signal }), normalizeVoice),
    [api],
  );

  const {
    data: voiceData,
    error: voiceError,
    refresh: refreshVoice,
  } = usePoll<VoiceView>(voiceFetcher, {
    enabled: focused && !configLoading && !!baseUrl && !voiceRouteMissing,
  });

  useEffect(() => {
    if (voiceError?.status === 404) {
      setVoiceRouteMissing(true);
    }
  }, [voiceError]);

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

  const chooseVoice = useCallback(
    (voiceId: string): Promise<void> =>
      runAction(async ({ signal, isActive }) => {
        setChangingVoice(voiceId);
        setError(null);
        setLastAction({ kind: 'voice', voiceId });
        setMessage('');
        const result = await api.setVoice(voiceId, { signal });
        if (!isActive()) return;
        setChangingVoice(null);
        if (result.ok) {
          setLastAction(null);
          const view = normalizeVoice(result.data);
          setMessage(view.message || `Đã đổi sang ${view.currentLabel.toLowerCase()}.`);
          refreshVoice();
          return;
        }
        if (result.error.kind === 'cancelled') return;
        setError(result.error);
      }),
    [api, refreshVoice, runAction],
  );

  const retryAction = useCallback((): void => {
    if (!lastAction) return;
    if (lastAction.kind === 'mute') void toggleMute();
    else if (lastAction.kind === 'ptz') void movePtz(lastAction.direction);
    else void chooseVoice(lastAction.voiceId);
  }, [chooseVoice, lastAction, movePtz, toggleMute]);

  const retryPoll = useCallback((): void => {
    refresh();
  }, [refresh]);

  return (
    <Screen title="Điều khiển" subtitle="Âm thanh, giọng đọc cảnh báo và xoay camera">
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
          retrying={muteBusy || ptzBusy !== null || changingVoice !== null}
        />
      ) : null}

      {message ? <SuccessBanner message={message} /> : null}

      <Card>
        <Label>Tiếng cảnh báo</Label>
        <Text style={[typo.heading, { color: muted ? palette.warn : palette.good }]}>
          {muted ? 'Đang tắt tiếng' : 'Đang bật tiếng'}
        </Text>
        <Text style={[typo.caption, { color: palette.textMuted }]}>
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
        <Text style={[typo.caption, { color: palette.textMuted }]}>
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

        <Text style={[typo.caption, { color: palette.textFaint }]}>
          Camera không hỗ trợ PTZ sẽ báo bằng câu tiếng Việt của máy chủ, không phải lỗi
          chung.
        </Text>
      </Card>

      {voiceData && voiceData.available && voiceData.voices.length > 0 ? (
        <>
          <Divider />
          <Card>
            <View style={styles.voiceHeadRow}>
              <Label>Giọng đọc cảnh báo</Label>
              <Chip text={voiceData.currentLabel} tone="good" />
            </View>
            {voiceData.fallbackCount > 0 && voiceData.fallbackNote ? (
              <Notice
                title="Còn câu phải mượn giọng khác"
                body={voiceData.fallbackNote}
                tone="warn"
              />
            ) : null}
            {voiceData.voices.map((voice) => (
              <View key={voice.id} style={styles.voiceRow}>
                <View style={styles.voiceInfo}>
                  <View style={styles.voiceTitleRow}>
                    <Text style={typo.heading}>{voice.label}</Text>
                    {voice.hasMissingClips ? (
                      <Chip text="Thiếu bản thu" tone="warn" />
                    ) : null}
                  </View>
                  <Text style={[typo.caption, { color: palette.textFaint }]}>
                    {voice.id}
                  </Text>
                </View>
                <Button
                  label={voice.selected ? 'Đang dùng' : 'Chọn'}
                  accessibilityLabel={
                    voice.selected
                      ? `${voice.label} đang được dùng`
                      : `Chọn ${voice.label}`
                  }
                  onPress={() => void chooseVoice(voice.id)}
                  variant={voice.selected ? 'quiet' : 'secondary'}
                  disabled={
                    voice.selected ||
                    (changingVoice !== null && changingVoice !== voice.id)
                  }
                  busy={changingVoice === voice.id}
                />
              </View>
            ))}
          </Card>
        </>
      ) : null}
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
  voiceHeadRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  voiceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
    paddingVertical: spacing.xs,
  },
  voiceInfo: {
    flex: 1,
    gap: 2,
  },
  voiceTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    flexWrap: 'wrap',
  },
});
