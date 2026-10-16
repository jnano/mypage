import "server-only";
import { ApiError, type ProblemBody } from "@/lib/api/problem";
import { personalGet } from "@/lib/server/backend";
import { redirectIfExpired } from "@/lib/server/session";

// 관리 화면 읽기 — 개인 데이터(요청 시점). 401·403 은 화면이 안내 문구로 바꾸도록 문제 본문을 돌려준다
// (401 인데 세션 쿠키가 있으면 만료·폐기된 쿠키를 지우러 /auth/expired 로 — 인증 설계도 §4.4.1)
export async function adminGet<T>(path: string): Promise<{ data: T; problem?: undefined } | { data?: undefined; problem: ProblemBody }> {
  try {
    return { data: await personalGet<T>(path) };
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.problem.status === 401) await redirectIfExpired("personal"); // 쿠키는 있는데 비회원 — 지우고 로그인으로
      return { problem: e.problem };
    }
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
