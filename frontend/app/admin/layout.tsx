import Link from "next/link";
import { Suspense } from "react";
import { AccountNav } from "@/components/auth/AccountNav";

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
  ["/admin/settings", "사이트 설정"],
  ["/admin/jobs", "실패 작업"],
];

// 관리 화면은 블록 틀을 쓰지 않는다(홈블록 설계도 §1.2) — 머리·본문 랜드마크를 여기서 직접 둔다
export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <div data-slot="admin">
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
