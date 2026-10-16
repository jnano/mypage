import { type NextRequest, NextResponse } from "next/server";
import { cookieNames } from "@/lib/auth/cookies";
import { safeNextPath } from "@/lib/auth/next";
import { serverConfig } from "@/lib/server/config";

// 무효가 된 세션 쿠키 지우기 — 한 곳(인증 설계도 §4.4.1). 서버 컴포넌트는 쿠키를 바꿀 수 없어 여기로 보낸다.
// 기기 쿠키는 남긴다(잠금 면제 — '이 브라우저에서 로그인한 적이 있다').
export async function GET(request: NextRequest) {
  const config = serverConfig();
  const next = safeNextPath(request.nextUrl.searchParams.get("next"));
  // 상대 경로 Location — 앞단(nginx)의 호스트·스킴을 다시 계산하지 않는다
  const response = new NextResponse(null, { status: 303, headers: { Location: next } });
  response.cookies.delete({ name: cookieNames(config.appEnv).session, path: "/", secure: config.appEnv === "prod" });
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}
