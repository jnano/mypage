import Link from "next/link";
import { connection } from "next/server";
import { Suspense, type ReactNode } from "react";
import { AccountNav } from "@/components/auth/AccountNav";
import { visibleNodes } from "@/lib/blocks/frame";
import type { BlockNode, FrameBundle, FrameNode } from "@/lib/blocks/types";
import { getFrame, getPersonalBlocks, type FrameQuery } from "@/lib/server/frame";
import { resolvePage } from "@/lib/server/pages";
import { hasViewer } from "@/lib/server/backend";
import { getSite } from "@/lib/server/seo";
import { RenderBlocks } from "./RenderBlock";

/** 화면 종류(홈블록 설계도 §3.3 — 원본은 백엔드 app/blocks/routes.ROUTE_CLASSES). page = 사용자 페이지, default = 대응 없음 */
export type RouteClass = "board" | "search" | "member" | "auth" | "default" | "page";
type Region = "header" | "nav" | "top" | "aside" | "bottom" | "footer";
// fallbackOnly — 블록 틀 대신 대체 틀 머리만(루트 not-found 전용, 홈블록 걸음 8 결정 ①). not-found 는 요청마다 미리 그려져
// 그 결과가 모든 응답의 RSC 페이로드에 실린다(D-232·D-235) — 기본 틀 전체를 그리면 모든 화면이 그만큼 커진다
type FrameProps = { routeClass: RouteClass; board?: Promise<{ slug: string }>; page?: Promise<string>; children: ReactNode; fallbackOnly?: boolean };

// 틀(홈블록 설계도 §3.1) — 영역 여섯은 각자 <Suspense> 안에서 요청 시점에 그린다(틀은 관리 화면에서 바뀌고, 빌드 때
// FastAPI 를 부르지 않는다 — 본 설계도 §3.3). 데이터는 캐시된 틀 묶음 하나(getFrame)를 영역들이 함께 쓴다.
// outlet(children)은 Suspense 밖이라 화면의 정적 셸은 그대로 미리 만들어진다. 본문 <main> 하나·처리방침 링크는
// 틀 밖 고정 줄(§3.2). 틀이 하나도 없으면 대체 틀(§3.6) — 걸음 1 과 같은 화면
export function Frame({ routeClass, board, page, children, fallbackOnly }: FrameProps) {
  const region = (name: Region) => (
    <Suspense fallback={null}>
      <FrameRegion name={name} routeClass={routeClass} board={board} page={page} fallbackOnly={fallbackOnly} />
    </Suspense>
  );
  return (
    <div data-slot="frame" data-route-class={routeClass}>
      {region("header")}
      {region("nav")}
      <div data-slot="frame-body">
        <main id="main" data-slot="site-main">
          {region("top")}
          {children}
          {region("bottom")}
        </main>
        {region("aside")}
      </div>
      <footer data-slot="site-footer">
        {region("footer")}
        <p data-slot="policy-links">
          <Link href="/privacy">개인정보 처리 고지</Link>
        </p>
      </footer>
    </div>
  );
}

async function frameQuery(routeClass: RouteClass, board?: Promise<{ slug: string }>): Promise<FrameQuery> {
  if (board) return { board: (await board).slug };
  return routeClass === "search" || routeClass === "member" || routeClass === "auth" ? { route: routeClass } : {};
}

/** 사용자 페이지면 그 페이지의 묶음(공개·개인·초안 — resolvePage, 요청마다 한 번), 아니면 화면 종류·게시판의 공개 틀 묶음 */
async function bundleFor(routeClass: RouteClass, board?: Promise<{ slug: string }>, page?: Promise<string>): Promise<FrameBundle> {
  if (page) {
    const resolved = await resolvePage(await page);
    if (resolved.kind === "page") return resolved.bundle;
  }
  return getFrame(await frameQuery(routeClass, board));
}

/** 묶음의 블록 → 지금 그릴 블록. 비회원 대상은 보는 사람이 있으면 숨기고, 회원 블록 자리는 회원 블록 호출로 채운다(§5.2 결정 A).
 * 영역들과 페이지 본문이 함께 쓴다 — 회원 블록 호출은 요청마다 한 번(React cache) */
export async function visibleIn(bundle: FrameBundle, nodes: FrameNode[] | undefined): Promise<BlockNode[]> {
  const signedIn = await hasViewer(); // 게시판 화면과 같은 판정 — 쿠키 유무만(유효성은 FastAPI)
  const ids = bundle.personal_block_ids;
  const personal = signedIn && ids.length > 0 ? await getPersonalBlocks([...ids].sort((a, b) => a - b).join(",")) : undefined;
  return visibleNodes(nodes, signedIn && (ids.length === 0 || personal !== undefined), personal);
}

// 영역 → 랜드마크(§10 — 대응은 여기 한 곳). nav 영역은 블록마다 <nav aria-label> 라 감싸지 않는다. 빈 영역은 그리지 않는다
async function FrameRegion({ name, routeClass, board, page, fallbackOnly }: { name: Region } & Omit<FrameProps, "children">) {
  await connection();
  if (fallbackOnly) return name === "header" ? <FallbackHeader /> : null; // not-found — 대체 틀 머리만(D-235)
  const bundle = await bundleFor(routeClass, board, page);
  if (bundle.layout === null) return name === "header" ? <FallbackHeader /> : null;
  const nodes = await visibleIn(bundle, bundle.layout.regions[name]);
  if (nodes.length === 0) return null;
  const blocks = <RenderBlocks nodes={nodes} />;
  switch (name) {
    case "header":
      return (
        <header data-slot="site-header" data-region="header">
          {blocks}
        </header>
      );
    case "aside":
      return <aside data-region="aside">{blocks}</aside>;
    default:
      return <div data-region={name}>{blocks}</div>;
  }
}

// 대체 틀의 머리(§3.6) — 사이트 이름 + 메뉴(처음 · 메뉴 노출 게시판 · 검색 · 알림) + 계정. 데이터는 캐시된 /api/site 하나
async function FallbackHeader() {
  const site = await getSite();
  return (
    <header data-slot="site-header" data-region="header">
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
      <AccountNav />
    </header>
  );
}
