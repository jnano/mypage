import Link from "next/link";
import { Suspense } from "react";
import { bootstrapLayoutAction, createLayoutAction, deleteLayoutAction, saveBindingsAction, setDefaultLayoutAction } from "@/app/admin/blockActions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { adminGet } from "@/lib/admin/load";
import { formatDateTime } from "@/lib/format/time";

// 틀 목록(홈블록 설계도 §8) — 기본 틀·화면 종류별 틀·'기본 틀 만들기'(§3.6)·만들기·지우기. 운영자 전용(site.design)
export const metadata = { title: "틀" };

interface LayoutRow {
  id: number;
  name: string;
  is_default: boolean;
  version: number;
  updated_at: string;
  blocks: number;
  boards: number;
  pages: number;
}

const ROUTE_LABELS: Record<string, string> = { board: "게시판 화면", search: "검색 화면", member: "내 정보 화면", auth: "로그인·가입 화면" };

export default function AdminLayoutsPage() {
  return (
    <section>
      <h1>틀</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Layouts />
      </Suspense>
    </section>
  );
}

async function Layouts() {
  const { data, problem } = await adminGet<{ layouts: LayoutRow[]; bindings: Record<string, number | null> }>("/api/admin/layouts");
  if (problem) return <AdminProblem problem={problem} />;
  const hasDefault = data.layouts.some((l) => l.is_default);
  const classes = Object.keys(data.bindings);
  return (
    <>
      {!hasDefault && (
        <section aria-labelledby="bootstrap-heading" data-slot="notice">
          <h2 id="bootstrap-heading">기본 틀이 없습니다</h2>
          <p>지금은 사이트가 코드에 들어 있는 대체 틀로 그려집니다. 같은 모습의 기본 틀(머리·주 메뉴·검색·계정·바닥)과 주 메뉴를 만들어 고칠 수 있게 합니다.</p>
          <AdminForm action={bootstrapLayoutAction} submitLabel="기본 틀 만들기" />
        </section>
      )}
      {data.layouts.length === 0 ? (
        <p data-slot="empty">틀이 없습니다.</p>
      ) : (
        <table data-slot="admin-table">
          <caption>틀 목록</caption>
          <thead>
            <tr>
              <th scope="col">이름</th>
              <th scope="col">블록</th>
              <th scope="col">쓰는 곳</th>
              <th scope="col">고친 때</th>
              <th scope="col">기본</th>
              <th scope="col">지우기</th>
            </tr>
          </thead>
          <tbody>
            {data.layouts.map((l) => (
              <tr key={l.id}>
                <th scope="row">
                  <Link href={`/admin/layouts/${l.id}`}>{l.name}</Link>
                </th>
                <td>{l.blocks}</td>
                <td>
                  게시판 {l.boards} · 페이지 {l.pages}
                  {classes.filter((c) => data.bindings[c] === l.id).map((c) => ` · ${ROUTE_LABELS[c] ?? c}`)}
                </td>
                <td>{formatDateTime(l.updated_at)}</td>
                <td>{l.is_default ? "기본 틀" : "—"}</td>
                <td>
                  {l.is_default ? (
                    "—"
                  ) : (
                    <AdminForm action={deleteLayoutAction.bind(null, l.id)} submitLabel="지우기" label={`${l.name} 지우기`} danger />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {data.layouts.length > 1 && (
        <>
          <h2>기본 틀 바꾸기</h2>
          <p>틀을 고르지 않은 게시판·페이지·화면이 모두 바뀝니다. 바꾼 뒤 확인할 것이 있으면 여기에 남습니다.</p>
          {/* 표 안의 줄마다 두면 바뀐 줄의 폼이 사라져 경고 문구도 사라진다 — 폼 하나로(코드 검토 v11 N-2 의 경고를 보이게) */}
          <AdminForm action={setDefaultLayoutAction} submitLabel="기본으로 정하기" label="기본 틀 바꾸기">
            <label>
              틀{" "}
              <select name="layout_id" required defaultValue="">
                <option value="">고르세요</option>
                {data.layouts
                  .filter((l) => !l.is_default)
                  .map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
              </select>
            </label>
          </AdminForm>
        </>
      )}

      <h2>화면 종류별 틀</h2>
      <p>고르지 않으면 기본 틀을 씁니다. 게시판마다 고른 틀(게시판 설정)이 이보다 먼저입니다.</p>
      <AdminForm action={saveBindingsAction.bind(null, classes)} submitLabel="저장" label="화면 종류별 틀">
        {classes.map((c) => (
          <label key={c}>
            {ROUTE_LABELS[c] ?? c}{" "}
            <select name={c} defaultValue={data.bindings[c] ?? ""}>
              <option value="">기본 틀</option>
              {data.layouts.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </label>
        ))}
      </AdminForm>

      <h2>새 틀</h2>
      <AdminForm action={createLayoutAction} submitLabel="만들기" label="새 틀">
        <label>
          이름 <input name="name" required maxLength={50} />
        </label>
      </AdminForm>
    </>
  );
}
