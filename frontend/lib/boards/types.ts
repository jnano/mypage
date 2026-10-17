// FastAPI 묶음 응답의 모양(backend/app/posts/present.py, app/api/*.py 와 짝)
import type { ProblemBody } from "@/lib/api/problem";

export type MaskReason = "secret" | "blinded" | "level";

export interface BoardSummary {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  kind: "default" | "gallery" | "line";
  editor: "rich" | "markdown";
  display: { views?: string[]; default_view?: string; list_columns?: string[] };
  hidden_post_listing: "mask" | "hide";
  pinned_display: "strip" | "inline";
  allow_secret: boolean;
  allow_comments: boolean;
  allow_share: boolean;
  posts_per_page: number;
  indexable: boolean;
  is_public: boolean;
}

export interface ListRow {
  id: number;
  title: string | null;
  masked: MaskReason | null;
  title_bold: boolean;
  title_color: string | null;
  author_name: string;
  /** 비회원 글 — 화면이 이름 옆에 '(비회원)'(§6.3) */
  author_is_guest: boolean;
  posted_as: "personal" | "admin";
  published_at: string | null;
  edited: boolean;
  is_secret: boolean;
  is_pinned: boolean;
  expired: boolean;
  category_ids: number[];
  stats: { views: number; likes: number; comments: number };
}

export interface BoardPage {
  board: BoardSummary;
  categories: { id: number; name: string }[];
  view: string;
  pinned: ListRow[];
  posts: ListRow[];
  page: {
    page: number;
    per_page: number;
    total: number;
    total_capped: boolean;
    last_page: number;
    category: number | null;
    archived: boolean;
    sort: string;
  };
  cache: { tags: string[]; has_restricted_posts: boolean };
}

export interface PostSeo {
  description: string;
  image: { url: string; width: number | null; height: number | null; alt: string } | null;
}

export interface PostPage {
  board: BoardSummary;
  /** 공개 색인 대상 글만(§10) — 비공개 글은 null */
  seo: PostSeo | null;
  post: {
    id: number;
    title: string;
    title_bold: boolean;
    title_color: string | null;
    author_name: string;
    author_is_guest: boolean;
    posted_as: "personal" | "admin";
    status: string;
    content_format: "rich" | "markdown";
    content_html: string;
    published_at: string | null;
    content_updated_at: string | null;
    edited: boolean;
    expired: boolean;
    is_pinned: boolean;
    is_secret: boolean;
    category_ids: number[];
    version: number;
    stats: { views: number; likes: number; comments: number; scraps: number; shares: number };
    indexable: boolean;
  };
  neighbors: { prev: { id: number; title: string | null } | null; next: { id: number; title: string | null } | null };
  related: { id: number; title: string; board_slug: string }[];
  attachments: AttachmentItem[];
  comments: CommentPage;
  /** 비회원 작성자가 edit 토큰으로 보고 있으면 true(§6.3) */
  guest_can_edit?: boolean;
  cache: { tags: string[] };
}

export interface AttachmentItem {
  id: number;
  name: string;
  size: number;
  mime: string;
  is_image: boolean;
  width: number | null;
  height: number | null;
  alt: string | null;
  is_cover: boolean;
  role: "attachment" | "inline";
  url: string;
  thumb: string | null;
}

export interface CommentItem {
  id: number;
  parent_id: number | null;
  reply_to: { id: number; author_name: string } | null;
  author_id: number | null;
  author_name: string | null;
  content: string | null;
  masked: "deleted" | "blinded" | null;
  is_blinded: boolean;
  edited: boolean;
  created_at: string;
}

export interface CommentPage {
  items: CommentItem[];
  next_cursor: string | null;
}

export interface PageState {
  viewer: { member_id: number; level: number; is_admin: boolean } | null;
  board_role: { is_moderator: boolean };
  unmasked: { id: number; title: string }[];
  editable: number[];
  /** 요청한 글 가운데 추천·스크랩한 글(§6.1) */
  liked: number[];
  scrapped: number[];
  unread_notifications: number;
  unread_capped: boolean;
  subscribed: boolean;
}

export interface EditablePost {
  id: number;
  is_guest: boolean;
  board_slug: string;
  title: string;
  content_format: "rich" | "markdown";
  content: string;
  category_ids: number[];
  is_secret: boolean;
  status: string;
  version: number;
  attachments: AttachmentItem[];
}

export interface Invalidation {
  now: string[];
  max: string[];
}

/** 공개 캐시에 담는 결과 — 오류도 값으로 담아 캐시한다(같은 거부를 매번 묻지 않게) */
export type Fetched<T> = { ok: true; data: T } | { ok: false; problem: ProblemBody };

export interface BoardQuery {
  page: number;
  category: number | null;
  archived: boolean;
}
