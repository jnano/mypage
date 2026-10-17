import "server-only";
import { ApiError, type ProblemBody } from "@/lib/api/problem";
import { cursorQuery, type Page } from "@/lib/me/lists";
import { hasViewer, personalGet } from "@/lib/server/backend";
import { redirectIfExpired } from "@/lib/server/session";

// 내 목록 읽기(설계도 §6.2) — 개인 데이터라 요청 시점·캐시 안 함. 세 화면이 같은 꼴을 쓴다
export type Loaded<T> = { kind: "page"; page: Page<T> } | { kind: "login" } | { kind: "problem"; problem: ProblemBody };

export async function loadMine<T>(api: string, cursor: string | string[] | undefined): Promise<Loaded<T>> {
  if (!(await hasViewer())) return { kind: "login" };
  try {
    return { kind: "page", page: await personalGet<Page<T>>(`${api}${cursorQuery(cursor)}`) };
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401) await redirectIfExpired("personal");
      return { kind: "problem", problem: e.problem };
    }
    throw e;
  }
}
