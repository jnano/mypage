import { NextResponse, type NextRequest } from "next/server";
import { loginRedirect, publicOrigin } from "@/lib/auth/guard";

// 요청마다 두 가지만 한다 — 인증 판정·DB 확인은 하지 않는다(Next 인증 가이드 'Optimistic checks with Proxy').
// ① 관리 화면(/admin…)은 로그인 쿠키가 없으면 로그인 화면으로(lib/auth/guard.ts). 쿠키가 있으면 통과 — 만료·폐기된
//    쿠키나 운영자가 아닌 회원은 FastAPI 가 판정하고(401·403) 화면이 처리한다.
// ② 지금 경로를 요청 머리에 싣는다 — 만료된 세션 쿠키를 지운 뒤 돌아올 곳(인증 설계도 §4.4.1 '/auth/expired?next=')을
//    서버 컴포넌트가 알도록. 바깥에서 같은 이름의 머리를 보내도 덮어쓴다. 값은 쓰는 쪽이 safeNextPath 로 다시 검사한다.
export const PATH_HEADER = "x-mypage-path";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const login = loginRedirect(pathname, search, (name) => request.cookies.has(name));
  if (login) {
    // Proxy 의 넘김은 절대 주소여야 한다 — 브라우저가 보는 바깥 주소로(nginx 뒤에서 127.0.0.1 로 보내지 않게)
    return NextResponse.redirect(new URL(login, publicOrigin(request.headers, request.nextUrl)));
  }
  const headers = new Headers(request.headers);
  headers.set(PATH_HEADER, pathname + search);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/me/:path*", "/admin/:path*", "/boards/:path*"],
};
