import Link from "next/link";
import { Suspense } from "react";
import {
  accessAction,
  createCategoryAction,
  deleteBoardAction,
  deleteCategoryAction,
  emptyBoardAction,
  mergeCategoryAction,
  moderatorsAction,
  moveCategoryAction,
  updateBoardAction,
  updateCategoryAction,
} from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { PageToc } from "@/components/admin/PageToc";
import { SettingField as Field } from "@/components/admin/SettingField";
import { BOARD_SECTIONS, fieldValue } from "@/lib/admin/boardFields";
import { adminGet, query } from "@/lib/admin/load";
import type { AdminBoardDetail, AdminBoards, PermissionPreview } from "@/lib/admin/types";

// 게시판 설정(§14.2) — 구역별 저장(바뀐 칸만 운영 기록), 카테고리, 명부·담당자, 권한 미리보기, 비우기·삭제. 운영자 전용
export const metadata = { title: "게시판 설정" };

export default function AdminBoardPage(props: PageProps<"/admin/boards/[slug]">) {
  return (
    <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
      <BoardSettings {...props} />
    </Suspense>
  );
}

async function BoardSettings({ params, searchParams }: PageProps<"/admin/boards/[slug]">) {
  const { slug } = await params;
  const sp = await searchParams;
  const previewQuery = query({ level: sp.level as string, member_id: sp.member_id as string });
  const [detail, list, preview] = await Promise.all([
    adminGet<AdminBoardDetail>(`/api/boards/${encodeURIComponent(slug)}`),
    adminGet<AdminBoards>("/api/admin/boards"),
    previewQuery ? adminGet<PermissionPreview>(`/api/admin/boards/${encodeURIComponent(slug)}/permission-preview${previewQuery}`) : null,
  ]);
  if (detail.problem) return <AdminProblem problem={detail.problem} />;
  const { board, categories, entries, moderators } = detail.data;
  const groupOptions: [string, string][] = [["", "분류 없음"], ...(list.data?.groups ?? []).map((g): [string, string] => [String(g.id), g.name])];
  const categoryOrder = categories.map((c) => c.id);

  return (
    <section>
      <h1>
        {board.name} <code>{board.slug}</code>
      </h1>
      <p>
        <Link href={`/boards/${board.slug}`}>게시판 보기</Link> · <Link href="/admin/boards">게시판 목록</Link>
      </p>
      <PageToc
        items={[
          ...BOARD_SECTIONS.map((s) => ({ id: `s-${s.id}`, label: s.title })),
          { id: "categories", label: "카테고리" },
          { id: "access", label: "명부와 담당자" },
          { id: "permission-preview", label: "권한 미리보기" },
          ...(board.is_system ? [] : [{ id: "danger-zone", label: "비우기·삭제", danger: true }]),
        ]}
      />

      {BOARD_SECTIONS.map((section) => (
        <AdminForm
          key={section.id}
          id={`s-${section.id}`}
          action={updateBoardAction.bind(null, board.slug, section.id)}
          submitLabel={`${section.title} 저장`}
          label={section.title}
        >
          <fieldset>
            <legend>{section.title}</legend>
            {section.fields.map((field) =>
              field.name === "slug" && board.is_system ? null : (
                <Field key={field.name} field={field} value={fieldValue(board, field)} options={field.name === "group_id" ? groupOptions : undefined} />
              ),
            )}
            <p>
              <label>
                사유(운영 기록) <input name="reason" maxLength={500} />
              </label>
            </p>
          </fieldset>
        </AdminForm>
      ))}

      <h2 id="categories">카테고리</h2>
      <p>지우기는 글이 없는 카테고리만 됩니다. 글이 있으면 다른 카테고리로 병합하세요.</p>
      <ol>
        {categories.map((c, i) => (
          <li key={c.id} data-inactive={!c.is_active || undefined}>
            <AdminForm action={updateCategoryAction.bind(null, c.id)} submitLabel="고치기" label={`${c.name} 고치기`}>
              <input name="name" defaultValue={c.name} maxLength={50} required aria-label="카테고리 이름" />
              <label>
                <input type="checkbox" name="is_active" defaultChecked={c.is_active} /> 사용
              </label>{" "}
              <span>글 {c.posts}</span>
            </AdminForm>
            {i > 0 && <AdminForm action={moveCategoryAction.bind(null, board.slug, categoryOrder, c.id, -1)} submitLabel="위로" label={`${c.name} 위로`} />}
            {categories.length > 1 && (
              <AdminForm action={mergeCategoryAction.bind(null, c.id)} submitLabel="병합" label={`${c.name} 병합`}>
                <select name="into" aria-label="병합할 카테고리">
                  {categories
                    .filter((o) => o.id !== c.id)
                    .map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name}(으)로
                      </option>
                    ))}
                </select>
              </AdminForm>
            )}
            {c.posts === 0 && <AdminForm action={deleteCategoryAction.bind(null, c.id)} submitLabel="지우기" label={`${c.name} 지우기`} danger />}
          </li>
        ))}
      </ol>
      <AdminForm action={createCategoryAction.bind(null, board.slug)} submitLabel="카테고리 더하기" label="새 카테고리">
        <input name="name" maxLength={50} required aria-label="새 카테고리 이름" />
      </AdminForm>

      <h2 id="access">명부와 담당자</h2>
      <AdminForm action={accessAction.bind(null, board.slug)} submitLabel="명부 저장" label="명부">
        <label htmlFor="access-entries">명부 — 등급이 모자라도 허용. 줄마다 &quot;member 회원번호 rw&quot; 또는 &quot;group 그룹번호 r&quot;(r 읽기, w 쓰기)</label>
        <textarea
          id="access-entries"
          name="entries"
          rows={4}
          defaultValue={entries.map((e) => `${e.subject_type} ${e.subject_id} ${e.can_read ? "r" : ""}${e.can_write ? "w" : ""}`).join("\n")}
        />
      </AdminForm>
      <AdminForm action={moderatorsAction.bind(null, board.slug)} submitLabel="담당자 저장" label="담당자">
        <label>
          담당자 회원 번호(쉼표로 나눔) <input name="member_ids" defaultValue={moderators.map((m) => m.id).join(", ")} />
        </label>{" "}
        <span>지금: {moderators.length ? moderators.map((m) => `${m.name}(#${m.id})`).join(", ") : "없음"}</span>
      </AdminForm>

      <h2 id="permission-preview">권한 미리보기</h2>
      <form method="get" aria-label="권한 미리보기">
        <label>
          등급 <input name="level" inputMode="numeric" defaultValue={(sp.level as string) ?? ""} />
        </label>{" "}
        또는{" "}
        <label>
          회원 번호 <input name="member_id" inputMode="numeric" defaultValue={(sp.member_id as string) ?? ""} />
        </label>{" "}
        <button type="submit">보기</button>
      </form>
      {preview?.problem && <AdminProblem problem={preview.problem} />}
      {preview?.data && (
        <table data-slot="admin-table">
          <caption>
            {preview.data.subject.member_id ? `회원 #${preview.data.subject.member_id}` : `등급 ${preview.data.subject.level}`}
            {preview.data.role.is_moderator ? " · 담당자" : ""}
            {preview.data.role.listed_read || preview.data.role.listed_write ? " · 명부" : ""}
          </caption>
          <tbody>
            {preview.data.actions.map((a) => (
              <tr key={a.action}>
                <th scope="row">{a.label}</th>
                <td>{a.allowed ? "허용" : "거부"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!board.is_system && (
        <section id="danger-zone" aria-labelledby="danger-zone-heading" data-slot="danger-zone">
          <h2 id="danger-zone-heading">비우기·삭제</h2>
          <p>되돌릴 수 없습니다. 실행 전에 한 번 더 묻습니다.</p>
          <AdminForm action={emptyBoardAction.bind(null, board.slug)} submitLabel="게시판 비우기(모든 글 영구 삭제)" label="게시판 비우기" danger>
            <label>
              확인: 주소 <code>{board.slug}</code> 를 적으세요 <input name="confirm" autoComplete="off" />
            </label>
            <label>
              사유 <input name="reason" maxLength={500} />
            </label>
          </AdminForm>
          <AdminForm action={deleteBoardAction.bind(null, board.slug)} submitLabel="게시판 삭제(글 0건일 때만)" label="게시판 삭제" danger>
            <label>
              확인: 주소 <code>{board.slug}</code> 를 적으세요 <input name="confirm" autoComplete="off" />
            </label>
          </AdminForm>
        </section>
      )}
    </section>
  );
}
