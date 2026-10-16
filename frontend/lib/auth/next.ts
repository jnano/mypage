// 로그인 뒤 돌아갈 곳(인증 설계도 §7.4) — 같은 사이트의 경로만. 아니면 "/". 순수 함수.

export function safeNextPath(raw: string | null | undefined): string {
  if (typeof raw !== "string" || raw.length === 0 || raw.length > 2000) return "/";
  // "/" 로 시작하고, "//"·"/\"(브라우저가 다른 호스트로 읽는다)가 아니고, 제어 문자가 없어야 한다
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return "/";
  // 제어 문자(0x00~0x1F, 0x7F) — 머리 주입·경로 혼동 방지
  for (let i = 0; i < raw.length; i++) {
    const c = raw.charCodeAt(i);
    if (c < 0x20 || c === 0x7f) return "/";
  }
  return raw;
}
