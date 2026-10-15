import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "mypage", template: "%s – mypage" },
};

// 골격 레이아웃 — 시맨틱 HTML + data-slot, class·스타일 없음(설계도 §13, §13.1)
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko">
      <body>
        <a href="#main" data-slot="skip-link">
          본문 바로가기
        </a>
        <header data-slot="site-header">
          <nav aria-label="사이트">
            <Link href="/">처음</Link> <Link href="/search">검색</Link>
          </nav>
        </header>
        <main id="main" data-slot="site-main">
          {children}
        </main>
        <footer data-slot="site-footer" />
      </body>
    </html>
  );
}
