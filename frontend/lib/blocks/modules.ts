import type { ModuleSlotData } from "./types";

// 모듈 키(홈블록 설계도 §3.4) — 백엔드 app/blocks/modules.py 의 MODULES 와 같아야 한다. 부품 등록부는
// components/blocks/ModuleSlot.tsx 의 MODULE_REGISTRY(빠진 키는 타입 검사가 잡는다)

export type ModuleKey = ModuleSlotData["module"];

/** 백엔드 등록부(blocks.gen.json 의 modules) = 프런트 모듈 형식 — 어긋나면 타입 검사 실패 */
type BackendModule = keyof (typeof import("./blocks.gen.json"))["modules"];
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
export const _modulesMatchBackend: Same<BackendModule, ModuleKey> = true;
