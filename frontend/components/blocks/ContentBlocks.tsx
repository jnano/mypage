import type { BlockData, LabeledLink } from "@/lib/blocks/types";
import { BlockImage } from "./BlockImage";
import { BlockLink } from "./BlockLink";

// 콘텐츠 블록(홈블록 설계도 §2.2). html 은 서버가 글과 같은 변환·정화(markdown_to_html + nh3)를 거쳐 만든 것이다

/** 블록 안 제목 — 단계는 부르는 쪽이 정한다(페이지 h1 아래 h2, 이름 있는 묶음 안이면 한 단 아래, h4 까지) */
export function BlockTitle({ level, children }: { level: number; children: string }) {
  const Tag = (`h${Math.min(Math.max(level, 2), 4)}`) as "h2" | "h3" | "h4";
  return <Tag data-slot="block-title">{children}</Tag>;
}

export function HeadingBlock({ data }: { data: BlockData["heading"] }) {
  return <BlockTitle level={data.level}>{data.text}</BlockTitle>;
}

export function TextBlock({ data }: { data: BlockData["text"] }) {
  return <div data-slot="block-text" dangerouslySetInnerHTML={{ __html: data.html }} />;
}

export function ImageBlock({ data }: { data: BlockData["image"] }) {
  const img = <BlockImage image={data.image} />;
  return <figure data-slot="block-image">{data.link ? <BlockLink link={data.link}>{img}</BlockLink> : img}</figure>;
}

function ButtonRow({ items }: { items: LabeledLink[] }) {
  return (
    <ul data-slot="buttons">
      {items.map((b, i) => (
        <li key={i}>
          <BlockLink link={b} slot="button">
            {b.label}
          </BlockLink>
        </li>
      ))}
    </ul>
  );
}

export function BannerBlock({ data, level }: { data: BlockData["banner"]; level: number }) {
  return (
    <div data-slot="banner">
      <BlockImage image={data.image} sizes="100vw" />
      <BlockTitle level={level}>{data.title}</BlockTitle>
      {data.description && <p>{data.description}</p>}
      {data.buttons.length > 0 && <ButtonRow items={data.buttons} />}
    </div>
  );
}

export function ButtonsBlock({ data }: { data: BlockData["buttons"] }) {
  return <ButtonRow items={data.items} />;
}

export function LinkListBlock({ data, level }: { data: BlockData["link_list"]; level: number }) {
  return (
    <div data-slot="link-list">
      {data.title && <BlockTitle level={level}>{data.title}</BlockTitle>}
      <ul>
        {data.items.map((item, i) => (
          <li key={i}>
            <BlockLink link={item}>{item.label}</BlockLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

// 글 본문의 동영상과 같은 속성(backend app/editor/render.py) — 제목 필수(WCAG 4.1.2)
export function VideoBlock({ data }: { data: BlockData["video"] }) {
  return (
    <div data-slot="block-video">
      <iframe
        src={data.embed_url}
        title={data.title}
        loading="lazy"
        allow="encrypted-media; picture-in-picture; fullscreen"
        referrerPolicy="strict-origin-when-cross-origin"
        allowFullScreen
      />
    </div>
  );
}

// 네이티브 <details>/<summary> — 키보드·화면 낭독기 동작을 브라우저가 맡는다(§10)
export function DetailsBlock({ data }: { data: BlockData["details"] }) {
  return (
    <div data-slot="block-details">
      {data.items.map((item, i) => (
        <details key={i}>
          <summary>{item.question}</summary>
          <div dangerouslySetInnerHTML={{ __html: item.html }} />
        </details>
      ))}
    </div>
  );
}

export function DividerBlock() {
  return <hr data-slot="divider" />;
}
