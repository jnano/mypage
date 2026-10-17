import Link from "next/link";
import { useId } from "react";
import { AccountNav } from "@/components/auth/AccountNav";
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
    <form role="search" action={data.action} method="get" data-slot="search-box">
      <label htmlFor={id}>사이트 검색</label>
      <input id={id} type="search" name="q" placeholder={data.placeholder} maxLength={100} />
      <button type="submit">검색</button>
    </form>
  );
}

// 쿠키 유무만 보는 기존 부품 — FastAPI 를 부르지 않는다(화면당 호출 예산). 요청 시점이라 부르는 쪽이 <Suspense> 안에 둔다
export function AccountBlock() {
  return (
    <div data-slot="account">
      <AccountNav />
    </div>
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
