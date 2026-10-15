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
