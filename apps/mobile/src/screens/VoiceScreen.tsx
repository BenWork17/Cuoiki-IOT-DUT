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
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { normalizeVoice, type VoiceView } from '../api/payload';
import type { ApiError } from '../api/errors';
import { Button, Card, Chip, Divider, ErrorBanner, Label, Notice, Screen } from '../components/ui';
import { useApp } from '../context/AppContext';
import { usePoll, type PollResult } from '../hooks/usePoll';
import { colors, radius, spacing, type as typo } from '../theme';

export function VoiceScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();

  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [actionMessage, setActionMessage] = useState('');
  const [changingTo, setChangingTo] = useState<string | null>(null);
  /**
   * Giọng vừa định đổi mà lệnh hỏng — để nút "Gửi lại" gửi lại **đúng** giọng đó.
   *
   * Vì sao không dùng `changingTo`: nhánh lỗi đặt `setChangingTo(null)` để mở
   * khoá các nút, nên tới lúc banner lỗi hiện ra thì `changingTo` đã là `null`
   * và `onRetry` rơi về `refresh()` — tức chỉ tải lại danh sách, **không** gửi
   * lại lệnh. Người dùng bấm "Thử lại", thấy banner biến mất và tin rằng giọng
   * đã đổi, trong khi thực ra chẳng có lệnh nào được gửi lại. Đây đúng là lỗi
   * mà ControlScreen đã sửa bằng `LastAction`; đây là bản tương ứng.
   */
  const [lastVoice, setLastVoice] = useState<string | null>(null);

  /** Đã unmount chưa — mọi setState sau `await` phải kiểm cờ này. */
  const mounted = useRef(true);
  /** Request đổi giọng đang chạy, để huỷ khi rời màn. */
  const actionController = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      actionController.current?.abort();
      actionController.current = null;
    };
  }, []);

  const fetcher = useCallback(
    async (signal: AbortSignal): Promise<PollResult<VoiceView>> => {
      const result = await api.getVoice({ signal });
      if (result.ok) {
        return { ok: true, data: normalizeVoice(result.data), ignored: false };
      }
      if (result.error.kind === 'cancelled') {
        return { ok: false, error: result.error, ignored: true };
      }
      return { ok: false, error: result.error, ignored: false };
    },
    [api],
  );

  const { data, error, loading, refresh } = usePoll(fetcher, {
    enabled: focused && !configLoading && !!baseUrl,
  });

  const chooseVoice = useCallback(
    async (voiceId: string): Promise<void> => {
      actionController.current?.abort();
      const controller = new AbortController();
      actionController.current = controller;
      setChangingTo(voiceId);
      // Nhớ giọng đang thử NGAY từ đầu, và **giữ** nó nếu lệnh hỏng: nút "Gửi
      // lại" phải gửi lại đúng giọng này, không phải tải lại danh sách. Chỉ
      // xoá khi thành công (không còn gì để gửi lại) hoặc khi người dùng chọn
      // giọng khác (lúc đó `setLastVoice` đã ghi đè).
      setLastVoice(voiceId);
      setActionError(null);
      setActionMessage('');
      const result = await api.setVoice(voiceId, { signal: controller.signal });
      if (!mounted.current || controller.signal.aborted) return;
      setChangingTo(null);
      if (result.ok) {
        setLastVoice(null);
        // Hiện câu server gửi, rồi đọc lại để màn hình khớp máy chủ.
        const view = normalizeVoice(result.data);
        setActionMessage(
          view.message || `Đã đổi sang ${view.currentLabel.toLowerCase()}.`,
        );
        refresh();
        return;
      }
      if (result.error.kind === 'cancelled') return;
      setActionError(result.error);
    },
    [api, refresh],
  );

  const unavailable = data ? !data.available : error?.status === 503;

  return (
    <Screen title="Giọng đọc" subtitle="Giọng phát cảnh báo ra loa camera">
      {!baseUrl ? (
        <Notice
          title="Chưa cấu hình máy chủ"
          body="Mở tab Kết nối, nhập IP LAN của máy chạy dashboard rồi lưu lại."
          tone="warn"
        />
      ) : null}

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

      {actionMessage ? (
        <View style={styles.success}>
          <Text style={[typo.body, { color: colors.good }]}>{actionMessage}</Text>
        </View>
      ) : null}

      {loading && !data ? (
        <Card style={styles.loadingCard}>
          <ActivityIndicator color={colors.accent} />
          <Text style={[typo.caption, styles.muted]}>Đang hỏi máy chủ…</Text>
        </Card>
      ) : null}

      {data ? (
        <Card>
          <Label>Đang dùng</Label>
          <Text style={[typo.heading, { color: colors.good }]}>{data.currentLabel}</Text>
          {data.currentVoice ? (
            <Text style={[typo.caption, styles.muted]}>Mã giọng: {data.currentVoice}</Text>
          ) : null}
        </Card>
      ) : null}

      {/* Câu giải thích lấy NGUYÊN VĂN từ `fallbacks` của server
          (`speaker_alert._fallback_notes` đã là câu tiếng Việt hoàn chỉnh).
          App không tự ghép câu: ghép là nguồn sự thật thứ hai, và bản trước
          ghép sai hẳn — nó đọc value của `fallbacks` như thể đó là mã giọng,
          nên in ra tên mã giọng thay vì câu server gửi.

          Nhánh dự phòng chỉ chạy khi server có `fallbacks` nhưng value rỗng
          (payload hỏng). Nó cố ý KHÔNG nhắc tới giọng nào: app không biết
          giọng nào đang được mượn nếu server không nói. */}
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
                    {/* Lý do thiếu bản thu nằm ngay dưới **đúng giọng đó**,
                        đọc từ `voices[ma].missing` của server. Đây là chỗ hợp
                        lý để nói lý do — tuyệt đối không nhét câu giải thích
                        vào danh sách tên giọng. */}
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
                    // Ba nút cùng chữ "Chọn" thì trình đọc màn hình đọc ba
                    // lần giống nhau — phải nói rõ chọn giọng **nào**.
                    accessibilityLabel={
                      voice.selected ? `${voice.label} đang được dùng` : `Chọn ${voice.label}`
                    }
                    onPress={() => void chooseVoice(voice.id)}
                    variant={voice.selected ? 'quiet' : 'secondary'}
                    // Giọng đang dùng thì không có gì để đổi; đang đổi giọng
                    // khác thì khoá hết để không tạo hai lệnh chồng nhau.
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
  loadingCard: {
    alignItems: 'center',
    gap: spacing.sm,
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
  warnText: {
    color: colors.warn,
  },
  footnote: {
    color: colors.textFaint,
  },
});
