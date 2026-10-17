import Link from "next/link";
import { Suspense } from "react";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet, query } from "@/lib/admin/load";
import type { ModerationLogItem, Page } from "@/lib/admin/types";
import { formatDateTime } from "@/lib/format/time";

// 운영 기록(§14.2) — 운영자는 전체, 담당자는 자기 게시판 기록. 행은 지우지 않고, 개인 칸은 작업자가 가린다(§14.4)
export const metadata = { title: "운영 기록" };

const FILTERS = ["actor_id", "action", "target_type", "target_id", "board_id", "since", "until"] as const;
// 대상 종류의 이름표 — 백엔드 MODERATION_TARGET_TYPES(생성 파일 enums.gen.json)를 빠짐없이 덮어야 한다. 종류가 늘고 이름표를
// 빠뜨리면 satisfies 가 타입 검사에서 잡는다(손으로 따로 적은 두 목록이 어긋나 group 이 빠졌던 일 — 통합 설계도 D-712)
type TargetType = keyof (typeof import("@/lib/admin/enums.gen.json"))["moderationTargetTypes"];
const TARGET_LABELS = {
  board: "게시판",
  post: "글",
  comment: "댓글",
  report: "신고",
  member: "회원",
  sanction: "제재",
  setting: "설정",
  group: "그룹",
  layout: "틀",
  page: "페이지",
  menu: "메뉴",
} satisfies Record<TargetType, string>;
const TARGET_TYPES: [string, string][] = [["", "모두"], ...Object.entries(TARGET_LABELS)];

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
        <table role="table" data-slot="admin-table">
          <caption>운영 기록(최신순)</caption>
          <thead role="rowgroup">
            <tr role="row">
              <th scope="col" role="columnheader">시각</th>
              <th scope="col" role="columnheader">행위자</th>
              <th scope="col" role="columnheader">게시판</th>
              <th scope="col" role="columnheader">행동</th>
              <th scope="col" role="columnheader">대상</th>
              <th scope="col" role="columnheader">바뀐 칸</th>
              <th scope="col" role="columnheader">사유</th>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {data.items.map((log) => (
              <tr role="row" key={log.id} data-redacted={log.redacted || undefined}>
                <td role="cell" data-label="시각">{formatDateTime(log.created_at)}</td>
                <td role="cell" data-label="행위자">{log.actor.name ?? (log.actor.id ? `#${log.actor.id}` : "작업자")}</td>
                <td role="cell" data-label="게시판">{log.board?.slug ?? ""}</td>
                <td role="cell" data-label="행동">{log.action}</td>
                <td role="cell" data-label="대상">
                  {log.target.type} #{log.target.id}
                </td>
                <td role="cell" data-label="바뀐 칸">
                  {log.before || log.after ? (
                    <>
                      <code>{payload(log.before)}</code> → <code>{payload(log.after)}</code>
                    </>
                  ) : null}
                </td>
                <td role="cell" data-label="사유">{log.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data.next_cursor !== null && (
        <p data-slot="more">
          <Link href={`/admin/logs${query({ ...params, cursor: String(data.next_cursor) })}`}>더 보기</Link>
        </p>
      )}
    </>
  );
}
