import Link from "next/link";

// 관리 화면 골격(설계도 §14) — 운영자는 전체, 게시판 담당자는 맡은 게시판으로 서버가 범위를 좁힌다
export const metadata = { robots: { index: false, follow: false } };

const NAV: [string, string][] = [
  ["/admin", "대시보드"],
  ["/admin/boards", "게시판"],
  ["/admin/posts", "글"],
  ["/admin/pending", "승인 대기"],
  ["/admin/comments", "댓글"],
  ["/admin/reports", "신고"],
  ["/admin/sanctions", "제재"],
  ["/admin/logs", "운영 기록"],
  ["/admin/settings", "사이트 설정"],
  ["/admin/jobs", "실패 작업"],
];

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <div data-slot="admin">
      <nav aria-label="관리" data-slot="admin-nav">
        <ul>
          {NAV.map(([href, label]) => (
            <li key={href}>
              <Link href={href}>{label}</Link>
            </li>
          ))}
        </ul>
      </nav>
      <div data-slot="admin-main">{children}</div>
    </div>
  );
}
