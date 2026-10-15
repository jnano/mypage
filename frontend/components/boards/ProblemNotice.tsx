import Link from "next/link";
import type { ProblemBody } from "@/lib/api/problem";

// 오류 안내 — 문구는 FastAPI(problem.title)가 정한다. 로그인이 필요해 보이면 개발 로그인으로 안내
export function ProblemNotice({ problem }: { problem: ProblemBody }) {
  const needsLogin = problem.status === 401 || problem.code === "board_forbidden" || problem.code === "post_level";
  return (
    <section data-slot="error" data-status={problem.status} role="alert">
      <h1>{problem.title}</h1>
      {needsLogin && (
        <p>
          <Link href="/dev/login">로그인</Link> 하면 볼 수 있을 수도 있습니다.
        </p>
      )}
    </section>
  );
}
