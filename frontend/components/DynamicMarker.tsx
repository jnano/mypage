import { connection } from "next/server";
import { Suspense } from "react";

// 동적 표시 부품(Next 문서 generate-metadata 'With Cache Components') — 루트 레이아웃의 사이트 메타는 요청 시점 데이터라
// (빌드 때 FastAPI 를 부르지 않는다), 페이지 자체가 완전히 정적이면 메타가 막힌다. 그런 페이지에 이 부품을 두어
// '요청 시점 렌더가 의도한 것'임을 밝힌다. 화면의 정적 셸은 그대로 미리 만들어진다.
// 레이아웃에도 같은 부품이 있지만, 개발 서버의 즉시 이동 검증은 페이지 단위라 레이아웃 것은 세지 않는다.
async function Connection() {
  await connection();
  return null;
}

export function DynamicMarker() {
  return (
    <Suspense>
      <Connection />
    </Suspense>
  );
}
