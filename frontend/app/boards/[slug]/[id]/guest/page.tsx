import { notFound } from "next/navigation";
import { GuestPasswordForm } from "@/components/boards/GuestPasswordForm";
import { guestTokenAction } from "../../../guestActions";

// 비회원 글의 비밀번호 확인(설계도 §6.3) — 비밀글 열기(read) 또는 수정·삭제(edit). 맞으면 그 글의 HttpOnly 쿠키를 심고 돌아간다
export const metadata = { title: "비밀번호 확인", robots: { index: false, follow: false } };

const PURPOSE = {
  read: { title: "비밀글 열기", next: "post", label: "열기" },
  edit: { title: "비회원 글 수정·삭제", next: "edit", label: "확인" },
} as const;

export default async function GuestPasswordPage({ params, searchParams }: PageProps<"/boards/[slug]/[id]/guest">) {
  const { slug, id } = await params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) notFound();
  const raw = (await searchParams).purpose;
  const key = raw === "read" ? "read" : "edit";
  const p = PURPOSE[key];
  const purpose = key === "read" ? "read" : "edit";
  return (
    <section data-slot="guest-password">
      <h1>{p.title}</h1>
      <GuestPasswordForm action={guestTokenAction.bind(null, slug, Number(id), purpose, p.next)} submitLabel={p.label} />
    </section>
  );
}
