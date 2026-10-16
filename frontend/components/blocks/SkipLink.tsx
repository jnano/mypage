"use client";

import type { MouseEvent } from "react";
import { focusVisibleMain } from "@/lib/blocks/skipLink";

// 건너뛰기 링크(WCAG 2.4.1, 홈블록 설계도 §3.2). 틀이 화면 종류마다 따로라 <main id="main"> 도 화면마다 하나씩이고,
// 클라이언트 이동 뒤에는 앞서 본 화면이 숨겨진 채(display:none) DOM 에 남는다(cacheComponents 의 이전 화면 보존) —
// 그래서 같은 id 가 여럿일 수 있다. '#main' 이 숨은 본문을 가리키지 않게 보이는 본문으로 옮긴다. JS 가 없으면
// 클라이언트 이동도 없어 본문은 하나이므로 기본 동작(#main)이 그대로 맞다
export function SkipLink() {
  function onClick(e: MouseEvent<HTMLAnchorElement>) {
    if (focusVisibleMain(document)) e.preventDefault();
  }
  return (
    <a href="#main" data-slot="skip-link" onClick={onClick}>
      본문 바로가기
    </a>
  );
}
