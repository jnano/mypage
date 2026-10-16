"use client";

import { useEffect, useRef } from "react";

// 조회 신호(설계도 §6.1) — 마운트될 때 한 번. 글 화면은 공개 캐시라 서버 렌더에서 셀 수 없다.
// 개발 모드 StrictMode 의 이중 실행은 ref 로 막는다. 자동화 브라우저(navigator.webdriver)는 보내지 않는다.
export function ViewBeacon({ postId }: { postId: number }) {
  const sent = useRef(false);
  useEffect(() => {
    if (sent.current || navigator.webdriver) return;
    sent.current = true;
    fetch(`/api/posts/${postId}/view`, { method: "POST", keepalive: true }).catch(() => {});
  }, [postId]);
  return null;
}
