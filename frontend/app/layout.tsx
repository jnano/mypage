import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";
import { siteMetadata } from "@/lib/seo/meta";
import { getSite } from "@/lib/server/seo";
import "./globals.css";

// 사이트 메타(§10) — 이름 틀·설명·검색엔진 확인·전체 피드. 사이트 설정(settings:seo)이 바뀌면 다시 만든다
export async function generateMetadata(): Promise<Metadata> {
  await connection(); // 요청 시점 — 캐시된 외부 데이터만 쓰면 빌드 때 미리 만들어진다(백엔드 없는 빌드 규칙)
  return siteMetadata((await getSite()).seo);
}

// 사이트 메타는 요청 시점 데이터(관리 화면에서 바뀐다)라 빌드 때 만들지 않는다 — 문서의 '동적 표시' 방식.
// 화면의 정적 셸은 그대로 미리 만들어지고, 메타만 요청 때 채워진다
async function Connection() {
  await connection();
  return null;
}

// 골격 레이아웃 — 시맨틱 HTML + data-slot, class·스타일 없음(설계도 §13, §13.1)
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko">
      <body>
        <a href="#main" data-slot="skip-link">
          본문 바로가기
        </a>
        <header data-slot="site-header">
          <nav aria-label="사이트">
            <Link href="/">처음</Link> <Link href="/search">검색</Link> <Link href="/me/notifications">알림</Link>
          </nav>
        </header>
        <main id="main" data-slot="site-main">
          {children}
        </main>
        <footer data-slot="site-footer" />
        <Suspense>
          <Connection />
        </Suspense>
      </body>
    </html>
  );
}
