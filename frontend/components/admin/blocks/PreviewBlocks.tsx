"use client";

import { blockRenderer } from "@/components/blocks/blockRenderer";
import { visibleNodes } from "@/lib/blocks/frame";
import type { FrameNode } from "@/lib/blocks/types";

// 편집기 미리보기(홈블록 설계도 §8) — POST /api/admin/blocks/preview 결과를 실제 블록 부품으로 브라우저에서 그린다.
// 서버에서만 그릴 수 있는 둘(게시판 모듈 — 자기 데이터를 서버에서 부른다, 계정 — 쿠키를 읽는다)은 자리 표시.
// 영역은 랜드마크 요소가 아니라 묶음으로 그린다 — 관리 화면 안에 header·footer 랜드마크가 하나 더 생기지 않게(§10)

const { RenderBlocks } = blockRenderer({
  module: ({ node }) => (
    <p data-slot="module-placeholder">
      게시판 모듈 — {node.data.board.slug} 게시판의 첫 쪽 글 {node.data.params.count}개와 &lsquo;더 보기&rsquo;(화면에서 그려집니다)
    </p>
  ),
  account: () => <p data-slot="account-placeholder">계정 표시(로그인 · 내 정보)</p>,
});

export interface PreviewResult {
  regions: Partial<Record<string, FrameNode[]>>;
  blocks: FrameNode[];
  personal_block_ids: number[];
}

const REGION_NAMES: Record<string, string> = { header: "머리", nav: "메뉴 줄", top: "본문 위", aside: "옆", bottom: "본문 아래", footer: "바닥" };

export function PreviewBlocks({ result, asMember, regions }: { result: PreviewResult; asMember: boolean; regions: string[] | null }) {
  const hidden = result.personal_block_ids.length;
  return (
    <div data-slot="block-preview">
      {!asMember && hidden > 0 && <p data-slot="preview-note">회원에게만 보이는 블록 {hidden}개는 비회원 모습에서 빠집니다.</p>}
      {regions ? (
        regions.map((r) => (
          <div key={r} data-slot="preview-region" data-region={r}>
            <p data-slot="preview-region-name">{REGION_NAMES[r] ?? r}</p>
            <RenderBlocks nodes={visibleNodes(result.regions[r], asMember)} />
            {r === "top" && <p data-slot="preview-outlet">— 본문 자리(게시판·페이지 내용) —</p>}
          </div>
        ))
      ) : (
        <RenderBlocks nodes={visibleNodes(result.blocks, asMember)} />
      )}
    </div>
  );
}
