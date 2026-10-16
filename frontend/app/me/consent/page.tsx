import Link from "next/link";
import { cookies } from "next/headers";
import { Suspense } from "react";
import { consentAction } from "@/app/auth/actions";
import { ConsentForm } from "@/components/auth/ConsentForm";
import { ApiError } from "@/lib/api/problem";
import { cookieNames } from "@/lib/auth/cookies";
import { safeNextPath } from "@/lib/auth/next";
import { noticeParagraphs } from "@/lib/auth/notice";
import { publicGet } from "@/lib/server/backend";
import { serverConfig } from "@/lib/server/config";

export const metadata = { title: "개인정보 고지 동의", robots: { index: false } };

interface Notice {
  version: string;
  body: string;
  published_at: string | null;
}

// 재동의(인증 설계도 §3.6·§6) — 재동의 쿠키(5분)가 있을 때만 동의 폼. 동의 전에는 세션이 없다
export default function ConsentPage(props: PageProps<"/me/consent">) {
  return (
    <section data-slot="consent">
      <h1>개인정보 고지가 바뀌었습니다</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Consent {...props} />
      </Suspense>
    </section>
  );
}

async function Consent({ searchParams }: PageProps<"/me/consent">) {
  const raw = (await searchParams).next;
  const next = safeNextPath(typeof raw === "string" ? raw : "/");
  if (!(await cookies()).get(cookieNames(serverConfig().appEnv).consent)) {
    return (
      <p>
        동의 시간이 지났습니다. <Link href={`/login?next=${encodeURIComponent(next)}`}>다시 로그인</Link> 해 주세요.
      </p>
    );
  }
  let notice: Notice;
  try {
    notice = await publicGet<Notice>("/api/privacy-notices/current");
  } catch (e) {
    if (e instanceof ApiError) return <p role="alert">{e.problem.title}</p>;
    throw e;
  }
  return (
    <>
      <p>계속 이용하려면 새 고지에 동의해 주세요. 동의하지 않으면 로그인되지 않습니다.</p>
      <article data-slot="privacy-notice" aria-label={`개인정보 고지 ${notice.version}`}>
        {noticeParagraphs(notice.body).map((para, i) => (
          <p key={i}>{para}</p>
        ))}
      </article>
      <ConsentForm action={consentAction.bind(null, next)} />
      <p>
        동의하지 않으려면 <Link href="/">처음으로</Link> 돌아가세요. 탈퇴는 로그인한 뒤 내 계정에서 할 수 있습니다.
      </p>
    </>
  );
}
