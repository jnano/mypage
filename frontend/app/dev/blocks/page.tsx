import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";
import { RenderBlocks } from "@/components/blocks/RenderBlock";
import { exampleNodes } from "@/lib/blocks/examples";
import { serverConfig } from "@/lib/server/config";

export const metadata = { title: "블록 견본", robots: { index: false } };

// 개발 견본 화면(홈블록 설계도 §4.4.2) — 지금 그릴 수 있는 블록을 생성 파일의 견본으로 모두 그린다.
// 블록 부품의 접근성 검사 대상이다. 걸음 7 의 시드 페이지가 생기면 그쪽으로 바꾼다
export default function DevBlocksPage() {
  return (
    <Suspense fallback={null}>
      <DevBlocks />
    </Suspense>
  );
}

async function DevBlocks() {
  await connection(); // 환경 변수를 빌드 때가 아니라 요청 때 읽는다
  // APP_ENV=dev 하나로 연다 — /dev/login 은 보는 사람을 바꾸는 기능이라 DEV_VIEWER_LOGIN 까지 켜야 하지만, 이 화면은 견본만 그린다
  if (serverConfig().appEnv !== "dev") notFound();
  return (
    <section data-slot="dev-blocks">
      <h1>블록 견본</h1>
      <p>개발 환경 전용입니다. 그림은 썸네일 전(자리 표시) 모양입니다.</p>
      <RenderBlocks nodes={exampleNodes()} />
    </section>
  );
}
