import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";
import { PostForm } from "@/components/boards/PostForm";
import { ProblemNotice } from "@/components/boards/ProblemNotice";
import { ApiError } from "@/lib/api/problem";
import type { BoardPage } from "@/lib/boards/types";
import { hasViewer, personalGet } from "@/lib/server/backend";
import { loadGuestForm, type GuestForm } from "@/lib/server/guest";
import { createPostAction } from "../../actions";
import { createGuestPostAction } from "../../guestActions";

export const metadata = { title: "글쓰기" };

export default function WritePage(props: PageProps<"/boards/[slug]/write">) {
  return (
    <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
      <WriteScreen {...props} />
    </Suspense>
  );
}

async function WriteScreen({ params }: PageProps<"/boards/[slug]/write">) {
  const { slug } = await params;
  if (!(await hasViewer())) return <GuestWrite slug={slug} />;
  let data: BoardPage;
  try {
    data = await personalGet<BoardPage>(`/api/boards/${encodeURIComponent(slug)}/page`);
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 404) notFound();
      return <ProblemNotice problem={e.problem} />;
    }
    throw e;
  }
  await connection(); // 요청마다 새 멱등 키
  const idempotencyKey = crypto.randomUUID();
  return (
    <section>
      <h1>{data.board.name} 글쓰기</h1>
      <PostForm
        action={createPostAction.bind(null, slug, idempotencyKey)}
        format={data.board.editor}
        allowSecret={data.board.allow_secret}
        categories={data.categories}
        submitLabel="등록"
        boardSlug={slug}
      />
    </section>
  );
}

/** 비회원 — 쓰기 등급 0 인 게시판이면 비회원 폼(§6.3), 아니면 로그인 안내 */
async function GuestWrite({ slug }: { slug: string }) {
  await connection(); // 폼 토큰·보안 문자는 요청마다 새로
  let form: GuestForm;
  try {
    form = await loadGuestForm(slug);
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 404) notFound();
      return (
        <section data-slot="error" role="alert">
          <h1>로그인이 필요합니다</h1>
          <p>
            <Link href={`/login?next=${encodeURIComponent(`/boards/${slug}/write`)}`}>로그인</Link> 한 뒤 다시 시도해 주세요.
          </p>
        </section>
      );
    }
    throw e;
  }
  return (
    <section>
      <h1>{form.board.name} 글쓰기</h1>
      <PostForm
        action={createGuestPostAction.bind(null, slug)}
        format={form.board.editor}
        allowSecret={form.board.allow_secret}
        categories={form.board.categories}
        submitLabel="등록"
        boardSlug={slug}
        guest={{ tokens: { form_token: form.form_token, captcha: form.captcha }, honeypot: form.policy.honeypot }}
      />
    </section>
  );
}
