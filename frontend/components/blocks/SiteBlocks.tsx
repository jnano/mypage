import Link from "next/link";
import { useId } from "react";
import { searchLandmark } from "@/lib/admin/enums.gen.json";
import type { BlockData } from "@/lib/blocks/types";
import { BlockImage } from "./BlockImage";

// 사이트 블록(홈블록 설계도 §2.2). 메뉴 셋(menu·sub_menu·breadcrumb)은 MenuBlocks

export function SiteBrandBlock({ data }: { data: BlockData["site_brand"] }) {
  return (
    <Link href={data.href} data-slot="site-brand">
      {data.logo && <BlockImage image={data.logo} sizes="200px" />}
      {data.name && <span data-slot="site-name">{data.name}</span>}
    </Link>
  );
}

export function SearchBoxBlock({ data }: { data: BlockData["search_box"] }) {
  const id = useId();
  return (
    // 이름 있는 검색 랜드마크 — 검색 화면의 검색 폼과 함께 있어도 구분된다(axe landmark-unique, §10). 이름은 저장 검증과 같은 값
    // (생성 파일 — 원본 backend tree.SEARCH_LANDMARK, 한 화면에 검색 블록 하나 규칙 D-122)
    <form role="search" aria-label={searchLandmark} action={data.action} method="get" data-slot="search-box">
      <label htmlFor={id}>{searchLandmark}</label>
      <input id={id} type="search" name="q" placeholder={data.placeholder} maxLength={100} />
      <button type="submit">검색</button>
    </form>
  );
}

export function FooterInfoBlock({ data }: { data: BlockData["footer_info"] }) {
  return (
    <div data-slot="footer-info">
      {data.lines.length > 0 && (
        <dl>
          {data.lines.map((line, i) => (
            <div key={i}>
              <dt>{line.label}</dt>
              <dd>{line.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {data.copyright && (
        <p>
          <small>{data.copyright}</small>
        </p>
      )}
    </div>
  );
}
