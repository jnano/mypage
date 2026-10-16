import Link from "next/link";
import { connection } from "next/server";
import { Suspense, type ReactNode } from "react";
import { AccountNav } from "@/components/auth/AccountNav";
import { getSite } from "@/lib/server/seo";

/** 화면 종류(홈블록 설계도 §3.3 — 원본은 백엔드 app/blocks/routes.py 가 생기면 그쪽). page = 사용자 페이지 */
export type RouteClass = "board" | "search" | "member" | "auth" | "default" | "page";

// 틀(홈블록 설계도 §3.1) — 영역은 각자 <Suspense> 안에서 요청 시점에 그린다(틀 데이터는 관리 화면에서 바뀌고,
// 빌드 때 FastAPI 를 부르지 않는다 — 본 설계도 §3.3). outlet(children)은 Suspense 밖이라 화면의 정적 셸은 그대로
// 미리 만들어진다. 본문 <main> 하나·처리방침 링크는 틀 밖 고정 줄(§3.2). 걸음 1: 대체 틀만(§3.6)
export function Frame({ routeClass, children }: { routeClass: RouteClass; children: ReactNode }) {
  return (
    <div data-slot="frame" data-route-class={routeClass}>
      <header data-slot="site-header" data-region="header">
        <Suspense fallback={null}>
          <FallbackHeader />
        </Suspense>
        <Suspense fallback={null}>
          <AccountNav />
        </Suspense>
      </header>
      <main id="main" data-slot="site-main">
        {children}
      </main>
      <footer data-slot="site-footer" data-region="footer">
        <p data-slot="policy-links">
          <Link href="/privacy">개인정보 처리 고지</Link>
        </p>
      </footer>
    </div>
  );
}

// 대체 틀의 머리(§3.6) — 사이트 이름 + 메뉴(처음 · 메뉴 노출 게시판 · 검색 · 알림). 데이터는 캐시된 /api/site 하나
async function FallbackHeader() {
  await connection();
  const site = await getSite();
  return (
    <>
      <Link href="/" data-slot="site-brand">
        {site.seo.site_name}
      </Link>
      <nav aria-label="사이트" data-slot="menu">
        <ul>
          <li>
            <Link href="/">처음</Link>
          </li>
          {site.menu_boards.map((b) => (
            <li key={b.slug}>
              <Link href={`/boards/${b.slug}`}>{b.name}</Link>
            </li>
          ))}
          <li>
            <Link href="/search">검색</Link>
          </li>
          <li>
            <Link href="/me/notifications">알림</Link>
          </li>
        </ul>
      </nav>
    </>
  );
}
