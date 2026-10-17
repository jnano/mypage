import { Frame } from "@/components/blocks/Frame";

// 게시판 화면의 틀(홈블록 설계도 §3.3) — 게시판별 틀은 params 를 아래 부품(영역)에서 기다린다(레이아웃 위에서 기다리지
// 않는다: Next 문서 dynamic-routes 'In layouts, avoid awaiting params at the top level')
export default function BoardLayout({ children, params }: LayoutProps<"/boards/[slug]">) {
  return (
    <Frame routeClass="board" board={params}>
      {children}
    </Frame>
  );
}
