import Link from "next/link";
import { Frame } from "@/components/blocks/Frame";

// 없는 주소(홈블록 설계도 §5.5) — 루트의 not-found 경계라 화면 종류의 레이아웃 밖에서 그려진다. 그래서 틀을 직접 둔다(틀이 겹치지 않음)
export default function NotFound() {
  return (
    <Frame routeClass="default">
      <section data-slot="not-found">
        <h1>페이지를 찾을 수 없습니다</h1>
        <p>
          주소를 확인하거나 <Link href="/">처음 화면</Link>으로 가세요.
        </p>
      </section>
    </Frame>
  );
}
