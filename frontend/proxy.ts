import { NextResponse, type NextRequest } from "next/server";

// 지금 경로를 요청 머리에 싣는다 — 만료된 세션 쿠키를 지운 뒤 돌아올 곳(인증 설계도 §4.4.1 '/auth/expired?next=')을
// 서버 컴포넌트가 알도록. 인증 판정·DB 확인은 하지 않는다(Next 인증 가이드 'Optimistic checks with Proxy').
// 바깥에서 같은 이름의 머리를 보내도 여기서 덮어쓴다. 값은 쓰는 쪽이 safeNextPath 로 다시 검사한다.
export const PATH_HEADER = "x-mypage-path";

export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.set(PATH_HEADER, request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/me/:path*", "/admin/:path*", "/boards/:path*"],
};
