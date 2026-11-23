/**
 * Cụm "Tín hiệu người học trực tiếp" (3 thông số: Có mặt trong khung hình,
 * Sử dụng điện thoại, Người đang học là ai) theo thiết kế Nocturne Telemetry
 * của Google Stitch.
 *
 * Đặt ngay bên dưới khung hình Camera trong `CameraScreen` (bố cục Bento 2+1)
 * để người dùng vừa xem trực tiếp luồng hình vừa theo dõi tức thì cả 3 thông số
 * mà không cần cuộn trang hay chuyển tab.
 *
 * Bảo toàn tuyệt đối quy tắc của `normalizeSignals`: khi `fresh === false`,
 * `row.text` là `"Chưa có dữ liệu mới"` và `row.ageText` là `"–"` — không bao
 * giờ lặp lại kết luận cũ như thể vừa đo.
 */
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { SignalRow } from '../api/payload';
import { colors, monoFamily, radius, spacing, type as typo } from '../theme';
import { Label, toneBorder, toneColor, toneSurface } from './ui';

function initialOfName(name?: string): string | null {
  if (!name) return null;
  const trimmed = name.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(/\s+/);
  const lastWord = parts[parts.length - 1] ?? trimmed;
  return lastWord.charAt(0).toUpperCase();
}

export function LearnerSignalsSection({
  rows,
  peopleDisabledMessage,
}: {
  rows: SignalRow[] | null;
  /** Thông điệp từ máy chủ khi dịch vụ nhận diện người học tắt (HTTP 503). */
  peopleDisabledMessage?: string | null;
}): React.ReactElement {
  if (peopleDisabledMessage) {
    return (
      <View style={[styles.container, styles.disabledContainer]}>
        <View style={styles.headerRow}>
          <View style={styles.headerLeft}>
            <View style={[styles.headerDot, { backgroundColor: colors.warn }]} />
            <Label>Tín hiệu người học</Label>
          </View>
          <Text style={[styles.headerMeta, { color: colors.warn }]}>Đang tắt</Text>
        </View>
        <Text style={[typo.caption, styles.disabledBody]}>{peopleDisabledMessage}</Text>
      </View>
    );
  }

  const presence = rows?.find((r) => r.kind === 'presence') ?? null;
  const phone = rows?.find((r) => r.kind === 'phone') ?? null;
  const identity = rows?.find((r) => r.kind === 'identity') ?? null;
  const anyFresh = Boolean(rows?.some((r) => r.fresh));
  const allFresh = Boolean(rows && rows.length === 3 && rows.every((r) => r.fresh));

  return (
    <View style={styles.container}>
      {/* Thanh tiêu đề nhỏ gọn */}
      <View style={styles.headerRow}>
        <View style={styles.headerLeft}>
          <View
            style={[
              styles.headerDot,
              {
                backgroundColor: allFresh
                  ? colors.good
                  : anyFresh
                    ? colors.warn
                    : colors.textFaint,
              },
            ]}
          />
          <Label>Tín hiệu người học</Label>
        </View>
        <Text style={styles.headerMeta}>
          {rows === null
            ? 'Đang đồng bộ…'
            : allFresh
              ? 'Trực tiếp · 3/3 mới'
              : anyFresh
                ? 'Một phần đã cũ'
                : 'Chờ nhịp đo mới'}
        </Text>
      </View>

      {/* Hàng 1: 2 ô song song — Có mặt trong khung hình & Sử dụng điện thoại */}
      <View style={styles.topRow}>
        <CompactSignalTile
          title="Có mặt"
          fallbackLabel="Trong khung hình"
          row={presence}
        />
        <CompactSignalTile
          title="Điện thoại"
          fallbackLabel="Sử dụng ĐT"
          row={phone}
        />
      </View>

      {/* Hàng 2: Ô rộng toàn chiều ngang — Người đang học là ai (Danh tính) */}
      <IdentitySignalTile row={identity} />
    </View>
  );
}

