import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { ApiError } from "@/lib/api/problem";
import { applyUnmask, boardQueryString, maskedIds, planBoard, planPost } from "@/lib/boards/plan";
import type { BoardPage, BoardQuery, CommentPage, Fetched, PageState, PostPage } from "@/lib/boards/types";
import { hasViewer, personalGet, publicGet } from "@/lib/server/backend";

// 화면 데이터 — 화면 하나당 FastAPI 호출: 공개 ≤ 2, 로그인 ≤ 3(§3.6, §15)
// 공개 결과는 비회원 기준 캐시(태그는 §3.4 무효화 표와 같은 이름), 개인 결과는 요청 시점(캐시 안 함)

async function settle<T>(load: () => Promise<T>): Promise<Fetched<T>> {
  try {
    return { ok: true, data: await load() };
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, problem: e.problem };
    throw e;
  }
}

export async function getPublicBoardPage(slug: string, query: BoardQuery): Promise<Fetched<BoardPage>> {
  "use cache";
  cacheTag(`board:${slug}`);
  cacheLife("minutes"); // 글 수·조회수 같은 카운터는 무효화하지 않고 자연 갱신(§3.4)
  return settle(() => publicGet<BoardPage>(`/api/boards/${encodeURIComponent(slug)}/page${boardQueryString(query)}`));
}

export async function getPublicPostPage(id: number): Promise<Fetched<PostPage>> {
  "use cache";
  cacheTag(`post:${id}`);
  cacheLife("minutes");
  const result = await settle(() => publicGet<PostPage>(`/api/posts/${id}/page`));
  if (result.ok) cacheTag(`board:${result.data.board.slug}`);
  return result;
}

function pageStatePath(slug: string, ids: number[]): string {
  const q = new URLSearchParams({ board: slug });
  if (ids.length) q.set("ids", ids.join(","));
  return `/api/me/page-state?${q}`;
}

export interface BoardScreen {
  result: Fetched<BoardPage>;
  state: PageState | null;
  plan: "public" | "public+unmask" | "personal";
}

export async function loadBoardScreen(slug: string, query: BoardQuery): Promise<BoardScreen> {
  const pub = await getPublicBoardPage(slug, query);
  if (!(await hasViewer()) || (!pub.ok && pub.problem.status === 404)) {
    return { result: pub, state: null, plan: "public" };
  }
  const state = await personalGet<PageState>(pageStatePath(slug, pub.ok ? maskedIds(pub.data) : []));
  const plan = planBoard(pub, state);
  if (plan === "personal") {
    const mine = await settle(() =>
      personalGet<BoardPage>(`/api/boards/${encodeURIComponent(slug)}/page${boardQueryString(query)}`),
    );
    return { result: mine, state, plan };
  }
  if (plan === "public+unmask" && pub.ok) {
    return { result: { ok: true, data: applyUnmask(pub.data, state.unmasked) }, state, plan };
  }
  return { result: pub, state, plan };
}

export interface PostScreen {
  result: Fetched<PostPage>;
  state: PageState | null;
  canEdit: boolean;
}

export async function loadPostScreen(slug: string, id: number): Promise<PostScreen> {
  const pub = await getPublicPostPage(id);
  if (!(await hasViewer()) || (!pub.ok && pub.problem.status === 410)) {
    return { result: pub, state: null, canEdit: false };
  }
  const boardSlug = pub.ok ? pub.data.board.slug : slug;
  const state = await personalGet<PageState>(pageStatePath(boardSlug, [id]));
  const result = planPost(pub.ok, state) === "personal" ? await settle(() => personalGet<PostPage>(`/api/posts/${id}/page`)) : pub;
  // 글이 화면 게시판의 목록 대상이 아니면(예: 임시 글) 개인 조각의 editable 에 없다 — 열람 가능하면 작성자 여부로 다시 본다
  const canEdit = state.editable.includes(id) || (result.ok && result.data.post.status !== "published" && state.viewer !== null);
  return { result, state, canEdit };
}

/** 댓글 더 보기 — 공개 캐시(글 태그와 함께 무효화된다) */
export async function getPublicComments(postId: number, cursor: string): Promise<Fetched<CommentPage>> {
  "use cache";
  cacheTag(`post:${postId}`);
  cacheLife("minutes");
  return settle(() => publicGet<CommentPage>(`/api/posts/${postId}/comments?cursor=${encodeURIComponent(cursor)}`));
}
