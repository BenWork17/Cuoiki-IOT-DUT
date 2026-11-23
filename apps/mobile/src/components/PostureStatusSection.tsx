/**
 * Cụm "Integrated Posture Status Banner + 2×2 Bento Telemetry Grid" theo thiết kế
 * Nocturne Telemetry của Google Stitch.
 *
 * Dùng chung cho màn hình chính `CameraScreen` (hiển thị ngay dưới khung camera)
 * và `StatusScreen` để không lặp JSX hay quy tắc hiển thị `stale` / `PAUSED`.
 */
import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { formatClock } from '../api/format';
import type { StatusView, Tone } from '../api/payload';
import { colors, radius, spacing, type as typo } from '../theme';
import { Chip, Label, toneColor, toneSurface } from './ui';

const REFERENCE_LABELS = ['Cúi đầu', 'Ngồi quá gần', 'Nghiêng vai'] as const;

function statusGlyph(view: StatusView): string {
  if (view.stale) return '!';
  if (view.state === 'PAUSED') return '⏸';
  switch (view.tone) {
    case 'good':
      return '✓';
    case 'warn':
      return '!';
    case 'bad':
      return '!';
    default:
      return '•';
  }
}

function statusSubtitle(view: StatusView): string {
  if (view.alert) return `Cảnh báo: ${view.alert}`;
  if (view.message) return view.message;
  if (view.stale) return 'Chưa nhận được nhịp cập nhật mới từ Raspberry Pi.';
  if (view.state === 'GOOD') return 'Trục lưng & khoảng cách ngồi ổn định.';
  if (view.state === 'WARN') return 'Phát hiện dấu hiệu lệch tư thế nhẹ — cần điều chỉnh.';
  if (view.state === 'BAD') return 'Tư thế sai kéo dài — hãy ngồi thẳng lưng lại.';
  if (view.state === 'ABSENT') return 'Không thấy người học trong khung hình camera.';
  return 'Hệ thống đang sẵn sàng theo dõi từ Raspberry Pi.';
}

function parsePercent(scoreText: string): number {
  const num = Number(scoreText.replace(',', '.'));
  if (!Number.isFinite(num)) return 0;
  return Math.max(0, Math.min(100, num));
}

function barColor(tone: Tone): string {
  if (tone === 'good') return colors.good;
  if (tone === 'warn') return colors.warn;
  if (tone === 'bad') return colors.bad;
  return colors.accent;
}

