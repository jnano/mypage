import Link from "next/link";
import type { ReactNode } from "react";
import type { ProblemBody } from "@/lib/api/problem";
import { MyTabs } from "@/components/me/MyTabs";

// 내 목록 화면 틀(설계도 §6.2) — 제목·탭·로그인 안내·오류·'더 보기'
type Current = "/me/posts" | "/me/comments" | "/me/scraps";

export function LoginHint({ next }: { next: Current }) {
  return (
    <p>
      <Link href={`/login?next=${encodeURIComponent(next)}`}>로그인</Link> 하면 볼 수 있습니다.
    </p>
  );
}

export function ProblemLine({ problem }: { problem: ProblemBody }) {
  return <p role="alert">{problem.title}</p>;
}

export function MoreLink({ href }: { href: string | null }) {
  return href ? (
    <p data-slot="more">
      <Link href={href}>더 보기</Link>
    </p>
  ) : null;
}

export function MyListFrame({ title, current, children }: { title: string; current: Current; children: ReactNode }) {
  return (
    <section data-slot="my-list">
      <h1>{title}</h1>
      <MyTabs current={current} />
      {children}
    </section>
  );
}
