// 블록 종류·그리기용 모양 — 원본은 backend/app/blocks(types·resolve), 이 폴더의 blocks.gen.json 은 생성 파일
// (홈블록 설계도 §4.4.2). 모양을 바꾸면 백엔드 resolve 와 이 타입을 같이 고친다
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
