/**
 * Cụm "Tín hiệu người học trực tiếp" (3 thông số: Có mặt trong khung hình,
 * Sử dụng điện thoại, Người đang học là ai), hỗ trợ cả hai chế độ Sáng & Tối.
 */
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { SignalRow } from '../api/payload';
import { useTheme } from '../context/AppContext';
import { monoFamily, radius, spacing, type ThemePalette } from '../theme';
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
  onOpenPeople,
}: {
  rows: SignalRow[] | null;
  /** Thông điệp từ máy chủ khi dịch vụ nhận diện người học tắt (HTTP 503). */
  peopleDisabledMessage?: string | null;
  /** Mở nhanh màn Người học (chọn người học / thêm người mới). */
  onOpenPeople?: () => void;
}): React.ReactElement {
  const { palette, typo } = useTheme();

  if (peopleDisabledMessage) {
    return (
      <View
        style={[
          styles.container,
          { backgroundColor: palette.surfaceElevated, borderColor: palette.warnBorder },
        ]}
      >
        <View style={styles.headerRow}>
          <View style={styles.headerLeft}>
            <View style={[styles.headerDot, { backgroundColor: palette.warn }]} />
            <Label>Tín hiệu người học</Label>
          </View>
          <Text style={[styles.headerMeta, { color: palette.warn }]}>Đang tắt</Text>
        </View>
        <Text style={[typo.caption, { color: palette.textMuted }]}>
          {peopleDisabledMessage}
        </Text>
      </View>
    );
  }

  const presence = rows?.find((r) => r.kind === 'presence') ?? null;
  const phone = rows?.find((r) => r.kind === 'phone') ?? null;
  const identity = rows?.find((r) => r.kind === 'identity') ?? null;
  const anyFresh = Boolean(rows?.some((r) => r.fresh));
  const allFresh = Boolean(rows && rows.length === 3 && rows.every((r) => r.fresh));

  return (
    <View
      style={[
        styles.container,
        { backgroundColor: palette.surfaceElevated, borderColor: palette.border },
      ]}
    >
      <View style={styles.headerRow}>
        <View style={styles.headerLeft}>
          <View
            style={[
              styles.headerDot,
              {
                backgroundColor: allFresh
                  ? palette.good
                  : anyFresh
                    ? palette.warn
                    : palette.textFaint,
              },
            ]}
          />
          <Label>Tín hiệu người học</Label>
        </View>
        <Text style={[styles.headerMeta, { color: palette.textFaint }]}>
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
          palette={palette}
        />
        <CompactSignalTile
          title="Điện thoại"
          fallbackLabel="Sử dụng ĐT"
          row={phone}
          palette={palette}
        />
      </View>

      {/* Hàng 2: Ô rộng toàn chiều ngang — Người đang học là ai (Danh tính) */}
      <IdentitySignalTile
        row={identity}
        palette={palette}
        onOpenPeople={onOpenPeople}
      />
    </View>
  );
}

function CompactSignalTile({
  title,
  fallbackLabel,
  row,
  palette,
}: {
  title: string;
  fallbackLabel: string;
  row: SignalRow | null;
  palette: ThemePalette;
}): React.ReactElement {
  const fresh = row?.fresh === true;
  const tone = fresh && row ? row.tone : 'idle';
  const accent = fresh && row ? toneColor(row.tone, palette) : palette.textMuted;
  const borderHex =
    fresh && row && (row.tone === 'bad' || row.tone === 'warn')
      ? toneBorder(row.tone, palette)
      : palette.border;

  return (
    <View
      style={[
        styles.compactTile,
        { backgroundColor: palette.surface, borderColor: borderHex },
      ]}
    >
      <View style={styles.tileHead}>
        <Label>{row?.label ?? title}</Label>
        <View
          style={[
            styles.freshPill,
            {
              backgroundColor: toneSurface(fresh ? 'good' : 'idle', palette),
              borderColor: fresh ? toneBorder('good', palette) : palette.border,
            },
          ]}
        >
          <Text
            style={[
              styles.freshPillText,
              { color: fresh ? palette.good : palette.textFaint },
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
            { backgroundColor: fresh && tone !== 'idle' ? accent : palette.textFaint },
          ]}
        />
        <Text style={[styles.compactValue, { color: accent }]} numberOfLines={2}>
          {row ? row.text : `Đang đọc ${fallbackLabel.toLowerCase()}…`}
        </Text>
      </View>

      <Text style={[styles.ageCaption, { color: palette.textFaint }]} numberOfLines={1}>
        {row ? row.ageText : '–'}
      </Text>
    </View>
  );
}

