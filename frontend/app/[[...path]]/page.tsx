import type { Metadata } from "next";
import Link from "next/link";
import { notFound, permanentRedirect, redirect } from "next/navigation";
import { Suspense } from "react";
import { Frame, visibleIn } from "@/components/blocks/Frame";
import { RenderBlocks } from "@/components/blocks/RenderBlock";
import { pathOf } from "@/lib/blocks/pagePath";
import { pageMetadata } from "@/lib/seo/meta";
import { resolvePage } from "@/lib/server/pages";
import { getSite } from "@/lib/server/seo";

// 사용자 페이지(홈블록 설계도 §3.5·§5.5·§6.2) — 다른 라우트가 맞지 않은 주소를 받는다(선택 catch-all 이라 / 도 여기).
// 무엇을 그릴지는 resolvePage 한 곳(형식 → 주소 집합 → 공개·개인·초안 / 옛 주소 / 없음). 틀의 영역들도 같은 결과를 쓴다.
// params 는 요청 시점 데이터라 <Suspense> 안에서 기다린다(Next 문서 dynamic-routes 'Without generateStaticParams').
// 없는 주소의 404·옛 주소의 308 은 메타에서도 낸다 — 봇(htmlLimitedBots)은 메타를 기다리므로 실제 HTTP 상태를 받는다.
// 사람의 브라우저는 스트리밍이 먼저 시작돼 200 + noindex 의 '찾을 수 없음' 화면이다(게시판의 없는 주소와 같음 — 본 설계도 §10.1, D-205)
export async function generateMetadata({ params }: PageProps<"/[[...path]]">): Promise<Metadata> {
  const path = pathOf((await params).path);
  const resolved = await resolvePage(path);
  switch (resolved.kind) {
    case "missing":
      notFound();
    case "moved":
      permanentRedirect(resolved.to);
    case "page":
      return pageMetadata((await getSite()).seo, resolved.bundle.page!, resolved.mode);
    case "home-fallback":
      return {};
    default: // 로그인·403 — 제목도 알리지 않는다
      return { robots: { index: false, follow: false } };
  }
}

export default function SitePage({ params }: PageProps<"/[[...path]]">) {
  const path = params.then((p) => pathOf(p.path));
  return (
    <Frame routeClass="page" page={path}>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <PageScreen path={path} />
      </Suspense>
    </Frame>
  );
}

async function PageScreen({ path }: { path: Promise<string> }) {
  const here = await path;
  const resolved = await resolvePage(here);
  switch (resolved.kind) {
    case "missing":
      notFound();
    case "moved":
      permanentRedirect(resolved.to);
    case "login":
      redirect(`/login?next=${encodeURIComponent(here)}`); // 인 §6 의 next 규칙
    case "forbidden":
      return (
        <section data-slot="page-forbidden">
          <h1>볼 수 없는 페이지입니다</h1>
          <p>이 페이지를 볼 수 있는 등급이 아닙니다.</p>
        </section>
      );
    case "home-fallback":
      return <FallbackHome />;
  }
  const page = resolved.bundle.page!;
  const blocks = await visibleIn(resolved.bundle, page.blocks);
  return (
    <article data-slot="user-page" data-page-id={page.id}>
      {resolved.mode === "draft" && (
        <p data-slot="draft-banner" role="status">
          초안 — 공개되지 않음
        </p>
      )}
      <h1>{page.title}</h1>
      <RenderBlocks nodes={blocks} />
    </article>
  );
}

// 대체 첫 화면(§3.6) — '/' 페이지가 없을 때. 사이트 이름 + 메뉴 노출 게시판
async function FallbackHome() {
  const site = await getSite();
  return (
    <section data-slot="home">
      <h1>{site.seo.site_name}</h1>
      <ul>
        {site.menu_boards.map((b) => (
          <li key={b.slug}>
            <Link href={`/boards/${b.slug}`}>{b.name}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
