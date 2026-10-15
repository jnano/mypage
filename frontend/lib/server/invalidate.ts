import "server-only";
import { revalidateTag, updateTag } from "next/cache";
import type { Invalidation } from "@/lib/boards/types";

/**
 * FastAPI 쓰기 응답의 무효화 태그를 적용한다 — Server Action 안에서만(§3.4).
 * 태그 결정은 FastAPI 무효화 표 한 곳. 여기서는 방식만 따른다:
 * now → updateTag(방금 한 일을 바로 보게, read-your-own-writes), max → revalidateTag(tag, 'max')(옛 내용을 주며 뒤에서 갱신)
 */
export function applyInvalidation(inv: Invalidation): void {
  for (const tag of inv.now) updateTag(tag);
  for (const tag of inv.max) revalidateTag(tag, "max");
}
