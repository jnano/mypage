import { connection, type NextRequest, NextResponse } from "next/server";
import { selfInitiated } from "@/lib/api/origin";
import { cookieNames } from "@/lib/auth/cookies";
import { safeNextPath } from "@/lib/auth/next";
import { serverConfig } from "@/lib/server/config";

// 무효가 된 세션 쿠키 지우기 — 한 곳(인증 설계도 §4.4.1). 서버 컴포넌트는 쿠키를 바꿀 수 없어 여기로 보낸다.
// 기기 쿠키는 남긴다(잠금 면제 — '이 브라우저에서 로그인한 적이 있다').
export async function GET(request: NextRequest) {
  await connection(); // 요청 시점 — 미리 렌더하지 않는다(cacheComponents)
  const config = serverConfig();
  const next = safeNextPath(request.nextUrl.searchParams.get("next"));
  // 상대 경로 Location — 앞단(nginx)의 호스트·스킴을 다시 계산하지 않는다
  const response = new NextResponse(null, { status: 303, headers: { Location: next, "Cache-Control": "private, no-store" } });
  // 다른 사이트가 이 주소를 불렀으면 지우지 않고 보내기만 한다(로그아웃 유도 방지, 검토 v3 R-5).
  // 쿠키가 정말 무효면 돌아간 화면이 같은 출처로 다시 여기로 보내 그때 지워진다
  if (!selfInitiated(request.headers)) return response;
  const names = cookieNames(config.appEnv);
  for (const name of [names.session, names.role]) response.cookies.delete({ name, path: "/", secure: config.appEnv === "prod" });
  return response;
}
