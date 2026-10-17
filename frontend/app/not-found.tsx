import Link from "next/link";
import { Frame } from "@/components/blocks/Frame";

// 없는 주소(홈블록 설계도 §5.5) — 루트의 not-found 경계라 화면 종류의 레이아웃 밖에서 그려진다. 그래서 틀을 직접 둔다(틀이 겹치지 않음).
// 틀은 대체 틀 머리만(fallbackOnly) — 루트 not-found 는 요청마다 미리 그려져 모든 응답의 RSC 에 실리므로 작게(걸음 8 결정 ①, D-235).
// 게시판·사용자 페이지 안의 없는 주소(notFound())는 그 화면의 레이아웃 틀을 그대로 쓴다
export default function NotFound() {
  return (
    <Frame routeClass="default" fallbackOnly>
      <section data-slot="not-found">
        <h1>페이지를 찾을 수 없습니다</h1>
        <p>
          주소를 확인하거나 <Link href="/">처음 화면</Link>으로 가세요.
        </p>
      </section>
    </Frame>
  );
}
