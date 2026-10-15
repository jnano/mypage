// 날짜·시각 표시 — 사이트 시간대 기준. 서버가 주는 ISO(UTC)를 그대로 잘라 쓰면 UTC 로 보인다(9시간 차이).
// 시간대는 사이트 설정(관리 기능)으로 옮길 수 있게 한 곳에 둔다.
export const SITE_TIME_ZONE = "Asia/Seoul";

const parts = new Intl.DateTimeFormat("en-CA", {
  timeZone: SITE_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function pick(iso: string): Record<string, string> {
  return Object.fromEntries(parts.formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
}

/** 2026-10-15 22:53 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const p = pick(iso);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

/** 2026-10-15 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const p = pick(iso);
  return `${p.year}-${p.month}-${p.day}`;
}