function IdentitySignalTile({
  row,
  palette,
  onOpenPeople,
}: {
  row: SignalRow | null;
  palette: ThemePalette;
  onOpenPeople?: () => void;
}): React.ReactElement {
  const { typo } = useTheme();
  const fresh = row?.fresh === true;
  const tone = fresh && row ? row.tone : 'idle';
  const accent = fresh && row ? toneColor(row.tone, palette) : palette.textMuted;
  const initial = fresh ? initialOfName(row?.personName) : null;
  const borderHex =
    fresh && row && (row.tone === 'bad' || row.tone === 'warn')
      ? toneBorder(row.tone, palette)
      : palette.border;

  return (
    <View
      style={[
        styles.identityTile,
        { backgroundColor: palette.surface, borderColor: borderHex },
      ]}
    >
      <View style={[styles.avatarBadge, { backgroundColor: toneSurface(tone, palette) }]}>
        <Text
          style={[
            styles.avatarGlyph,
            { color: fresh && tone !== 'idle' ? accent : palette.textMuted },
          ]}
        >
          {initial ?? row?.glyph ?? '•'}
        </Text>
      </View>

      <View style={styles.identityBody}>
        <View style={styles.identityHeadRow}>
          <Label>Người đang học · {row?.label ?? 'Danh tính'}</Label>
          <View style={styles.identityMetaRight}>
            <Text style={[styles.ageCaption, { color: palette.textFaint }]} numberOfLines={1}>
              {row ? row.ageText : '–'}
            </Text>
            <View
              style={[
                styles.freshPill,
                {
                  backgroundColor: toneSurface(fresh ? 'good' : 'idle', palette),
                  borderColor: fresh ? toneBorder('good', palette) : palette.border,
                },
              ]}
            >
              <Text
                style={[
                  styles.freshPillText,
                  { color: fresh ? palette.good : palette.textFaint },
                ]}
              >
                {row === null ? '…' : fresh ? 'Mới' : 'Cũ'}
              </Text>
            </View>
          </View>
        </View>

        <View style={styles.identityValueRow}>
          <Text style={[styles.identityValue, { color: accent }]} numberOfLines={2}>
            {row ? row.text : 'Đang xác thực người học…'}
          </Text>
          {onOpenPeople ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Mở quản lý người học"
              onPress={onOpenPeople}
              style={({ pressed }) => [
                styles.managePill,
                {
                  backgroundColor: palette.accentWash,
                  borderColor: palette.accentBorder,
                },
                pressed ? { opacity: 0.75 } : null,
              ]}
            >
              <Text style={[styles.managePillText, { color: palette.accent }]}>
                Đổi / Thêm ›
              </Text>
            </Pressable>
          ) : null}
        </View>

        {row?.reason ? (
          <Text style={[typo.caption, { color: palette.textMuted }]} numberOfLines={2}>
            Lý do: {row.reason}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.md,
    gap: spacing.sm,
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
    fontVariant: ['tabular-nums'],
  },
  topRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  compactTile: {
    flex: 1,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
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
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
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
  identityValueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  identityValue: {
    fontSize: 15,
    lineHeight: 20,
    fontWeight: '700',
    flex: 1,
  },
  managePill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    flexShrink: 0,
  },
  managePillText: {
    fontSize: 11,
    fontWeight: '700',
  },
  ageCaption: {
    fontFamily: monoFamily,
    fontSize: 11,
    lineHeight: 14,
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
