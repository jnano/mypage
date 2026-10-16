import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { SkipLink } from "@/components/blocks/SkipLink";
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

// 루트 레이아웃 — 문서 뼈대와 건너뛰기 링크만(틀 밖 고정 줄, 홈블록 설계도 §3.2). 머리·본문·발은 화면 종류마다
// 틀(components/blocks/Frame)이 그린다: 경로 그룹 (frame)/(…) · boards/[slug] · [[...path]] · not-found. 관리·개발은 틀 없음
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko">
      <body>
        <SkipLink />
        {children}
        <Suspense>
          <Connection />
        </Suspense>
      </body>
    </html>
  );
}
