import "server-only";
import type { GuestFormTokens } from "@/app/boards/actions";
import { personalGet } from "@/lib/server/backend";

// 비회원 글쓰기 화면의 묶음 응답(설계도 §6.3) — 폼 토큰·보안 문자가 들어 있어 캐시하지 않는다(요청 시점)
export interface GuestForm extends GuestFormTokens {
  policy: { honeypot: boolean; min_elapsed_sec: number };
  board: { slug: string; name: string; editor: "rich" | "markdown"; allow_secret: boolean; categories: { id: number; name: string }[] };
}

export async function loadGuestForm(slug: string): Promise<GuestForm> {
  return personalGet<GuestForm>(`/api/boards/${encodeURIComponent(slug)}/guest-form`);
}
