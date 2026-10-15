import "server-only";
import { ApiError, type ProblemBody } from "@/lib/api/problem";
import { personalGet } from "@/lib/server/backend";

// 관리 화면 읽기 — 개인 데이터(요청 시점). 401·403 은 화면이 안내 문구로 바꾸도록 문제 본문을 돌려준다
export async function adminGet<T>(path: string): Promise<{ data: T; problem?: undefined } | { data?: undefined; problem: ProblemBody }> {
  try {
    return { data: await personalGet<T>(path) };
  } catch (e) {
    if (e instanceof ApiError) return { problem: e.problem };
    throw e;
  }
}

/** URLSearchParams — 빈 값은 뺀다 */
export function query(params: Record<string, string | number | null | undefined | string[]>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    const value = Array.isArray(v) ? v[0] : v;
    if (value !== undefined && value !== null && value !== "") q.set(k, String(value));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
