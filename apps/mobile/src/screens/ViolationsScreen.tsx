/**
 * Màn 7 — Vi phạm.
 *
 * `GET /api/violations?limit=200` — **lịch sử vi phạm** (rời khỏi camera, dùng
 * điện thoại, sai người học), đọc từ bảng `events` trong SQLite. Đây không
 * phải log debug: người dùng mở tab để biết "hôm nay mình bị nhắc mấy lần, lúc
 * nào", không phải để đọc chẩn đoán của tiến trình.
 *
 * Bốn quyết định, và lý do:
 *
 * 1. **Không poll định kỳ.** Màn này chỉ tải khi được mở hoặc khi bấm "Làm
 *    mới". Lịch sử vi phạm không phải dữ liệu thời gian thực: một vi phạm mới
 *    không cần hiện trong 2 giây, còn hỏi máy chủ mỗi 2 giây thì làm nóng Pi
 *    (thứ đang phải chạy model pose) và tốn pin vô ích. Rời tab là dừng hẳn.
 *
 * 2. **`kindText` lấy từ server, dùng thẳng.** Nhãn tiếng Việt tồn tại ở
 *    `app.py` (`LABEL_TEXT`). Chép lại vào app là nguồn sự thật thứ hai: sửa
 *    một bên thì app và dashboard web nói hai câu khác nhau về cùng một việc.
 *    Khi server không gửi nhãn, màn hình hiện **mã thô** kèm dấu hiệu — không
 *    bịa câu.
 *
 * 3. **Một bản ghi hỏng không làm mất cả danh sách.** `normalizeViolations` bỏ
 *    dòng không đọc được; ở đây chỉ việc vẽ.
 *
 * 4. **`FlatList`** thay vì `ScrollView` + `.map()`: 200 dòng là đủ nhiều để
 *    cuộn giật trên máy yếu, và `keyExtractor` ổn định (ts + kind + chỉ số)
 *    giữ đúng dòng khi danh sách đổi.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, StyleSheet, Text, View } from 'react-native';

import type { ApiError } from '../api/errors';
import { formatClock, formatDecimal, formatDuration } from '../api/format';
import {
  VIOLATION_KIND_ORDER,
  normalizeViolations,
  type ViolationCount,
  type ViolationEntry,
  type ViolationsView,
} from '../api/payload';
import {
  Button,
  Card,
  Chip,
  ErrorBanner,
  Label,
  LoadingCard,
  Screen,
  UnconfiguredNotice,
  toneColor,
} from '../components/ui';
import { useApp } from '../context/AppContext';
import { colors, radius, spacing, type as typo } from '../theme';

/**
 * Nhãn dự phòng khi server không gửi `kind_text` cho một mã.
 *
 * **Chép đúng chuỗi của server** (`VIOLATION_KIND_TEXT` trong `web/app.py`),
 * không phải câu app tự nghĩ ra. Đây chỉ là lưới an toàn cho payload thiếu
 * trường; bình thường nhãn luôn đến từ server.
 */
const KIND_FALLBACK_LABEL: Record<string, string> = {
  ABSENT: 'Rời khỏi bàn học',
  PHONE_USE: 'Dùng điện thoại',
  IMPOSTOR: 'Không phải người đăng ký',
};

/** "kéo dài 8,2 giây" / "kéo dài 1 phút 35 giây" — chỉ khi vi phạm có thời lượng thật. */
function violationDurationText(seconds: number): string | null {
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  // Dưới 10 giây giữ một chữ số thập phân; từ 10 giây trở lên dùng formatDuration cho gọn.
  if (seconds < 10) return `kéo dài ${formatDecimal(seconds, 1)} giây`;
  return `kéo dài ${formatDuration(seconds)}`;
}

