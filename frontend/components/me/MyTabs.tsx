import Link from "next/link";

// 내 목록 탭(설계도 §6.2) — 헤드리스. 지금 화면은 aria-current
const TABS = [
  { href: "/me/posts", label: "내 글" },
  { href: "/me/comments", label: "내 댓글" },
  { href: "/me/scraps", label: "스크랩" },
] as const;

export function MyTabs({ current }: { current?: (typeof TABS)[number]["href"] }) {
  return (
    <nav data-slot="my-tabs" aria-label="내 목록">
      <ul>
        {TABS.map((t) => (
          <li key={t.href}>
            <Link href={t.href} aria-current={t.href === current ? "page" : undefined}>
              {t.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
