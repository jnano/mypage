// 작업자 → Next 캐시 무효화 요청 검증(설계도 §3.4 '작업자 변경'). 순수 함수 — Route Handler 가 쓴다.
import { timingSafeEqual } from "node:crypto";

export const MAX_TAGS = 500;
const TAG_MAX_LEN = 256; // Next revalidateTag 의 태그 길이 상한
const TAG_PATTERN = /^[a-z][a-z0-9_-]*(?::[A-Za-z0-9_.-]+)?$/; // 무효화 표의 태그 모양(board:free, post:12, recent:posts)

export interface RevalidateBody {
  now: string[];
  max: string[];
}

/** 비밀이 비어 있으면 언제나 거부(fail closed) */
export function secretMatches(given: string | null, expected: string): boolean {
  if (!expected || given === null) return false;
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

function tags(value: unknown, field: string): string[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error(`${field} 는 배열이어야 합니다`);
  for (const t of value) {
    if (typeof t !== "string" || t.length > TAG_MAX_LEN || !TAG_PATTERN.test(t)) {
      throw new Error(`${field} 에 올바르지 않은 태그가 있습니다`);
    }
  }
  return [...new Set(value as string[])];
}

export function parseRevalidateBody(raw: unknown): RevalidateBody {
  if (typeof raw !== "object" || raw === null) throw new Error("본문은 객체여야 합니다");
  const body = raw as Record<string, unknown>;
  const result = { now: tags(body.now, "now"), max: tags(body.max, "max") };
  if (result.now.length + result.max.length > MAX_TAGS) throw new Error(`태그는 ${MAX_TAGS}개까지입니다`);
  return result;
}
