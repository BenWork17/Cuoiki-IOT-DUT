/**
 * Màn 4 — Tín hiệu.
 *
 * Dùng `GET /api/signals` (`app.py:897-909`), trả ba mục `presence`, `phone`,
 * `identity`, mỗi mục `{state, age_s, age_limit_s, fresh}`; `identity` thêm
 * `name`, `reason` (`people_service.py:1368-1397`).
 *
 * Quy tắc quan trọng nhất của màn này (`app.js:145-149`): `fresh === false`
 * nghĩa là **hết dữ liệu**, không phải "vẫn như cũ". Dòng đó phải nói
 * "Chưa có dữ liệu mới" và tuổi là "–"; lặp lại `state` cũ là làm người dùng
 * tin hệ thống vừa đo. Việc quyết định câu chữ nằm trong `normalizeSignal()`
 * (thuần, test được), màn hình chỉ vẽ.
 *
 * Ngưỡng tuổi (3,0 s cho presence/phone, 10,0 s cho identity) **không**
 * hardcode ở đây: app hiện `age_limit_s` server gửi, đúng như yêu cầu.
 */
import React, { useCallback } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { normalizeSignals, type SignalRow } from '../api/payload';
import { Button, Card, ErrorBanner, Label, Notice, Screen, toneColor, toneSurface } from '../components/ui';
import { useApp } from '../context/AppContext';
import { usePoll, type PollResult } from '../hooks/usePoll';
import { colors, radius, spacing, type as typo } from '../theme';

/** `focused` do thanh tab truyền vào: màn chỉ hỏi máy chủ khi đang được hiện. */
export function SignalsScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();

  const fetcher = useCallback(
    async (signal: AbortSignal): Promise<PollResult<SignalRow[]>> => {
      const result = await api.getSignals({ signal });
      if (result.ok) {
        return { ok: true, data: normalizeSignals(result.data), ignored: false };
      }
      if (result.error.kind === 'cancelled') {
        return { ok: false, error: result.error, ignored: true };
      }
      return { ok: false, error: result.error, ignored: false };
    },
    [api],
  );

  const { data, error, loading, refresh } = usePoll(fetcher, { enabled: focused && !configLoading && !!baseUrl });
  const peopleDisabled = error?.status === 503;

  return (
    <Screen title="Tín hiệu" subtitle="Dấu hiệu thô gần nhất mà Pi ghi nhận">
      {!baseUrl ? (
        <Notice
          title="Chưa cấu hình máy chủ"
          body="Mở tab Kết nối, nhập IP LAN của máy chạy dashboard rồi lưu lại."
          tone="warn"
        />
      ) : null}

      {peopleDisabled ? (
        <Notice
          title="Tính năng người học đang tắt"
          body={
            error?.message ??
            'Máy chủ chưa bật dịch vụ người học trong lần chạy này.'
          }
          tone="warn"
        />
      ) : null}

      {error && !peopleDisabled ? (
        <ErrorBanner message={error.message} onRetry={refresh} retrying={loading} />
      ) : null}

      {loading && !data ? (
        <Card style={styles.loadingCard}>
          <ActivityIndicator color={colors.accent} />
          <Text style={[typo.caption, styles.muted]}>Đang hỏi máy chủ…</Text>
        </Card>
      ) : null}

      {(data ?? []).map((row) => (
        <SignalCard key={row.kind} row={row} />
      ))}

      {data ? (
        <Button label="Làm mới ngay" onPress={refresh} variant="quiet" busy={loading} />
      ) : null}

      <Text style={[typo.caption, styles.footnote]}>
        Tín hiệu chỉ có hạn trong vài giây. Dòng ghi “Chưa có dữ liệu mới” nghĩa là lần đo
        gần nhất đã cũ — không phải kết luận hiện tại.
      </Text>
    </Screen>
  );
}

function SignalCard({ row }: { row: SignalRow }): React.ReactElement {
  return (
    <Card style={[styles.signalCard, { borderColor: row.fresh ? colors.border : colors.borderStrong }]}>
      <View style={styles.signalHead}>
        <View style={styles.signalTitleBlock}>
          <Label>{row.label}</Label>
          <View style={styles.signalValueRow}>
            <Text style={[styles.glyph, { color: toneColor(row.tone) }]}>{row.glyph}</Text>
            <Text
              style={[
                typo.heading,
                { color: row.fresh ? toneColor(row.tone) : colors.textMuted, flexShrink: 1 },
              ]}
            >
              {row.text}
            </Text>
          </View>
        </View>
        <View
          style={[
            styles.freshBadge,
            {
              backgroundColor: toneSurface(row.fresh ? 'good' : 'idle'),
              borderColor: row.fresh ? 'rgba(95,224,176,0.35)' : colors.border,
            },
          ]}
        >
          <Text
            style={[styles.freshText, { color: row.fresh ? colors.good : colors.textMuted }]}
          >
            {row.fresh ? 'Mới' : 'Cũ'}
          </Text>
        </View>
      </View>

      <Text style={[typo.caption, styles.muted]}>{row.ageText}</Text>
      {row.reason ? (
        <Text style={[typo.caption, styles.muted]}>Lý do: {row.reason}</Text>
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  signalCard: {
    gap: spacing.sm,
    borderRadius: radius.lg,
  },
  signalHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: spacing.md,
  },
  signalTitleBlock: {
    flex: 1,
    gap: 4,
  },
  signalValueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  glyph: {
    fontSize: 16,
    lineHeight: 22,
  },
  freshBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  freshText: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  loadingCard: {
    alignItems: 'center',
    gap: spacing.sm,
  },
  muted: {
    color: colors.textMuted,
  },
  footnote: {
    color: colors.textFaint,
  },
});


