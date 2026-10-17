// 내 목록 응답 타입과 표시 문구(설계도 §6.2) — 순수

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface MyPost {
  id: number;
  title: string;
  board: { slug: string; name: string };
  status: "draft" | "scheduled" | "pending" | "published";
  is_secret: boolean;
  is_blinded: boolean;
  created_at: string;
  published_at: string | null;
  stats: { comments: number; likes: number };
  /** 작성자도 지금 열 수 없으면 null(게시판 조건·가림·등급 — §6.2) */
  path: string | null;
}

export interface MyComment {
  id: number;
  excerpt: string;
  is_blinded: boolean;
  created_at: string;
  post: { id: number; title: string | null; masked: "hidden" | null };
  path: string | null;
}

export interface MyScrap {
  post_id: number;
  title: string | null;
  masked: "hidden" | null;
  board: { slug: string; name: string } | null;
  scrapped_at: string;
  path: string | null;
}

export const STATUS_LABEL: Record<MyPost["status"], string | null> = {
  published: null,
  draft: "임시 저장",
  scheduled: "예약",
  pending: "승인 대기",
};

/** '더 보기' 링크 — 커서가 없으면 null */
export function moreHref(path: string, cursor: string | null): string | null {
  return cursor ? `${path}?cursor=${encodeURIComponent(cursor)}` : null;
}

/** 요청의 ?cursor= → API 쿼리 문자열 */
export function cursorQuery(raw: string | string[] | undefined): string {
  return typeof raw === "string" && raw ? `?cursor=${encodeURIComponent(raw)}` : "";
}