export function ViolationsScreen({ focused }: { focused: boolean }): React.ReactElement {
  const { api, baseUrl, loading: configLoading } = useApp();

  const [view, setView] = useState<ViolationsView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);

  /** Đã unmount chưa — mọi setState sau `await` phải kiểm cờ này. */
  const mounted = useRef(true);
  /** Request đang chạy, để huỷ khi rời tab. */
  const controllerRef = useRef<AbortController | null>(null);
  /** Chặn chồng request khi bấm "Làm mới" liên tục. */
  const busyRef = useRef(false);

  const load = useCallback(async (): Promise<void> => {
    if (busyRef.current) return;
    busyRef.current = true;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    try {
      const result = await api.getViolations(undefined, { signal: controller.signal });
      if (!mounted.current || controller.signal.aborted) return;
      if (result.ok) {
        setView(normalizeViolations(result.data));
        setError(null);
      } else if (result.error.kind !== 'cancelled') {
        // Giữ danh sách cũ khi lỗi: mất mạng một nhịp không được xoá lịch sử
        // người dùng đang đọc. Nhưng lỗi **phải** hiện, kèm nút thử lại.
        setError(result.error);
      }
    } finally {
      busyRef.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controllerRef.current?.abort();
      controllerRef.current = null;
      busyRef.current = false;
    };
  }, []);

  // Chỉ tải khi tab đang hiện. Không có `setInterval` ở đây là **có chủ ý**.
  useEffect(() => {
    if (!focused || !baseUrl || configLoading) return;
    void load();
  }, [focused, baseUrl, configLoading, load]);

  const rows = view?.violations ?? [];
  const showSpinner = loading && rows.length === 0;
  const showEmpty = !loading && !error && view !== null && rows.length === 0;

  return (
    <Screen
      title="Vi phạm"
      subtitle="Lịch sử rời bàn, dùng điện thoại và sai người học"
      scroll={false}
    >
      {!baseUrl ? <UnconfiguredNotice /> : null}

      {error ? (
        <ErrorBanner
          message={error.message}
          onRetry={() => void load()}
          retrying={loading}
        />
      ) : null}

      {view ? <Summary view={view} /> : null}

      {showSpinner ? <LoadingCard label="Đang tải lịch sử…" /> : null}

      {showEmpty ? (
        // Trạng thái rỗng là tin **tốt** — không dùng màu báo động (đỏ/vàng).
        <Card style={styles.emptyCard}>
          <Text style={[typo.heading, { color: colors.good }]}>Chưa có vi phạm nào</Text>
          <Text style={[typo.body, styles.muted]}>
            Chưa ghi nhận lần rời bàn, dùng điện thoại hay sai người học nào. Cứ học
            bình thường nhé.
          </Text>
        </Card>
      ) : null}

      {rows.length > 0 ? (
        <FlatList
          data={rows}
          keyExtractor={(item, index) => `${item.ts}-${item.kind}-${index}`}
          renderItem={({ item }) => <ViolationRow entry={item} />}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          style={styles.list}
          contentContainerStyle={styles.listContent}
          refreshing={loading}
          onRefresh={() => void load()}
        />
      ) : null}

      <View style={styles.footer}>
        <Button
          label="Làm mới"
          onPress={() => void load()}
          variant="quiet"
          busy={loading}
          disabled={!baseUrl}
        />
      </View>
    </Screen>
  );
}

/** Đầu màn: tổng số + phân loại theo `counts` server gửi. */
function Summary({ view }: { view: ViolationsView }): React.ReactElement {
  if (view.total === 0 && view.countsNonZero.length === 0) return <></>;
  return (
    <Card style={styles.summaryCard}>
      <View style={styles.summaryHead}>
        <Label>Tổng vi phạm</Label>
        <Text style={[typo.number, { color: colors.text }]}>{view.total}</Text>
      </View>
      {view.countsNonZero.length > 0 ? (
        <View style={styles.chips}>
          {view.countsNonZero.map((c) => (
            <Chip
              key={c.kind}
              text={`${countLabel(c)} · ${c.count}`}
              tone={toneForKind(c.kind)}
            />
          ))}
        </View>
      ) : null}
    </Card>
  );
}

/** Nhãn của một dòng phân loại: ưu tiên server, rồi bảng dự phòng, rồi mã thô. */
function countLabel(c: ViolationCount): string {
  if (c.kindText) return c.kindText;
  const fallback = KIND_FALLBACK_LABEL[c.kind];
  if (fallback) return fallback;
  return c.kind;
}

/** Tông màu theo mức nghiêm trọng. */
function toneForKind(kind: string): 'bad' | 'warn' | 'idle' {
  if (kind === 'IMPOSTOR') return 'bad';
  if (kind === 'PHONE_USE') return 'warn';
  if (kind === 'ABSENT') return 'warn';
  return 'idle';
}

/** Một dòng vi phạm: giờ · nhãn · (kéo dài N giây). */
function ViolationRow({ entry }: { entry: ViolationEntry }): React.ReactElement {
  const duration = violationDurationText(entry.durationS);
  const label = entry.kindText ?? KIND_FALLBACK_LABEL[entry.kind] ?? entry.kind;
  const isUnknownKind =
    !entry.kindText &&
    !Object.prototype.hasOwnProperty.call(KIND_FALLBACK_LABEL, entry.kind);
  return (
    <View style={styles.row}>
      <Text style={[typo.number, styles.clock]}>{formatClock(entry.ts)}</Text>
      <View style={styles.rowBody}>
        <Text style={[typo.body, { color: toneColor(toneForKind(entry.kind)) }]}>
          {label}
          {isUnknownKind ? ` (${entry.kind})` : ''}
        </Text>
        {duration ? <Text style={[typo.caption, styles.muted]}>{duration}</Text> : null}
      </View>
    </View>
  );
}

/** Đánh dấu các mã đã biết để `toneForKind` phản ánh đúng; xuất để test dùng. */
export const KNOWN_VIOLATION_KINDS = VIOLATION_KIND_ORDER;

const styles = StyleSheet.create({
  list: {
    flex: 1,
  },
  listContent: {
    paddingBottom: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
    paddingVertical: spacing.sm,
  },
  clock: {
    minWidth: 78,
  },
  rowBody: {
    flex: 1,
    gap: 2,
  },
  separator: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.border,
  },
  summaryCard: {
    gap: spacing.sm,
  },
  summaryHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  emptyCard: {
    gap: spacing.sm,
    borderColor: 'rgba(52,211,153,0.35)',
    borderRadius: radius.lg,
  },
  footer: {
    paddingTop: spacing.sm,
  },
  muted: {
    color: colors.textMuted,
  },
});
