import { Suspense, type ReactNode } from "react";
import type { ModuleKey } from "@/lib/blocks/modules";
import type { ModuleSlotData } from "@/lib/blocks/types";
import { BoardModule } from "@/components/modules/BoardModule";

// 모듈 자리(홈블록 설계도 §3.4) — 등록된 모듈 부품을 끼운다. 부품은 자기 데이터를 자기 API·캐시 태그로 부르고,
// 보는 사람에 따라 달라지는 부분(쿠키)을 읽으므로 자리마다 Suspense 로 감싼다(틀·페이지 나머지는 먼저 그린다)

type ModuleProps<K extends ModuleKey> = { data: Extract<ModuleSlotData, { module: K }>; level: number };

const MODULE_REGISTRY = {
  board: ({ data, level }) => <BoardModule data={data} level={level} />,
} satisfies { [K in ModuleKey]: (props: ModuleProps<K>) => ReactNode };

export function ModuleSlot({ data, level }: { data: ModuleSlotData; level: number }) {
  const Part = MODULE_REGISTRY[data.module] as (props: { data: ModuleSlotData; level: number }) => ReactNode;
  return (
    <div data-slot="module-slot" data-module={data.module}>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Part data={data} level={level} />
      </Suspense>
    </div>
  );
}
