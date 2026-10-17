import Link from "next/link";
import { Suspense } from "react";
import { bulkPostsAction, pinnedOrderAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { SelectAll } from "@/components/admin/SelectAll";
import { adminGet, query } from "@/lib/admin/load";
import type { AdminPostRow, AdminSummary, Page } from "@/lib/admin/types";
import { formatDateTime } from "@/lib/format/time";

// 글 통합 목록·일괄 조치(§14.2) — 담당자는 자기 게시판만. 조치는 최대 100건, 하나라도 권한이 없으면 아무것도 바꾸지 않는다
export const metadata = { title: "글 관리" };

const FILTERS = ["board", "status", "blinded", "secret", "reported", "pinned", "author_id", "q", "since", "until"] as const;
const STATUSES: [string, string][] = [
  ["all", "모든 상태"],
  ["published", "발행"],
  ["scheduled", "예약"],
  ["pending", "승인 대기"],
  ["draft", "임시"],
  ["trashed", "휴지통"],
];
const ACTIONS: [string, string][] = [
  ["trash", "휴지통으로"],
  ["restore", "휴지통에서 복원"],
  ["purge", "영구 삭제(휴지통 글만)"],
  ["pin", "고정"],
  ["unpin", "고정 해제"],
  ["blind", "가리기"],
  ["unblind", "가림 풀기"],
  ["move", "다른 게시판으로 옮기기"],
  ["copy", "다른 게시판으로 복사(첨부 제외)"],
  ["category", "카테고리 바꾸기"],
  ["view_level", "열람 등급 정하기"],
  ["publish_now", "지금 발행(예약·임시·승인 대기)"],
];
const STATUS_LABEL = Object.fromEntries(STATUSES);
// 되돌릴 수 없는 조치 — 고르면 제출 전에 확인 대화(AdminForm), 단추는 위험 모양(lists.css)
const DANGER_ACTIONS = new Set(["purge"]);

export default function AdminPostsPage(props: PageProps<"/admin/posts">) {
  return (
    <section>
      <h1>글 관리</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Posts {...props} />
      </Suspense>
    </section>
  );
}

function Tristate({ name, label, value }: { name: string; label: string; value: string }) {
  return (
    <label>
      {label}{" "}
      <select name={name} defaultValue={value}>
        <option value="">상관없음</option>
        <option value="true">예</option>
        <option value="false">아니오</option>
      </select>
    </label>
  );
}

async function Posts({ searchParams }: PageProps<"/admin/posts">) {
  const sp = await searchParams;
  const params = Object.fromEntries(FILTERS.map((k) => [k, sp[k]])) as Record<string, string | string[] | undefined>;
  const value = (k: string) => (typeof params[k] === "string" ? (params[k] as string) : "");
  const [list, summary] = await Promise.all([
    adminGet<Page<AdminPostRow>>(`/api/admin/posts${query({ ...params, cursor: sp.cursor as string })}`),
    adminGet<AdminSummary>("/api/admin/summary"),
  ]);
  if (list.problem) return <AdminProblem problem={list.problem} />;
  const boards = summary.data?.boards ?? [];
  const pinnedBoard = value("board") && value("pinned") === "true" ? value("board") : null;
  const pinnedOrder = pinnedBoard ? [...list.data.items].sort((a, b) => (a.flags.pin_order ?? 0) - (b.flags.pin_order ?? 0)) : [];

  return (
    <>
      <p>
        <Link href="/admin/posts?status=trashed">휴지통</Link> · <Link href="/admin/posts?status=scheduled">예약 발행</Link> ·{" "}
        <Link href="/admin/pending">승인 대기</Link> · <Link href="/admin/posts?reported=true">신고된 글</Link>
      </p>
      <form method="get" data-slot="filters" aria-label="글 거르기">
        <label>
          게시판{" "}
          <select name="board" defaultValue={value("board")}>
            <option value="">모두</option>
            {boards.map((b) => (
              <option key={b.id} value={b.slug}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          상태{" "}
          <select name="status" defaultValue={value("status") || "all"}>
            {STATUSES.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <Tristate name="blinded" label="가림" value={value("blinded")} />
        <Tristate name="secret" label="비밀" value={value("secret")} />
        <Tristate name="reported" label="신고 대기" value={value("reported")} />
        <Tristate name="pinned" label="고정" value={value("pinned")} />
        <label>
          작성자 번호 <input name="author_id" inputMode="numeric" defaultValue={value("author_id")} />
        </label>
        <label>
          제목 <input name="q" defaultValue={value("q")} />
        </label>
        <label>
          작성일 시작 <input type="date" name="since" defaultValue={value("since")} />
        </label>
        <label>
          끝(그날 전까지) <input type="date" name="until" defaultValue={value("until")} />
        </label>
        <button type="submit">거르기</button>
      </form>

      {list.data.items.length === 0 ? (
        <p data-slot="empty">글이 없습니다.</p>
      ) : (
        <AdminForm
          action={bulkPostsAction}
          submitLabel="고른 글에 조치"
          label="일괄 조치"
          bulk={{
            legend: "조치",
            fields: (
              <>
                <label>
                  조치{" "}
                  <select name="action" defaultValue="trash">
                    {ACTIONS.map(([v, label]) => (
                      <option key={v} value={v} data-danger={DANGER_ACTIONS.has(v) || undefined}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label data-action-field="move copy">
                  옮길·복사할 게시판{" "}
                  <select name="board_id" defaultValue="">
                    <option value="">—</option>
                    {boards.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label data-action-field="category">
                  카테고리 번호(쉼표, 비우면 뗌) <input name="category_ids" />
                </label>
                <label data-action-field="view_level">
                  열람 등급(1~99, 비우면 해제) <input name="min_view_level" inputMode="numeric" />
                </label>
                <label>
                  사유 <input name="reason" maxLength={500} />
                </label>
              </>
            ),
          }}
        >
          <table role="table" data-slot="admin-table">
            <caption>글(최신순) — 조치할 글을 고르세요</caption>
            <thead role="rowgroup">
              <tr role="row">
                <th scope="col" role="columnheader">
                  <SelectAll name="ids" label="이 쪽 모두 고르기" />
                </th>
                <th scope="col" role="columnheader">제목</th>
                <th scope="col" role="columnheader">게시판</th>
                <th scope="col" role="columnheader">작성자</th>
                <th scope="col" role="columnheader">상태</th>
                <th scope="col" role="columnheader">표시</th>
                <th scope="col" role="columnheader">댓글·조회·신고</th>
                <th scope="col" role="columnheader">작성</th>
              </tr>
            </thead>
            <tbody role="rowgroup">
              {list.data.items.map((p) => (
                <tr role="row" key={p.id}>
                  <td role="cell" data-label="고르기">
                    <input type="checkbox" name="ids" value={p.id} aria-label={`${p.title} 고르기`} />
                  </td>
                  <th scope="row" role="rowheader" data-label="제목">
                    <Link href={`/boards/${p.board.slug}/${p.id}`}>{p.title}</Link>
                  </th>
                  <td role="cell" data-label="게시판">{p.board.name}</td>
                  <td role="cell" data-label="작성자">
                    {p.author.name}
                    {p.author.guest ? "(비회원)" : ""}
                  </td>
                  <td role="cell" data-label="상태">
                    {STATUS_LABEL[p.status] ?? p.status}
                    {p.trash && ` · ${formatDateTime(p.trash.trashed_at)} 이동${p.trash.purge_at ? `, ${formatDateTime(p.trash.purge_at)} 자동 정리` : ""}`}
                    {p.status === "scheduled" && ` · ${formatDateTime(p.published_at)} 발행 예정`}
                  </td>
                  <td role="cell" data-label="표시">
                    {[
                      p.flags.pinned && `고정 ${p.flags.pin_order ?? ""}`,
                      p.flags.blinded && "가림",
                      p.flags.secret && "비밀",
                      p.flags.min_view_level && `등급 ${p.flags.min_view_level}+`,
                      p.flags.posted_as === "admin" && "운영자 명의",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </td>
                  <td role="cell" data-label="댓글·조회·신고">
                    {p.comments} · {p.views} · {p.reports}
                  </td>
                  <td role="cell" data-label="작성">{formatDateTime(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </AdminForm>
      )}
      {list.data.next_cursor !== null && (
        <p data-slot="more">
          <Link href={`/admin/posts${query({ ...params, cursor: String(list.data.next_cursor) })}`}>더 보기</Link>
        </p>
      )}

      {pinnedBoard && pinnedOrder.length > 1 && (
        <>
          <h2>고정 글 순서</h2>
          <ol>
            {pinnedOrder.map((p, i) => (
              <li key={p.id}>
                {p.title}{" "}
                {i > 0 && (
                  <AdminForm
                    action={pinnedOrderAction.bind(null, pinnedBoard, pinnedOrder.map((x) => x.id), p.id, -1)}
                    submitLabel="위로"
                    label={`${p.title} 위로`}
                  />
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </>
  );
}
