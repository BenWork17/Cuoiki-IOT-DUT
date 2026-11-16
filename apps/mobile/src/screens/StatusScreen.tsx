/**
 * Màn 1 — Trạng thái.
 *
 * Dùng `GET /api/status` (`app.py:423-429`), tự làm mới 2 s khi đang hiện.
 *
 * Hai quyết định quan trọng, đều lấy từ tài liệu yêu cầu §5.1 hàng 1:
 * 1. `stale` (hoặc `data_age_s > 10`) ⇒ **không** hiện `state_text` như kết
 *    luận mới. Máy chủ có thể đã chết từ lâu mà trạng thái cuối cùng vẫn là
 *    "Tư thế tốt" — hiện nguyên câu đó là nói dối người dùng.
 * 2. `state === "PAUSED"` ⇒ "Chưa bắt đầu phiên học", **không** phải "Không
 *    thấy người". Ngồi trước camera ngoài phiên mà đọc "không thấy ai" là
 *    đúng hiện tượng người dùng phàn nàn.
 */
import React, { useCallback } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { normalizeStatus, type StatusView } from '../api/payload';
import { Button, Card, Chip, Divider, ErrorBanner, Label, Screen, Stat, toneColor, toneSurface } from '../components/ui';
import { useApp } from '../context/AppContext';
import { usePoll, type PollResult } from '../hooks/usePoll';
import { colors, radius, spacing, type as typo } from '../theme';

/** `focused` do thanh tab truyền vào: màn chỉ hỏi máy chủ khi đang được hiện. */
export function StatusScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();

  const fetcher = useCallback(
    async (signal: AbortSignal): Promise<PollResult<StatusView>> => {
      const result = await api.getStatus({ signal });
      if (result.ok) {
        return { ok: true, data: normalizeStatus(result.data), ignored: false };
      }
      return {
        ok: false,
        error: result.error,
        ignored: result.error.kind === 'cancelled',
      };
    },
    [api],
  );

  const { data, error, loading, updatedAt, refresh } = usePoll(fetcher, {
    enabled: focused && !configLoading && !!baseUrl,
  });

  return (
    <Screen title="Trạng thái" subtitle="Tư thế hiện tại do Pi đo và gửi lên">
      {!baseUrl ? (
        <NoServerYet />
      ) : (
        <>
          {error ? <ErrorBanner message={error.message} onRetry={refresh} retrying={loading} /> : null}
          {data ? <StatusBody view={data} updatedAt={updatedAt} /> : loading ? <LoadingCard /> : null}
          {!data && !loading && !error ? (
            <Card>
              <Text style={typo.body}>Chưa có dữ liệu. Bấm Thử lại để hỏi lại máy chủ.</Text>
              <Button label="Thử lại" onPress={refresh} variant="quiet" />
            </Card>
          ) : null}
          <Button label="Làm mới ngay" onPress={refresh} variant="quiet" busy={loading && !!data} />
        </>
      )}
    </Screen>
  );
}

/** Trạng thái chưa cấu hình địa chỉ: hướng dẫn thay vì màn hình trắng. */
function NoServerYet(): React.ReactElement {
  return (
    <Card>
      <Text style={typo.heading}>Chưa cấu hình máy chủ</Text>
      <Text style={[typo.body, styles.muted]}>
        Mở tab <Text style={styles.strong}>Kết nối</Text>, nhập địa chỉ IP LAN của máy chạy
        dashboard (ví dụ http://192.168.x.x:8000) rồi bấm Lưu và kiểm tra.
      </Text>
    </Card>
  );
}

function LoadingCard(): React.ReactElement {
  return (
    <Card style={styles.loadingCard}>
      <ActivityIndicator color={colors.accent} />
      <Text style={[typo.caption, styles.muted]}>Đang hỏi máy chủ…</Text>
    </Card>
  );
}

function StatusBody({
  view,
  updatedAt,
}: {
  view: StatusView;
  updatedAt: number | null;
}): React.ReactElement {
  return (
    <>
      <Card style={styles.heroCard}>
        <View style={styles.heroTop}>
          <Label>Tư thế</Label>
          {view.stale ? <Chip text="Dữ liệu cũ" tone="warn" /> : null}
        </View>
        <Text style={[typo.title, { color: toneColor(view.tone) }]}>{view.stateText}</Text>
        <Text style={[typo.caption, styles.muted]}>{view.ageText}</Text>
        {view.message ? (
          <View style={[styles.alert, { backgroundColor: toneSurface('bad') }]}>
            <Text style={[typo.body, { color: colors.text }]}>{view.message}</Text>
          </View>
        ) : null}
        {updatedAt ? (
          <Text style={[typo.caption, styles.faint]}>
            Lần tải này: {new Date(updatedAt).toLocaleTimeString('vi-VN')}
          </Text>
        ) : null}
      </Card>

      <Card>
        <View style={styles.statRow}>
          <Stat label="Điểm" value={view.scoreText} hint="thang 10" />
          <Stat
            label="Khoảng cách"
            value={view.distanceText ?? '–'}
            hint={view.distanceText ? 'tới camera' : 'chưa đo được'}
          />
        </View>
        <Divider />
        <View style={styles.statRow}>
          <Stat label="Đã ngồi" value={view.sittingText ?? '–'} />
          <Stat
            label="Tiếng cảnh báo"
            value={view.muted ? 'Đang tắt' : 'Đang bật'}
            tone={view.muted ? 'warn' : 'good'}
          />
        </View>
      </Card>

      <Card>
        <Label>Nhãn phân loại</Label>
        {view.labels.length ? (
          <View style={styles.chips}>
            {view.labels.map((label) => (
              <Chip key={label} text={label} tone={view.tone === 'good' ? 'good' : 'warn'} />
            ))}
          </View>
        ) : (
          <Text style={[typo.caption, styles.muted]}>
            Không có nhãn nào — tư thế không bị đánh dấu vấn đề.
          </Text>
        )}
      </Card>
    </>
  );
}

const styles = StyleSheet.create({
  heroCard: {
    gap: spacing.sm,
    borderRadius: radius.lg,
  },
  heroTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  statRow: {
    flexDirection: 'row',
    gap: spacing.lg,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  alert: {
    borderRadius: radius.md,
    padding: spacing.md,
  },
  muted: {
    color: colors.textMuted,
  },
  faint: {
    color: colors.textFaint,
  },
  strong: {
    color: colors.text,
    fontWeight: '700',
  },
  loadingCard: {
    alignItems: 'center',
    gap: spacing.sm,
  },
});


