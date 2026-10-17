import "server-only";
import type { EditorOptions } from "@/components/admin/blocks/ConfigForm";
import type { ProblemBody } from "@/lib/api/problem";
import { adminGet } from "@/lib/admin/load";
import type { AdminBoards } from "@/lib/admin/types";
import type { BlockTypes } from "./schema";

// 블록 편집기의 재료(홈블록 설계도 §8) — 블록 종류(폼 형식)와 고르기 선택지(게시판·페이지·메뉴·틀). 관리 화면은 요청 시점
// 개인 데이터라 캐시하지 않는다(편집 중에 다른 운영자가 만든 메뉴도 바로 고를 수 있게). 동시에 부른다

export interface LayoutSummary {
  id: number;
  name: string;
  is_default: boolean;
}

export interface EditorMaterials {
  types: BlockTypes;
  options: EditorOptions;
  layouts: LayoutSummary[];
}

export async function loadEditorMaterials(): Promise<{ data: EditorMaterials; problem?: undefined } | { data?: undefined; problem: ProblemBody }> {
  const [types, boards, pages, menus, layouts] = await Promise.all([
    adminGet<BlockTypes>("/api/admin/block-types"),
    adminGet<AdminBoards>("/api/admin/boards"),
    adminGet<{ pages: { id: number; path: string; title: string }[] }>("/api/admin/pages"),
    adminGet<{ menus: { id: number; name: string }[] }>("/api/admin/menus"),
    adminGet<{ layouts: LayoutSummary[] }>("/api/admin/layouts"),
  ]);
  for (const r of [types, boards, pages, menus, layouts]) if (r.problem) return { problem: r.problem };
  return {
    data: {
      types: types.data!,
      options: {
        boards: boards.data!.boards.map((b) => ({ id: b.id, name: b.name })),
        pages: pages.data!.pages.map((p) => ({ id: p.id, path: p.path, title: p.title })),
        menus: menus.data!.menus.map((m) => ({ id: m.id, name: m.name })),
        modules: types.data!.modules,
      },
      layouts: layouts.data!.layouts.map((l) => ({ id: l.id, name: l.name, is_default: l.is_default })),
    },
  };
}
