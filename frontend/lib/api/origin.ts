// 브라우저가 직접 부르는 Route Handler 의 CSRF 검사(설계도 §6). Server Action 처럼 Origin 의 host 를 요청 host 와 견준다.
// Server Action 과 달리 Origin 이 없으면 거부한다(파일 업로드는 언제나 브라우저 fetch — 최신 브라우저는 Origin 을 싣는다).

export function sameOrigin(headers: Headers): boolean {
  const origin = headers.get("origin");
  if (!origin) return false;
  const site = headers.get("sec-fetch-site");
  if (site && site !== "same-origin") return false;
  const host = headers.get("x-forwarded-host") ?? headers.get("host");
  try {
    return host !== null && new URL(origin).host === host;
  } catch {
    return false;
  }
}

/**
 * 쿠키를 바꾸는 GET(예: /auth/expired)을 이 사이트가 시작했는지 — 다른 사이트의 링크·이미지로 불러 로그아웃을
 * 유도하지 못하게(검토 v3 R-5). 탐색 요청은 Origin 을 싣지 않으므로 Sec-Fetch-Site 로 본다:
 * same-origin(우리 화면의 redirect) 또는 none(주소창 직접 입력)만. 머리가 없는 옛 브라우저는 판정할 수 없어 허용한다
 * — 막으면 만료된 쿠키를 지울 길이 없어 같은 화면과 /auth/expired 를 오간다.
 */
export function selfInitiated(headers: Headers): boolean {
  const site = headers.get("sec-fetch-site");
  return site === null || site === "same-origin" || site === "none";
}
