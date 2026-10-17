// 관리 메뉴 다섯 묶음과 '지금 메뉴' 판정 — 순수 데이터·함수(Vitest 대상). 그리는 쪽은 components/admin/AdminNav
export const ADMIN_NAV: { title: string; items: [string, string][] }[] = [
  { title: "한눈에", items: [["/admin", "대시보드"]] },
  {
    title: "콘텐츠",
    items: [
      ["/admin/boards", "게시판"],
      ["/admin/posts", "글"],
      ["/admin/pending", "승인 대기"],
      ["/admin/comments", "댓글"],
      ["/admin/reports", "신고"],
    ],
  },
  {
    title: "회원",
    items: [
      ["/admin/members", "회원"],
      ["/admin/members/pending", "가입 대기"],
      ["/admin/level-requests", "승급 신청"],
      ["/admin/member-groups", "그룹"],
      ["/admin/privacy-notices", "개인정보 고지"],
    ],
  },
  {
    title: "사이트 꾸미기",
    items: [
      ["/admin/layouts", "틀"],
      ["/admin/pages", "페이지"],
      ["/admin/menus", "메뉴"],
    ],
  },
  {
    title: "점검·설정",
    items: [
      ["/admin/blocks", "끊긴 블록"],
      ["/admin/jobs", "실패 작업"],
      ["/admin/logs", "운영 기록"],
      ["/admin/settings", "사이트 설정"],
    ],
  },
];

const ALL = ADMIN_NAV.flatMap((g) => g.items.map(([href]) => href));

/** 지금 주소에 가장 길게 맞는 메뉴 — /admin/members/pending 이 /admin/members 보다 먼저, 하위 경로는 부모 메뉴 */
export function currentNav(pathname: string): string | undefined {
  return ALL.filter((href) => pathname === href || (href !== "/admin" && pathname.startsWith(`${href}/`))).sort((a, b) => b.length - a.length)[0];
}

