import Link from "next/link";
import { Suspense } from "react";
import { AdminNav, AdminNavList, DRAWER_ID } from "@/components/admin/AdminNav";
import { Icon } from "@/components/admin/Icon";
import { AccountNav } from "@/components/auth/AccountNav";
import { adminFontVariables } from "@/skins/admin/fonts";
import "@/skins/admin/base-tokens.css";
import "@/skins/admin/tokens.css";
import "@/skins/admin/buttons.css";
import "@/skins/admin/forms.css";
import "@/skins/admin/status.css";
import "@/skins/admin/dialog.css";
import "@/skins/admin/shell.css";
import "@/skins/admin/lists.css";
import "@/skins/admin/screens.css";
import "@/skins/admin/editor.css";
import "@/skins/admin/adapt.css";

// 관리 화면 골격(설계도 §14) — 운영자는 전체, 게시판 담당자는 맡은 게시판으로 서버가 범위를 좁힌다
export const metadata = { robots: { index: false, follow: false } };

// 관리 화면은 블록 틀을 쓰지 않는다(홈블록 설계도 §1.2) — 머리·본문 랜드마크를 여기서 직접 둔다.
// 모양은 스킨 skins/admin(관리디자인 지시서). className 은 골격의 class 금지(설계도 §13.1)의 명시적 예외 하나 —
// next/font 가 글꼴 CSS 변수를 이 방식으로만 준다(Next 공식 문서 Fonts). 스킨 선택자는 여전히 data-slot 만 쓴다
export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <div data-slot="admin" className={adminFontVariables}>
      <header data-slot="admin-header">
        <button type="button" popoverTarget={DRAWER_ID} aria-controls={DRAWER_ID} aria-label="관리 메뉴 열기" data-shape="icon">
          <Icon name="menu" />
        </button>
        <strong>관리</strong>
        <Link href="/">사이트로</Link>
        <span data-slot="account-placeholder">
          <Suspense fallback={null}>
            <AccountNav />
          </Suspense>
        </span>
      </header>
      <div id={DRAWER_ID} popover="auto" data-slot="admin-drawer">
        <div data-slot="drawer-head">
          <strong>관리</strong>
          <button type="button" popoverTarget={DRAWER_ID} popoverTargetAction="hide" aria-label="관리 메뉴 닫기" data-shape="icon">
            <Icon name="x" />
          </button>
        </div>
        <Suspense fallback={<AdminNavList />}>
          <AdminNav />
        </Suspense>
      </div>
      <main id="main" data-slot="admin-main">
        {children}
      </main>
    </div>
  );
}
