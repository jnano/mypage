import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Frame } from "@/components/blocks/Frame";
import { getSite } from "@/lib/server/seo";

// 사용자 페이지(홈블록 설계도 §3.5·§5.1) — 다른 라우트가 맞지 않은 주소를 받는다(선택 catch-all 이라 / 도 여기).
// 걸음 1: 페이지 표가 아직 없어 / 는 대체 첫 화면(§3.6), 나머지는 FastAPI 를 부르지 않고 404(§5.5 의 '주소 집합 먼저'의 자리).
// params 는 요청 시점 데이터라 <Suspense> 안에서 기다린다(Next 문서 dynamic-routes 'Without generateStaticParams')
// 없는 주소의 404 를 메타에서도 낸다 — 봇(htmlLimitedBots)은 메타를 기다리므로 실제 HTTP 404 를 받는다.
// 사람의 브라우저는 스트리밍이 먼저 시작돼 200 + noindex 의 '찾을 수 없음' 화면이다(게시판의 없는 주소와 같음 — 본 설계도 §10.1, D-205)
export async function generateMetadata({ params }: PageProps<"/[[...path]]">): Promise<Metadata> {
  const { path } = await params;
  if (path && path.length > 0) notFound();
  return {};
}

export default function SitePage({ params }: PageProps<"/[[...path]]">) {
  return (
    <Frame routeClass="page">
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <PageScreen params={params} />
      </Suspense>
    </Frame>
  );
}

async function PageScreen({ params }: { params: PageProps<"/[[...path]]">["params"] }) {
  const { path } = await params;
  if (path && path.length > 0) notFound();
  return <FallbackHome />;
}

// 대체 첫 화면(§3.6) — 사이트 이름 + 메뉴 노출 게시판. 예전의 하드코딩 링크(시드 게시판 이름)를 대신한다
async function FallbackHome() {
  const site = await getSite();
  return (
    <section data-slot="home">
      <h1>{site.seo.site_name}</h1>
      {site.menu_boards.length > 0 ? (
        <ul>
          {site.menu_boards.map((b) => (
            <li key={b.slug}>
              <Link href={`/boards/${b.slug}`}>{b.name}</Link>
            </li>
          ))}
        </ul>
      ) : (
        <p data-slot="empty">아직 게시판이 없습니다.</p>
      )}
    </section>
  );
}
