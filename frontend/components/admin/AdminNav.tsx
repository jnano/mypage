"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { ADMIN_NAV, currentNav } from "@/lib/admin/nav";

// 관리 메뉴 — 다섯 묶음(관리디자인 지시서 §6.1). 지금 화면 링크에 aria-current. 권한에 따라 숨기지 않는다 —
// 범위는 서버가 좁히고 담당자에게 없는 화면은 '권한 없음'으로 답한다(설계도 §14).
// 모바일은 머리 단추가 여는 서랍(popover, JS 없이 열림), 1024px 이상은 늘 보이는 옆 메뉴(스킨 shell.css)
export const DRAWER_ID = "admin-drawer";

/** 메뉴 목록 — current 가 없으면 '지금 화면' 표시 없이(Suspense 대기 중의 자리) */
export function AdminNavList({ current }: { current?: string }) {
  return (
    <nav aria-label="관리" data-slot="admin-nav">
      {ADMIN_NAV.map((g, i) => (
        <section key={g.title} aria-labelledby={`admin-nav-${i}`}>
          <h2 id={`admin-nav-${i}`}>{g.title}</h2>
          <ul>
            {g.items.map(([href, label]) => (
              <li key={href}>
                <Link href={href} aria-current={href === current ? "page" : undefined}>
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </nav>
  );
}

/** 지금 주소를 읽는 메뉴 — 요청 시점 데이터라 레이아웃이 <Suspense fallback={<AdminNavList />}> 안에 둔다(cacheComponents) */
export function AdminNav() {
  const pathname = usePathname();
  // 서랍을 연 채 이동하거나 화면이 넓어지면 닫는다(넓은 화면은 서랍이 아니라 옆 메뉴)
  useEffect(() => {
    const drawer = document.getElementById(DRAWER_ID);
    if (drawer?.matches(":popover-open")) drawer.hidePopover();
  }, [pathname]);
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 1024px)");
    const close = () => {
      const drawer = document.getElementById(DRAWER_ID);
      if (wide.matches && drawer?.matches(":popover-open")) drawer.hidePopover();
    };
    wide.addEventListener("change", close);
    return () => wide.removeEventListener("change", close);
  }, []);
  return <AdminNavList current={currentNav(pathname)} />;
}
