import Link from "next/link";
import type { ReactNode } from "react";
import type { BlockLinkView } from "@/lib/blocks/types";

// 블록의 링크 한 곳(홈블록 설계도 §9·§10) — 새 창이면 rel 과 '(새 창)' 을 이름에 덧붙인다. 사이트 안 주소는 클라이언트 이동
export function BlockLink({ link, children, slot }: { link: BlockLinkView; children: ReactNode; slot?: string }) {
  const internal = link.href.startsWith("/");
  if (link.new_window) {
    return (
      <a href={link.href} target="_blank" rel="noopener noreferrer" data-slot={slot}>
        {children}
        <span data-slot="new-window"> (새 창)</span>
      </a>
    );
  }
  return internal ? (
    <Link href={link.href} data-slot={slot}>
      {children}
    </Link>
  ) : (
    <a href={link.href} data-slot={slot}>
      {children}
    </a>
  );
}