function CompactSignalTile({
  title,
  fallbackLabel,
  row,
}: {
  title: string;
  fallbackLabel: string;
  row: SignalRow | null;
}): React.ReactElement {
  const fresh = row?.fresh === true;
  const tone = fresh && row ? row.tone : 'idle';
  const accent = fresh && row ? toneColor(row.tone) : colors.textMuted;
  const borderHex =
    fresh && row && (row.tone === 'bad' || row.tone === 'warn')
      ? toneBorder(row.tone)
      : colors.border;

  return (
    <View style={[styles.compactTile, { borderColor: borderHex }]}>
      <View style={styles.tileHead}>
        <Label>{row?.label ?? title}</Label>
        <View
          style={[
            styles.freshPill,
            {
              backgroundColor: toneSurface(fresh ? 'good' : 'idle'),
              borderColor: fresh ? toneBorder('good') : colors.border,
            },
          ]}
        >
          <Text
            style={[
              styles.freshPillText,
              { color: fresh ? colors.good : colors.textFaint },
            ]}
          >
            {row === null ? '…' : fresh ? 'Mới' : 'Cũ'}
          </Text>
        </View>
      </View>

      <View style={styles.valueRow}>
        <View
          style={[
            styles.signalDot,
            { backgroundColor: fresh && tone !== 'idle' ? accent : colors.textFaint },
          ]}
        />
        <Text
          style={[styles.compactValue, { color: accent }]}
          numberOfLines={2}
        >
          {row ? row.text : `Đang đọc ${fallbackLabel.toLowerCase()}…`}
        </Text>
      </View>

      <Text style={styles.ageCaption} numberOfLines={1}>
        {row ? row.ageText : '–'}
      </Text>
    </View>
  );
}

function IdentitySignalTile({ row }: { row: SignalRow | null }): React.ReactElement {
  const fresh = row?.fresh === true;
  const tone = fresh && row ? row.tone : 'idle';
  const accent = fresh && row ? toneColor(row.tone) : colors.textMuted;
  const initial = fresh ? initialOfName(row?.personName) : null;
  const borderHex =
    fresh && row && (row.tone === 'bad' || row.tone === 'warn')
      ? toneBorder(row.tone)
      : colors.border;

  return (
    <View style={[styles.identityTile, { borderColor: borderHex }]}>
      <View style={[styles.avatarBadge, { backgroundColor: toneSurface(tone) }]}>
        <Text
          style={[
            styles.avatarGlyph,
            { color: fresh && tone !== 'idle' ? accent : colors.textMuted },
          ]}
        >
          {initial ?? row?.glyph ?? '•'}
        </Text>
      </View>

      <View style={styles.identityBody}>
        <View style={styles.identityHeadRow}>
          <Label>Người đang học · {row?.label ?? 'Danh tính'}</Label>
          <View style={styles.identityMetaRight}>
            <Text style={styles.ageCaption} numberOfLines={1}>
              {row ? row.ageText : '–'}
            </Text>
            <View
              style={[
                styles.freshPill,
                {
                  backgroundColor: toneSurface(fresh ? 'good' : 'idle'),
                  borderColor: fresh ? toneBorder('good') : colors.border,
                },
              ]}
            >
              <Text
                style={[
                  styles.freshPillText,
                  { color: fresh ? colors.good : colors.textFaint },
                ]}
              >
                {row === null ? '…' : fresh ? 'Mới' : 'Cũ'}
              </Text>
            </View>
          </View>
        </View>

        <Text style={[styles.identityValue, { color: accent }]} numberOfLines={2}>
          {row ? row.text : 'Đang xác thực người học…'}
        </Text>

        {row?.reason ? (
          <Text style={styles.reasonCaption} numberOfLines={2}>
            Lý do: {row.reason}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surfaceElevated,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: spacing.md,
    gap: spacing.sm,
  },
  disabledContainer: {
    borderColor: 'rgba(251,191,36,0.40)',
  },
  disabledBody: {
    color: colors.textMuted,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    paddingHorizontal: 2,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  headerDot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
  },
  headerMeta: {
    fontFamily: monoFamily,
    fontSize: 11,
    color: colors.textFaint,
    fontVariant: ['tabular-nums'],
  },
  topRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  compactTile: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: spacing.md,
    justifyContent: 'space-between',
    gap: 6,
  },
  tileHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 4,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  signalDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    flexShrink: 0,
  },
  compactValue: {
    fontSize: 14,
    lineHeight: 19,
    fontWeight: '700',
    flexShrink: 1,
  },
  identityTile: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: spacing.md,
  },
  avatarBadge: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  avatarGlyph: {
    fontSize: 16,
    fontWeight: '800',
  },
  identityBody: {
    flex: 1,
    gap: 3,
  },
  identityHeadRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.xs,
  },
  identityMetaRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexShrink: 0,
  },
  identityValue: {
    fontSize: 15,
    lineHeight: 20,
    fontWeight: '700',
  },
  reasonCaption: {
    ...typo.caption,
    color: colors.textMuted,
  },
  ageCaption: {
    fontFamily: monoFamily,
    fontSize: 11,
    lineHeight: 14,
    color: colors.textFaint,
    fontVariant: ['tabular-nums'],
  },
  freshPill: {
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
  },
  freshPillText: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
});
