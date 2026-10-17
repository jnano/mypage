// 블록 종류·그리기용 모양 — 원본은 backend/app/blocks(types·resolve), 이 폴더의 blocks.gen.json 은 생성 파일
// (홈블록 설계도 §4.4.2). 모양을 바꾸면 백엔드 resolve 와 이 타입을 같이 고친다
import type { MenuItemView } from "./currentItem";
import generated from "./blocks.gen.json";

export const BLOCKS = generated;
export const REGIONS = generated.regions;
export const PAGE_PATH_PATTERN = generated.pagePathPattern;

export type BlockLinkView = { href: string; new_window: boolean };
export type LabeledLink = BlockLinkView & { label: string };
export type ImageView = {
  alt: string;
  width: number | null;
  height: number | null;
  src?: string;
  srcset?: string;
  pending?: true;
};

export type BlockData = {
  site_brand: { href: string; name: string | null; logo: ImageView | null };
  menu: { label: string; items: MenuItemView[] };
  sub_menu: { label: string; show_root_title: boolean; items: MenuItemView[] };
  breadcrumb: { label: string; items: MenuItemView[] };
  search_box: { action: string; placeholder: string };
  account: Record<string, never>;
  footer_info: { lines: { label: string; value: string }[]; copyright: string | null };
  heading: { text: string; level: 2 | 3 | 4 };
  text: { html: string };
  image: { image: ImageView; link: BlockLinkView | null };
  banner: { image: ImageView; title: string; description: string | null; buttons: LabeledLink[] };
  buttons: { items: LabeledLink[] };
  link_list: { title: string | null; items: LabeledLink[] };
  video: { title: string; embed_url: string };
  details: { items: { question: string; html: string }[] };
  divider: Record<string, never>;
  recent_posts: {
    title: string | null;
    view: "list" | "photo";
    items: { id: number; title: string; href: string; published_at: string; pinned: boolean; image?: ImageView | null }[];
  };
  recent_comments: {
    title: string | null;
    items: { id: number; excerpt: string; author: string; post_title: string; href: string; created_at: string }[];
  };
  board_links: { title: string | null; items: { name: string; href: string; last_posted_at: string | null }[] };
  group: { title: string | null; landmark: boolean };
  columns: { count: number };
};

export type RenderableType = keyof BlockData;

/** 묶음 응답의 블록 하나(걸음 5 가 채운다). group 은 children, columns 는 칸마다 블록 목록 */
export type BlockNode = {
  [K in RenderableType]: {
    id: number;
    type: K;
    data: BlockData[K];
    children?: BlockNode[];
    columns?: BlockNode[][];
  };
}[RenderableType];

/** 틀 묶음(GET /api/frame)의 블록 — 개인 블록은 data 없이 자리만, 회원이면 다시 계산할 블록은 refresh(걸음 5-3) */
export type FrameNode = {
  id: number;
  type: RenderableType;
  data?: BlockData[RenderableType];
  personal?: true;
  refresh?: true;
  audience?: "guest";
  children?: FrameNode[];
  columns?: FrameNode[][];
};

export type FrameBundle = {
  layout: { id: number; version: number; regions: Partial<Record<string, FrameNode[]>> } | null;
  personal_block_ids: number[];
  cache: { tags: string[] };
};
