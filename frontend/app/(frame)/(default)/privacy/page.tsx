import Link from "next/link";
import { Suspense } from "react";
import { ApiError } from "@/lib/api/problem";
import { safeNextPath } from "@/lib/auth/next";
import { noticeParagraphs } from "@/lib/auth/notice";
import { publicGet } from "@/lib/server/backend";

export const metadata = { title: "개인정보 처리 고지" };

interface Notice {
  version: string;
  body: string;
  published_at: string | null;
}

// 현재 개인정보 고지(인증 설계도 §6). 로그인 직후 '바뀌었습니다' 한 번 안내도 여기서(updated=1)
export default function PrivacyPage(props: PageProps<"/privacy">) {
  return (
    <section data-slot="privacy">
      <h1>개인정보 처리 고지</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Privacy {...props} />
      </Suspense>
    </section>
  );
}

async function Privacy({ searchParams }: PageProps<"/privacy">) {
  const sp = await searchParams;
  const next = typeof sp.next === "string" ? safeNextPath(sp.next) : null;
  let notice: Notice;
  try {
    notice = await publicGet<Notice>("/api/privacy-notices/current");
  } catch (e) {
    if (e instanceof ApiError) return <p>{e.problem.title}</p>;
    throw e;
  }
  return (
    <>
      {sp.updated === "1" && (
        <p role="status">
          개인정보 처리 고지가 바뀌었습니다(판 {notice.version}). 아래에서 확인해 주세요.{" "}
          {next && <Link href={next}>계속하기</Link>}
        </p>
      )}
      <article data-slot="privacy-notice" aria-label={`판 ${notice.version}`}>
        {noticeParagraphs(notice.body).map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </article>
    </>
  );
}
