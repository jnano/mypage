import type { ReactNode } from "react";

// 개발 전용 화면 — 틀 없음(홈블록 설계도 §3.3 표). 본문 랜드마크만
export default function DevLayout({ children }: { children: ReactNode }) {
  return (
    <main id="main" data-slot="site-main">
      {children}
    </main>
  );
}
