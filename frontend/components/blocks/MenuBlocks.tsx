"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId, useState } from "react";
import { currentChain, type MenuItemView } from "@/lib/blocks/currentItem";
import type { BlockData } from "@/lib/blocks/types";
import { BlockLink } from "./BlockLink";
import { BlockTitle } from "./ContentBlocks";

// 메뉴 블록 셋(홈블록 설계도 §2.2·§10). 묶음 응답은 메뉴 전체 트리를 주고 지금 항목은 여기서 주소로 고른다(currentItem).
// 펼침은 단추 + aria-expanded(APG Disclosure Navigation) — 마우스 올림만으로 열지 않는다. 지금 항목에 aria-current="page"

function ItemLink({ item, current }: { item: MenuItemView; current: boolean }) {
  if (item.href === null) return <span>{item.label}</span>;
  return (
    <BlockLink link={{ href: item.href, new_window: item.new_window }} current={current} slot="menu-item">
      {item.label}
    </BlockLink>
  );
}

/** 하위 항목을 펼치는 한 칸 — 주소가 있으면 링크 + 펼침 단추, 없으면(묶음 제목) 이름이 곧 펼침 단추 */
function Disclosure({ item, currentId, inChain }: { item: MenuItemView; currentId: number | null; inChain: boolean }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const toggle = { "aria-expanded": open, "aria-controls": id, onClick: () => setOpen(!open) };
  return (
    <li data-slot="menu-item" data-in-path={inChain || undefined}>
      {item.href === null ? (
        <button type="button" {...toggle}>
          {item.label}
        </button>
      ) : (
        <>
          <ItemLink item={item} current={item.id === currentId} />
          {/* 보이는 글자가 접근 이름 안에 있어야 한다(WCAG 2.5.3) — 빈 단추는 누를 자리도 없다(2.5.8) */}
          <button type="button" {...toggle} aria-label={`${item.label} 하위 메뉴 펼치기`} data-slot="submenu-toggle">
            펼치기
          </button>
        </>
      )}
      <ul id={id} hidden={!open}>
        {item.children.map((child) => (
          <li key={child.id} data-slot="menu-item">
            <ItemLink item={child} current={child.id === currentId} />
          </li>
        ))}
      </ul>
    </li>
  );
}

export function MenuBlock({ data }: { data: BlockData["menu"] }) {
  const chain = currentChain(data.items, usePathname());
  const currentId = chain.at(-1)?.id ?? null;
  return (
    <nav aria-label={data.label} data-slot="menu">
      <ul>
        {data.items.map((item) =>
          item.children.length > 0 ? (
            <Disclosure key={item.id} item={item} currentId={currentId} inChain={chain[0]?.id === item.id} />
          ) : (
            <li key={item.id} data-slot="menu-item">
              <ItemLink item={item} current={item.id === currentId} />
            </li>
          ),
        )}
      </ul>
    </nav>
  );
}

function Tree({ items, currentId }: { items: MenuItemView[]; currentId: number | null }) {
  return (
    <ul>
      {items.map((item) => (
        <li key={item.id} data-slot="menu-item">
          <ItemLink item={item} current={item.id === currentId} />
          {item.children.length > 0 && <Tree items={item.children} currentId={currentId} />}
        </li>
      ))}
    </ul>
  );
}

/** 옆 메뉴 — 지금 화면이 속한 1단 항목의 아래 트리. 지금 항목이 메뉴에 없거나 그 1단에 아래가 없으면 1단 목록 */
export function SubMenuBlock({ data, level }: { data: BlockData["sub_menu"]; level: number }) {
  const chain = currentChain(data.items, usePathname());
  const root = chain[0];
  const currentId = chain.at(-1)?.id ?? null;
  const inRoot = root !== undefined && root.children.length > 0;
  return (
    <nav aria-label={data.label} data-slot="sub-menu">
      {inRoot && data.show_root_title && <BlockTitle level={level}>{root.label}</BlockTitle>}
      <Tree items={inRoot ? root.children : data.items.map((i) => ({ ...i, children: [] }))} currentId={currentId} />
    </nav>
  );
}

/** 경로 표시 — 처음 › 1단 › … › 지금(지금 항목은 aria-current). 지금 항목이 메뉴에 없으면 그리지 않는다 */
export function BreadcrumbBlock({ data }: { data: BlockData["breadcrumb"] }) {
  const chain = currentChain(data.items, usePathname());
  if (chain.length === 0) return null;
  return (
    <nav aria-label={data.label} data-slot="breadcrumb">
      <ol>
        <li>
          <Link href="/">처음</Link>
        </li>
        {chain.map((item, i) => (
          <li key={item.id}>
            <ItemLink item={item} current={i === chain.length - 1} />
          </li>
        ))}
      </ol>
    </nav>
  );
}
