import { notFound } from "next/navigation";
import { Suspense } from "react";
import { GuestPasswordForm } from "@/components/boards/GuestPasswordForm";
import { guestTokenAction } from "../../../guestActions";

// 비회원 글의 비밀번호 확인(설계도 §6.3) — 비밀글 열기(read) 또는 수정·삭제(edit). 맞으면 그 글의 HttpOnly 쿠키를 심고 돌아간다
export const metadata = { title: "비밀번호 확인", robots: { index: false, follow: false } };

const PURPOSE = {
  read: { title: "비밀글 열기", next: "post", label: "열기" },
  edit: { title: "비회원 글 수정·삭제", next: "edit", label: "확인" },
} as const;

export default function GuestPasswordPage(props: PageProps<"/boards/[slug]/[id]/guest">) {
  return (
    <section data-slot="guest-password">
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <GuestPassword {...props} />
      </Suspense>
    </section>
  );
}

async function GuestPassword({ params, searchParams }: PageProps<"/boards/[slug]/[id]/guest">) {
  const { slug, id } = await params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) notFound();
  const key = (await searchParams).purpose === "read" ? "read" : "edit";
  const p = PURPOSE[key];
  return (
    <>
      <h1>{p.title}</h1>
      <GuestPasswordForm action={guestTokenAction.bind(null, slug, Number(id), key, p.next)} submitLabel={p.label} />
    </>
  );
}
