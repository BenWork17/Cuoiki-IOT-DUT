/**
 * Màn 6 — Giọng đọc.
 *
 * `GET /api/voice` và `POST /api/voice` (`app.py:655-682`, `app.py:686-731`).
 *
 * Ba điểm bắt buộc, lấy từ yêu cầu §5.1 hàng 5:
 * 1. `available: false` ⇒ hiện `message` của server và **không** hiện nút bấm
 *    được. Server nói rõ "chưa nối dây loa"; mời người dùng bấm vào một việc
 *    chắc chắn hỏng là lỗi thiết kế.
 * 2. Đổi giọng thành công ⇒ hiện **phản hồi của server** làm nguồn sự thật,
 *    rồi đọc lại `GET /api/voice` để giá trị trên màn hình và giá trị trong
 *    máy chủ không bao giờ lệch nhau.
 * 3. Giọng lạ ⇒ server **400**, và câu lỗi của server **đã chứa danh sách
 *    giọng hợp lệ**. App hiện đúng câu đó, không tự viết lại danh sách —
 *    viết lại là nguồn sự thật thứ hai, sửa một bên là lệch.
 *
 * `fallbacks` khác rỗng nghĩa là người dùng đang nghe giọng khác giọng đã
 * chọn (vì thiếu bản thu) — phải nói ra, im lặng là để họ tưởng nhầm.
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
import { useApp } from '../context/AppContext';
import { useAsyncAction } from '../hooks/useAsyncAction';
import { toPollFetcher, usePoll } from '../hooks/usePoll';
import { colors, spacing, type as typo } from '../theme';

export function VoiceScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();
  const { run: runAction } = useAsyncAction();

  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [actionMessage, setActionMessage] = useState('');
  const [changingTo, setChangingTo] = useState<string | null>(null);
  /**
   * Giọng vừa định đổi mà lệnh hỏng — để nút "Gửi lại" gửi lại **đúng** giọng đó.
   */
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
        // Nhớ giọng đang thử NGAY từ đầu, và **giữ** nó nếu lệnh hỏng: nút "Gửi
        // lại" phải gửi lại đúng giọng này, không phải tải lại danh sách.
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
          <Text style={[typo.heading, { color: colors.good }]}>{data.currentLabel}</Text>
          {data.currentVoice ? (
            <Text style={[typo.caption, styles.muted]}>Mã giọng: {data.currentVoice}</Text>
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
              <Text style={[typo.caption, styles.muted]}>
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
                    <Text style={[typo.caption, styles.faint]}>{voice.id}</Text>
                    {voice.hasMissingClips ? (
                      <Text style={[typo.caption, styles.warnText]}>
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

      <Text style={[typo.caption, styles.footnote]}>
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
  muted: {
    color: colors.textMuted,
  },
  faint: {
    color: colors.textFaint,
  },
  warnText: {
    color: colors.warn,
  },
  footnote: {
    color: colors.textFaint,
  },
});
