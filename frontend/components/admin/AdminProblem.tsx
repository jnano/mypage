import Link from "next/link";
import type { ProblemBody } from "@/lib/api/problem";

// 관리 화면 오류 — 로그인 전이면 로그인으로, 권한이 없으면 그 사실만 알린다
export function AdminProblem({ problem }: { problem: ProblemBody }) {
  return (
    <section data-slot="error" data-status={problem.status} role="alert">
      <h2>{problem.title}</h2>
      {problem.status === 401 && (
        <p>
          <Link href="/dev/login">로그인</Link> 한 뒤 다시 시도해 주세요.
        </p>
      )}
    </section>
  );
}
