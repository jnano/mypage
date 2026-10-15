import Link from "next/link";
import { Suspense } from "react";
import {
  createBoardAction,
  createGroupAction,
  deleteGroupAction,
  moveBoardAction,
  moveGroupAction,
  renameGroupAction,
} from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import type { AdminBoards } from "@/lib/admin/types";
import { formatDateTime } from "@/lib/format/time";

// 게시판 관리 목록(§14.2) — 분류 그룹별·글 수·최근 글·승인 대기·신고 대기, 만들기, 순서, 분류 그룹. 운영자 전용
export const metadata = { title: "게시판 관리" };

export default function AdminBoardsPage() {
  return (
    <section>
      <h1>게시판</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Boards />
      </Suspense>
    </section>
  );
}

async function Boards() {
  const { data, problem } = await adminGet<AdminBoards>("/api/admin/boards");
  if (problem) return <AdminProblem problem={problem} />;
  const order = data.boards.map((b) => b.id);
  const groupOrder = data.groups.map((g) => g.id);
  return (
    <>
      <table data-slot="admin-table">
        <caption>게시판 목록(메뉴 순서)</caption>
        <thead>
          <tr>
            <th scope="col">분류</th>
            <th scope="col">이름</th>
            <th scope="col">형식</th>
            <th scope="col">글</th>
            <th scope="col">최근 글</th>
            <th scope="col">승인 대기</th>
            <th scope="col">신고 대기</th>
            <th scope="col">상태</th>
            <th scope="col">순서</th>
          </tr>
        </thead>
        <tbody>
          {data.boards.map((b, i) => (
            <tr key={b.id} data-inactive={!b.is_active || undefined}>
              <td>{b.group?.name ?? "—"}</td>
              <th scope="row">
                <Link href={`/admin/boards/${b.slug}`}>{b.name}</Link> <code>{b.slug}</code>
              </th>
              <td>
                {b.kind} · {b.editor === "rich" ? "리치" : "마크다운"}
              </td>
              <td>{b.posts}</td>
              <td>{formatDateTime(b.last_post_at)}</td>
              <td>{b.pending}</td>
              <td>{b.reports}</td>
              <td>
                {[b.is_active ? "사용" : "중지", b.show_in_menu ? "메뉴" : "메뉴 숨김", b.is_system ? "시스템" : ""].filter(Boolean).join(" · ")}
              </td>
              <td>
                <AdminForm action={moveBoardAction.bind(null, order, b.id, -1)} submitLabel="위로" label={`${b.name} 위로`} />
                {i < data.boards.length - 1 && <AdminForm action={moveBoardAction.bind(null, order, b.id, 1)} submitLabel="아래로" label={`${b.name} 아래로`} />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>새 게시판</h2>
      <AdminForm action={createBoardAction} submitLabel="만들기" label="새 게시판">
        <label>
          이름 <input name="name" required maxLength={100} />
        </label>
        <label>
          주소(slug) <input name="slug" required maxLength={100} pattern="[a-z0-9][a-z0-9\-]*" />
        </label>
        <label>
          형식 견본{" "}
          <select name="template" defaultValue="default">
            {data.templates.map((t) => (
              <option key={t.name} value={t.name}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          또는 설정 복사{" "}
          <select name="copy_from" defaultValue="">
            <option value="">복사 안 함</option>
            {data.boards.map((b) => (
              <option key={b.id} value={b.slug}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
      </AdminForm>

      <h2>분류 그룹</h2>
      <ul>
        {data.groups.map((g, i) => (
          <li key={g.id}>
            <AdminForm action={renameGroupAction.bind(null, g.id)} submitLabel="이름 바꾸기" label={`${g.name} 이름`}>
              <input name="name" defaultValue={g.name} maxLength={50} required aria-label="그룹 이름" />
            </AdminForm>
            {i > 0 && <AdminForm action={moveGroupAction.bind(null, groupOrder, g.id, -1)} submitLabel="위로" label={`${g.name} 위로`} />}
            <AdminForm action={deleteGroupAction.bind(null, g.id)} submitLabel="지우기" label={`${g.name} 지우기`} danger />
          </li>
        ))}
      </ul>
      <AdminForm action={createGroupAction} submitLabel="그룹 더하기" label="새 분류 그룹">
        <input name="name" maxLength={50} required aria-label="새 그룹 이름" />
      </AdminForm>
    </>
  );
}
