import { AccountBlock } from "./AccountBlock";
import { blockRenderer } from "./blockRenderer";
import { ModuleSlot } from "./ModuleSlot";

// 화면용 블록 렌더러 — 모듈 자리는 등록된 모듈 부품(자기 데이터를 서버에서 부른다), 계정은 쿠키를 보는 기존 부품
const renderer = blockRenderer({
  module: ({ node, level }) => <ModuleSlot data={node.data} level={level} />,
  account: () => <AccountBlock />,
});

export const { RenderBlock, RenderBlocks } = renderer;

/** 백엔드가 그릴 수 있다고 낸 종류(blocks.gen.json 의 examples) = 이 등록부의 종류 — 어긋나면 타입 검사 실패 */
type BackendRenderable = keyof (typeof import("@/lib/blocks/blocks.gen.json"))["examples"];
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
export const _registryMatchesBackend: Same<BackendRenderable, keyof typeof renderer.registry> = true;