export function PostureStatusSection({
  view,
  updatedAt,
  mutedOverride,
  muteBusy = false,
  onToggleMute,
}: {
  view: StatusView;
  updatedAt: number | null;
  mutedOverride?: boolean | null;
  muteBusy?: boolean;
  onToggleMute?: () => void;
}): React.ReactElement {
  const effectiveTone: Tone = view.stale ? 'warn' : view.tone;
  const accentHex = toneColor(effectiveTone);
  const haloBg = toneSurface(effectiveTone);
  const scorePct = parsePercent(view.scoreText);
  const effectiveMuted = mutedOverride ?? view.muted;

  return (
    <View style={styles.section}>
      {/* 1. Integrated Posture Status Hero Banner */}
      <View style={[styles.heroBanner, { borderColor: view.tone === 'bad' ? 'rgba(248,113,113,0.4)' : colors.border }]}>
        <View style={styles.heroRow}>
          <View style={[styles.nodeHalo, { backgroundColor: haloBg }]}>
            <View
              style={[
                styles.nodeCore,
                {
                  backgroundColor:
                    effectiveTone === 'idle' ? colors.surfaceRaised : accentHex,
                },
              ]}
            >
              <Text
                style={[
                  styles.nodeGlyph,
                  {
                    color:
                      effectiveTone === 'idle' ? colors.text : colors.onGood,
                  },
                ]}
              >
                {statusGlyph(view)}
              </Text>
            </View>
          </View>

          <View style={styles.heroTextCol}>
            <View style={styles.heroHeadlineRow}>
              <Text
                style={[typo.heading, { color: accentHex, flexShrink: 1 }]}
                numberOfLines={2}
              >
                {view.stateText}
              </Text>
              {view.stale ? (
                <Chip text="Dữ liệu cũ" tone="warn" />
              ) : (
                <Text style={[typo.caption, styles.ageMono]} numberOfLines={1}>
                  {view.ageText}
                </Text>
              )}
            </View>
            <Text style={[typo.caption, styles.heroSub]} numberOfLines={2}>
              {statusSubtitle(view)}
            </Text>
            {updatedAt ? (
              <Text style={[typo.caption, styles.faint]}>
                Lần tải này: {formatClock(updatedAt)}
              </Text>
            ) : null}
          </View>
        </View>

        {/* Dải chip phân loại tư thế */}
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipsRow}
        >
          {view.labels.length > 0 ? (
            view.labels.map((label) => (
              <Chip
                key={label}
                text={label}
                tone={view.tone === 'good' ? 'good' : view.tone === 'bad' ? 'bad' : 'warn'}
              />
            ))
          ) : view.state === 'PAUSED' ? (
            <Chip text="Ngoài phiên học · AI đang nghỉ" tone="idle" />
          ) : view.state === 'GOOD' && !view.stale ? (
            <>
              <Chip text="✓ Đúng tư thế" tone="good" />
              {REFERENCE_LABELS.map((refLabel) => (
                <View key={refLabel} style={styles.inactiveChip}>
                  <Text style={styles.inactiveChipText}>{refLabel}</Text>
                </View>
              ))}
            </>
          ) : (
            <Chip text={view.stateText} tone={effectiveTone} />
          )}
        </ScrollView>
      </View>

      {/* 2. Lưới Bento 2x2 đọc rõ từ khoảng cách bàn học */}
      <View style={styles.bentoGrid}>
        <View style={styles.bentoRow}>
          {/* Ô 1: Điểm tư thế */}
          <View style={styles.bentoTile}>
            <View style={styles.tileHead}>
              <Label>Điểm tư thế</Label>
              <Text style={[styles.tileIcon, { color: colors.good }]}>✦</Text>
            </View>
            <View style={styles.tileBody}>
              <Text
                style={[
                  typo.telemetry,
                  { color: view.state === 'PAUSED' ? colors.textMuted : barColor(view.tone) },
                ]}
                numberOfLines={1}
              >
                {view.scoreText}
              </Text>
              <Text style={styles.tileHint}>thang 100</Text>
            </View>
            <View style={styles.progressTrack}>
              <View
                style={[
                  styles.progressFill,
                  {
                    width: `${view.state === 'PAUSED' ? 0 : scorePct}%`,
                    backgroundColor: barColor(view.tone),
                  },
                ]}
              />
            </View>
          </View>

          {/* Ô 2: Đã ngồi */}
          <View style={styles.bentoTile}>
            <View style={styles.tileHead}>
              <Label>Đã ngồi</Label>
              <Text style={[styles.tileIcon, { color: colors.textMuted }]}>◷</Text>
            </View>
            <View style={styles.tileBody}>
              <Text style={typo.telemetry} numberOfLines={1} adjustsFontSizeToFit>
                {view.sittingText ?? '–'}
              </Text>
              <Text style={styles.tileHint}>phiên hiện tại</Text>
            </View>
            <View style={styles.progressTrack}>
              <View
                style={[
                  styles.progressFill,
                  {
                    width: view.sittingText && view.state !== 'PAUSED' ? '55%' : '0%',
                    backgroundColor: colors.accent,
                  },
                ]}
              />
            </View>
          </View>
        </View>

        <View style={styles.bentoRow}>
          {/* Ô 3: Khoảng cách */}
          <View style={styles.bentoTile}>
            <View style={styles.tileHead}>
              <Label>Khoảng cách</Label>
              <Text style={[styles.tileIcon, { color: colors.accent }]}>↔</Text>
            </View>
            <View style={styles.tileBody}>
              <Text
                style={[
                  typo.telemetry,
                  { color: view.distanceText ? colors.accent : colors.textMuted },
                ]}
                numberOfLines={1}
                adjustsFontSizeToFit
              >
                {view.distanceText ?? '–'}
              </Text>
              <Text style={styles.tileHint}>
                {view.distanceText ? 'tới cảm biến' : 'chưa đo được'}
              </Text>
            </View>
            <View style={styles.progressTrack}>
              <View
                style={[
                  styles.progressFill,
                  {
                    width: view.distanceText ? '75%' : '0%',
                    backgroundColor: colors.accent,
                  },
                ]}
              />
            </View>
          </View>

          {/* Ô 4: Tiếng cảnh báo */}
          <View style={styles.bentoTile}>
            <View style={styles.tileHead}>
              <Label>Tiếng cảnh báo</Label>
              <Text
                style={[
                  styles.tileIcon,
                  { color: effectiveMuted ? colors.warn : colors.good },
                ]}
              >
                {effectiveMuted ? '✕' : '♪'}
              </Text>
            </View>
            <View style={styles.tileBody}>
              {onToggleMute ? (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={
                    effectiveMuted ? 'Bật lại tiếng cảnh báo' : 'Tắt tiếng cảnh báo'
                  }
                  disabled={muteBusy}
                  onPress={onToggleMute}
                  style={({ pressed }) => [
                    styles.soundPill,
                    effectiveMuted ? styles.soundPillMuted : styles.soundPillActive,
                    pressed ? { opacity: 0.8 } : null,
                  ]}
                >
                  <Text
                    style={[
                      styles.soundPillText,
                      { color: effectiveMuted ? colors.warn : colors.onGood },
                    ]}
                  >
                    {effectiveMuted ? 'Đang tắt' : 'Đang bật'}
                  </Text>
                </Pressable>
              ) : (
                <View
                  style={[
                    styles.soundPill,
                    effectiveMuted ? styles.soundPillMuted : styles.soundPillActive,
                  ]}
                >
                  <Text
                    style={[
                      styles.soundPillText,
                      { color: effectiveMuted ? colors.warn : colors.onGood },
                    ]}
                  >
                    {effectiveMuted ? 'Đang tắt' : 'Đang bật'}
                  </Text>
                </View>
              )}
              <Text style={styles.tileHint}>
                {onToggleMute ? 'Chạm để bật/tắt loa' : 'Chuông tự động'}
              </Text>
            </View>
            <View style={styles.progressTrack}>
              <View
                style={[
                  styles.progressFill,
                  {
                    width: effectiveMuted ? '25%' : '100%',
                    backgroundColor: effectiveMuted ? colors.warn : colors.good,
                  },
                ]}
              />
            </View>
          </View>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: spacing.md,
  },
  heroBanner: {
    backgroundColor: colors.surfaceElevated,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.md,
  },
  heroRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  nodeHalo: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  nodeCore: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  nodeGlyph: {
    fontSize: 16,
    fontWeight: '800',
  },
  heroTextCol: {
    flex: 1,
    gap: 2,
  },
  heroHeadlineRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  ageMono: {
    fontVariant: ['tabular-nums'],
    color: colors.textMuted,
  },
  heroSub: {
    color: colors.textMuted,
  },
  faint: {
    color: colors.textFaint,
    marginTop: 2,
  },
  chipsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingTop: 2,
  },
  inactiveChip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceRaised,
    opacity: 0.72,
  },
  inactiveChipText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.textFaint,
  },
  bentoGrid: {
    gap: spacing.md,
  },
  bentoRow: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  bentoTile: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    padding: spacing.lg,
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  tileHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  tileIcon: {
    fontSize: 14,
    fontWeight: '700',
  },
  tileBody: {
    gap: 2,
  },
  tileHint: {
    fontSize: 11,
    lineHeight: 15,
    color: colors.textFaint,
  },
  progressTrack: {
    height: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceRaised,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    borderRadius: radius.pill,
  },
  soundPill: {
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: radius.pill,
    marginVertical: 2,
  },
  soundPillActive: {
    backgroundColor: colors.good,
  },
  soundPillMuted: {
    backgroundColor: 'rgba(251,191,36,0.16)',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(251,191,36,0.45)',
  },
  soundPillText: {
    fontSize: 12,
    fontWeight: '700',
  },
});
