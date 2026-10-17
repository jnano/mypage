"use server";

import type { PreviewResult } from "@/components/admin/blocks/PreviewBlocks";
import { ApiError, type ProblemBody } from "@/lib/api/problem";
import { personalSend } from "@/lib/server/backend";

// 블록 편집기의 서버 함수(홈블록 설계도 §8) — 미리보기는 아무것도 저장하지 않는다(무효화 없음)

export async function previewAction(body: unknown): Promise<{ data?: PreviewResult; problem?: ProblemBody }> {
  try {
    const { data } = await personalSend<PreviewResult>("POST", "/api/admin/blocks/preview", body);
    return { data };
  } catch (e) {
    if (e instanceof ApiError) return { problem: e.problem };
    throw e;
  }
}
