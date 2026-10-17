import { useId, type ReactNode } from "react";
import type { BlockData, BlockNode, RenderableType } from "@/lib/blocks/types";
import {
  BannerBlock,
  BlockTitle,
  ButtonsBlock,
  DetailsBlock,
  DividerBlock,
  HeadingBlock,
  ImageBlock,
  LinkListBlock,
  TextBlock,
  VideoBlock,
} from "./ContentBlocks";
import { BoardLinksBlock, RecentCommentsBlock, RecentPostsBlock } from "./DynamicBlocks";
import { BreadcrumbBlock, MenuBlock, SubMenuBlock } from "./MenuBlocks";
import { FooterInfoBlock, SearchBoxBlock, SiteBrandBlock } from "./SiteBlocks";

// 블록 하나를 종류에 맞는 부품으로(홈블록 설계도 §3·§4.4.2). 등록부는 그릴 수 있는 종류 전부를 빠짐없이 가져야 한다 —
// satisfies Record<RenderableType, …> 가 빠진 종류를 타입 검사에서 잡는다. 서버 전용 부품이 필요한 자리 둘(모듈·계정)은
// 부르는 쪽이 끼운다: 화면은 RenderBlock.tsx(게시판 모듈·쿠키를 읽는 계정 표시), 관리 화면 미리보기는 브라우저에서
// 그리므로 자리 표시(components/admin/blocks/PreviewBlocks.tsx). 그 밖의 부품은 서버·브라우저 어디서나 그려진다

export type Props<K extends RenderableType> = { node: Extract<BlockNode, { type: K }>; level: number };
export type SlotParts = { module: (props: Props<"module">) => ReactNode; account: (props: Props<"account">) => ReactNode };

export function blockRenderer(slots: SlotParts) {
  const REGISTRY = {
    site_brand: ({ node }) => <SiteBrandBlock data={node.data} />,
    menu: ({ node }) => <MenuBlock data={node.data} />,
    sub_menu: ({ node, level }) => <SubMenuBlock data={node.data} level={level} />,
    breadcrumb: ({ node }) => <BreadcrumbBlock data={node.data} />,
    search_box: ({ node }) => <SearchBoxBlock data={node.data} />,
    account: slots.account,
    footer_info: ({ node }) => <FooterInfoBlock data={node.data} />,
    heading: ({ node }) => <HeadingBlock data={node.data} />,
    text: ({ node }) => <TextBlock data={node.data} />,
    image: ({ node }) => <ImageBlock data={node.data} />,
    banner: ({ node, level }) => <BannerBlock data={node.data} level={level} />,
    buttons: ({ node }) => <ButtonsBlock data={node.data} />,
    link_list: ({ node, level }) => <LinkListBlock data={node.data} level={level} />,
    video: ({ node }) => <VideoBlock data={node.data} />,
    details: ({ node }) => <DetailsBlock data={node.data} />,
    divider: () => <DividerBlock />,
    recent_posts: ({ node, level }) => <RecentPostsBlock data={node.data} level={level} />,
    recent_comments: ({ node, level }) => <RecentCommentsBlock data={node.data} level={level} />,
    board_links: ({ node, level }) => <BoardLinksBlock data={node.data} level={level} />,
    module: slots.module,
    group: ({ node, level }) => <GroupBlock node={node} level={level} />,
    columns: ({ node, level }) => <ColumnsBlock node={node} level={level} />,
  } satisfies { [K in RenderableType]: (props: Props<K>) => ReactNode };

  function RenderBlock({ node, level = 2 }: { node: BlockNode; level?: number }) {
    const Part = REGISTRY[node.type] as (props: { node: BlockNode; level: number }) => ReactNode;
    return (
      <div data-slot="block" data-block-type={node.type}>
        <Part node={node} level={level} />
      </div>
    );
  }

  function RenderBlocks({ nodes, level = 2 }: { nodes: BlockNode[]; level?: number }) {
    return nodes.map((n) => <RenderBlock key={n.id} node={n} level={level} />);
  }

  // 묶음 — 이름이 있으면 그 아래 블록 제목은 한 단 아래. 랜드마크면 <section aria-labelledby>(§10, 이름 중복은 저장 검증)
  function GroupBlock({ node, level }: Props<"group">) {
    const id = useId();
    const data: BlockData["group"] = node.data;
    const inner = level + (data.title ? 1 : 0);
    const body = (
      <>
        {data.title && (
          <div id={id}>
            <BlockTitle level={level}>{data.title}</BlockTitle>
          </div>
        )}
        <RenderBlocks nodes={node.children ?? []} level={inner} />
      </>
    );
    return data.landmark ? (
      <section aria-labelledby={id} data-slot="group">
        {body}
      </section>
    ) : (
      <div data-slot="group">{body}</div>
    );
  }

  function ColumnsBlock({ node, level }: Props<"columns">) {
    const cols = node.columns ?? [];
    return (
      <div data-slot="columns" data-count={node.data.count}>
        {Array.from({ length: node.data.count }, (_, i) => (
          <div key={i} data-slot="column">
            <RenderBlocks nodes={cols[i] ?? []} level={level} />
          </div>
        ))}
      </div>
    );
  }

  return { RenderBlock, RenderBlocks, registry: REGISTRY };
}
