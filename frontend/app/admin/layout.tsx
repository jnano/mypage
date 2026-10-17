import Link from "next/link";
import { Suspense } from "react";
import { AccountNav } from "@/components/auth/AccountNav";
import { adminFontVariables } from "@/skins/admin/fonts";
import "@/skins/admin/base-tokens.css";
import "@/skins/admin/tokens.css";
import "@/skins/admin/buttons.css";

// 관리 화면 골격(설계도 §14) — 운영자는 전체, 게시판 담당자는 맡은 게시판으로 서버가 범위를 좁힌다
export const metadata = { robots: { index: false, follow: false } };

const NAV: [string, string][] = [
  ["/admin", "대시보드"],
  ["/admin/boards", "게시판"],
  ["/admin/posts", "글"],
  ["/admin/pending", "승인 대기"],
  ["/admin/comments", "댓글"],
  ["/admin/reports", "신고"],
  ["/admin/logs", "운영 기록"],
  ["/admin/members", "회원"],
  ["/admin/members/pending", "가입 대기"],
  ["/admin/member-groups", "그룹"],
  ["/admin/level-requests", "승급 신청"],
  ["/admin/privacy-notices", "개인정보 고지"],
  ["/admin/layouts", "틀"],
  ["/admin/pages", "페이지"],
  ["/admin/menus", "메뉴"],
  ["/admin/blocks", "끊긴 블록"],
  ["/admin/settings", "사이트 설정"],
  ["/admin/jobs", "실패 작업"],
];

// 관리 화면은 블록 틀을 쓰지 않는다(홈블록 설계도 §1.2) — 머리·본문 랜드마크를 여기서 직접 둔다.
// 모양은 스킨 skins/admin(관리디자인 지시서). className 은 골격의 class 금지(설계도 §13.1)의 명시적 예외 하나 —
// next/font 가 글꼴 CSS 변수를 이 방식으로만 준다(Next 공식 문서 Fonts). 스킨 선택자는 여전히 data-slot 만 쓴다
export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <div data-slot="admin" className={adminFontVariables}>
      <header data-slot="admin-header">
        <Link href="/">사이트로</Link>{" "}
        <Suspense fallback={null}>
          <AccountNav />
        </Suspense>
      </header>
      <nav aria-label="관리" data-slot="admin-nav">
        <ul>
          {NAV.map(([href, label]) => (
            <li key={href}>
              <Link href={href}>{label}</Link>
            </li>
          ))}
        </ul>
      </nav>
      <main id="main" data-slot="admin-main">
        {children}
      </main>
    </div>
  );
}
