import Link from "next/link";
import { Suspense } from "react";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet, query } from "@/lib/admin/load";
import type { ModerationLogItem, Page } from "@/lib/admin/types";
import { formatDateTime } from "@/lib/format/time";

// 운영 기록(§14.2) — 운영자는 전체, 담당자는 자기 게시판 기록. 행은 지우지 않고, 개인 칸은 작업자가 가린다(§14.4)
export const metadata = { title: "운영 기록" };

const FILTERS = ["actor_id", "action", "target_type", "target_id", "board_id", "since", "until"] as const;
const TARGET_TYPES: [string, string][] = [
  ["", "모두"],
  ["board", "게시판"],
  ["post", "글"],
  ["comment", "댓글"],
  ["report", "신고"],
  ["member", "회원"],
  ["sanction", "제재"],
  ["setting", "설정"],
];

export default function LogsPage(props: PageProps<"/admin/logs">) {
  return (
    <section>
      <h1>운영 기록</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Logs {...props} />
      </Suspense>
    </section>
  );
}

function payload(value: Record<string, unknown> | null): string {
  return value ? JSON.stringify(value) : "";
}

async function Logs({ searchParams }: PageProps<"/admin/logs">) {
  const sp = await searchParams;
  const params = Object.fromEntries(FILTERS.map((k) => [k, sp[k]])) as Record<string, string | string[] | undefined>;
  const { data, problem } = await adminGet<Page<ModerationLogItem>>(`/api/admin/moderation-logs${query({ ...params, cursor: sp.cursor as string })}`);
  if (problem) return <AdminProblem problem={problem} />;
  const value = (k: string) => (typeof params[k] === "string" ? (params[k] as string) : "");
  return (
    <>
      <form method="get" data-slot="filters" aria-label="운영 기록 거르기">
        <label>
          행위자 회원 번호 <input name="actor_id" inputMode="numeric" defaultValue={value("actor_id")} />
        </label>
        <label>
          행동 <input name="action" defaultValue={value("action")} placeholder="post.blind" />
        </label>
        <label>
          대상 종류{" "}
          <select name="target_type" defaultValue={value("target_type")}>
            {TARGET_TYPES.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          대상 번호 <input name="target_id" inputMode="numeric" defaultValue={value("target_id")} />
        </label>
        <label>
          게시판 번호 <input name="board_id" inputMode="numeric" defaultValue={value("board_id")} />
        </label>
        <label>
          시작 <input type="date" name="since" defaultValue={value("since")} />
        </label>
        <label>
          끝(그날 전까지) <input type="date" name="until" defaultValue={value("until")} />
        </label>
        <button type="submit">거르기</button>
      </form>
      {data.items.length === 0 ? (
        <p data-slot="empty">기록이 없습니다.</p>
      ) : (
        <table data-slot="admin-table">
          <caption>운영 기록(최신순)</caption>
          <thead>
            <tr>
              <th scope="col">시각</th>
              <th scope="col">행위자</th>
              <th scope="col">게시판</th>
              <th scope="col">행동</th>
              <th scope="col">대상</th>
              <th scope="col">바뀐 칸</th>
              <th scope="col">사유</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((log) => (
              <tr key={log.id} data-redacted={log.redacted || undefined}>
                <td>{formatDateTime(log.created_at)}</td>
                <td>{log.actor.name ?? (log.actor.id ? `#${log.actor.id}` : "작업자")}</td>
                <td>{log.board?.slug ?? ""}</td>
                <td>{log.action}</td>
                <td>
                  {log.target.type} #{log.target.id}
                </td>
                <td>
                  {log.before || log.after ? (
                    <>
                      <code>{payload(log.before)}</code> → <code>{payload(log.after)}</code>
                    </>
                  ) : null}
                </td>
                <td>{log.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data.next_cursor !== null && (
        <p>
          <Link href={`/admin/logs${query({ ...params, cursor: String(data.next_cursor) })}`}>더 보기</Link>
        </p>
      )}
    </>
  );
}
