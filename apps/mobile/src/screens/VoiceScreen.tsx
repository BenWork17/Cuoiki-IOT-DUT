/**
 * Màn Giọng đọc (`GET /api/voice` và `POST /api/voice`), thích ứng Sáng & Tối.
 */
import React, { useCallback, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { ApiError } from '../api/errors';
import { normalizeVoice, type VoiceView } from '../api/payload';
import {
  Button,
  Card,
  Chip,
  Divider,
  ErrorBanner,
  Label,
  LoadingCard,
  Notice,
  Screen,
  SuccessBanner,
  UnconfiguredNotice,
} from '../components/ui';
import { useApp, useTheme } from '../context/AppContext';
import { useAsyncAction } from '../hooks/useAsyncAction';
import { toPollFetcher, usePoll } from '../hooks/usePoll';
import { spacing } from '../theme';

export function VoiceScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();
  const { palette, typo } = useTheme();
  const { run: runAction } = useAsyncAction();

  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [actionMessage, setActionMessage] = useState('');
  const [changingTo, setChangingTo] = useState<string | null>(null);
  const [lastVoice, setLastVoice] = useState<string | null>(null);

  const fetcher = useMemo(
    () => toPollFetcher((signal) => api.getVoice({ signal }), normalizeVoice),
    [api],
  );

  const { data, error, loading, refresh } = usePoll<VoiceView>(fetcher, {
    enabled: focused && !configLoading && !!baseUrl,
  });

  const chooseVoice = useCallback(
    (voiceId: string): Promise<void> =>
      runAction(async ({ signal, isActive }) => {
        setChangingTo(voiceId);
        setLastVoice(voiceId);
        setActionError(null);
        setActionMessage('');
        const result = await api.setVoice(voiceId, { signal });
        if (!isActive()) return;
        setChangingTo(null);
        if (result.ok) {
          setLastVoice(null);
          const view = normalizeVoice(result.data);
          setActionMessage(
            view.message || `Đã đổi sang ${view.currentLabel.toLowerCase()}.`,
          );
          refresh();
          return;
        }
        if (result.error.kind === 'cancelled') return;
        setActionError(result.error);
      }),
    [api, refresh, runAction],
  );

  const unavailable = data ? !data.available : error?.status === 503;

  return (
    <Screen title="Giọng đọc" subtitle="Giọng phát cảnh báo ra loa camera">
      {!baseUrl ? <UnconfiguredNotice /> : null}

      {error && !unavailable ? (
        <ErrorBanner message={error.message} onRetry={refresh} retrying={loading} />
      ) : null}

      {unavailable ? (
        <Notice
          title="Loa cảnh báo chưa bật"
          body={
            data?.message ||
            error?.message ||
            'Máy chủ báo phiên chạy này chưa nối loa cảnh báo.'
          }
          tone="warn"
        />
      ) : null}

      {actionError ? (
        <ErrorBanner
          title="Không đổi được giọng"
          message={actionError.message}
          retryLabel="Gửi lại"
          onRetry={lastVoice ? () => void chooseVoice(lastVoice) : refresh}
          retrying={changingTo !== null}
        />
      ) : null}

      {actionMessage ? <SuccessBanner message={actionMessage} /> : null}

      {loading && !data ? <LoadingCard /> : null}

      {data ? (
        <Card>
          <Label>Đang dùng</Label>
          <Text style={[typo.heading, { color: palette.good }]}>{data.currentLabel}</Text>
          {data.currentVoice ? (
            <Text style={[typo.caption, { color: palette.textMuted }]}>
              Mã giọng: {data.currentVoice}
            </Text>
          ) : null}
        </Card>
      ) : null}

      {data && data.fallbackCount > 0 ? (
        <Notice
          title="Còn câu phải mượn giọng khác"
          body={
            data.fallbackNote ??
            `Máy chủ báo ${data.fallbackCount} câu cảnh báo đang phải mượn giọng khác.`
          }
          tone="warn"
        />
      ) : null}

      {data && data.available ? (
        <>
          <Divider />
          <Card>
            <Label>Chọn giọng</Label>
            {data.voices.length === 0 ? (
              <Text style={[typo.caption, { color: palette.textMuted }]}>
                Máy chủ không báo giọng nào khả dụng.
              </Text>
            ) : (
              data.voices.map((voice) => (
                <View key={voice.id} style={styles.voiceRow}>
                  <View style={styles.voiceInfo}>
                    <View style={styles.voiceTitleRow}>
                      <Text style={typo.heading}>{voice.label}</Text>
                      {voice.selected ? <Chip text="Đang dùng" tone="good" /> : null}
                      {voice.hasMissingClips ? <Chip text="Thiếu bản thu" tone="warn" /> : null}
                    </View>
                    <Text style={[typo.caption, { color: palette.textFaint }]}>{voice.id}</Text>
                    {voice.hasMissingClips ? (
                      <Text style={[typo.caption, { color: palette.warn }]}>
                        {voice.missingKinds.length > 0
                          ? `Thiếu bản thu cho: ${voice.missingKinds.join(', ')}`
                          : 'Thiếu bản thu cho một số câu cảnh báo'}
                      </Text>
                    ) : null}
                  </View>
                  <Button
                    label={voice.selected ? 'Đang dùng' : 'Chọn'}
                    accessibilityLabel={
                      voice.selected ? `${voice.label} đang được dùng` : `Chọn ${voice.label}`
                    }
                    onPress={() => void chooseVoice(voice.id)}
                    variant={voice.selected ? 'quiet' : 'secondary'}
                    disabled={voice.selected || (changingTo !== null && changingTo !== voice.id)}
                    busy={changingTo === voice.id}
                  />
                </View>
              ))
            )}
          </Card>
        </>
      ) : null}

      <Text style={[typo.caption, { color: palette.textFaint }]}>
        Đổi giọng có hiệu lực từ lần cảnh báo kế tiếp và được ghi lại để lần chạy sau vẫn
        nhớ.
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
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
