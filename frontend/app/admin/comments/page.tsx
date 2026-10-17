import Link from "next/link";
import { Suspense } from "react";
import { bulkCommentsAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { SelectAll } from "@/components/admin/SelectAll";
import { adminGet, query } from "@/lib/admin/load";
import type { AdminCommentRow, Page } from "@/lib/admin/types";
import { formatDateTime } from "@/lib/format/time";

// 댓글 통합 목록·일괄 가림·삭제(§14.2) — 담당자는 자기 게시판만
export const metadata = { title: "댓글 관리" };

const FILTERS = ["board", "blinded", "author_id", "q"] as const;

export default function AdminCommentsPage(props: PageProps<"/admin/comments">) {
  return (
    <section>
      <h1>댓글 관리</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Comments {...props} />
      </Suspense>
    </section>
  );
}

async function Comments({ searchParams }: PageProps<"/admin/comments">) {
  const sp = await searchParams;
  const params = Object.fromEntries(FILTERS.map((k) => [k, sp[k]])) as Record<string, string | string[] | undefined>;
  const value = (k: string) => (typeof params[k] === "string" ? (params[k] as string) : "");
  const { data, problem } = await adminGet<Page<AdminCommentRow>>(`/api/admin/comments${query({ ...params, cursor: sp.cursor as string })}`);
  if (problem) return <AdminProblem problem={problem} />;
  return (
    <>
      <form method="get" data-slot="filters" aria-label="댓글 거르기">
        <label>
          게시판 주소 <input name="board" defaultValue={value("board")} />
        </label>
        <label>
          가림{" "}
          <select name="blinded" defaultValue={value("blinded")}>
            <option value="">상관없음</option>
            <option value="true">가린 것</option>
            <option value="false">보이는 것</option>
          </select>
        </label>
        <label>
          작성자 번호 <input name="author_id" inputMode="numeric" defaultValue={value("author_id")} />
        </label>
        <label>
          내용 <input name="q" defaultValue={value("q")} />
        </label>
        <button type="submit">거르기</button>
      </form>
      {data.items.length === 0 ? (
        <p data-slot="empty">댓글이 없습니다.</p>
      ) : (
        <AdminForm
          action={bulkCommentsAction}
          submitLabel="고른 댓글에 조치"
          label="댓글 일괄 조치"
          bulk={{
            legend: "조치",
            fields: (
              <>
                <label>
                  조치{" "}
                  <select name="action" defaultValue="blind">
                    <option value="blind">가리기</option>
                    <option value="unblind">가림 풀기</option>
                    <option value="delete" data-danger>
                      삭제
                    </option>
                  </select>
                </label>
                <label>
                  사유 <input name="reason" maxLength={500} />
                </label>
              </>
            ),
          }}
        >
          <table role="table" data-slot="admin-table">
            <caption>댓글(최신순)</caption>
            <thead role="rowgroup">
              <tr role="row">
                <th scope="col" role="columnheader">
                  <SelectAll name="ids" label="이 쪽 모두 고르기" />
                </th>
                <th scope="col" role="columnheader">내용</th>
                <th scope="col" role="columnheader">글</th>
                <th scope="col" role="columnheader">작성자</th>
                <th scope="col" role="columnheader">상태</th>
                <th scope="col" role="columnheader">작성</th>
              </tr>
            </thead>
            <tbody role="rowgroup">
              {data.items.map((c) => (
                <tr role="row" key={c.id}>
                  <td role="cell" data-label="고르기">
                    <input type="checkbox" name="ids" value={c.id} aria-label={`댓글 ${c.id} 고르기`} />
                  </td>
                  <th scope="row" role="rowheader" data-label="내용">{c.content.slice(0, 120)}</th>
                  <td role="cell" data-label="글">
                    <Link href={`/boards/${c.board.slug}/${c.post.id}#c-${c.id}`}>{c.post.title}</Link> ({c.board.name})
                  </td>
                  <td role="cell" data-label="작성자">{c.author.name}</td>
                  <td role="cell" data-label="상태">{c.blinded ? `가림${c.blind_source === "auto_report" ? "(신고 자동)" : ""}` : "보임"}</td>
                  <td role="cell" data-label="작성">{formatDateTime(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </AdminForm>
      )}
      {data.next_cursor !== null && (
        <p data-slot="more">
          <Link href={`/admin/comments${query({ ...params, cursor: String(data.next_cursor) })}`}>더 보기</Link>
        </p>
      )}
    </>
  );
}
