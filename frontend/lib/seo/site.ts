// 사이트 공개 설정 형식(GET /api/site) — 메타·sitemap·robots·RSS 가 같이 쓴다(§10)
export interface SiteSeo {
  indexable: boolean;
  site_name: string;
  site_url: string;
  description: string;
  google_verification: string;
  naver_verification: string;
  bing_verification: string;
}

export interface SiteInfo {
  seo: SiteSeo;
  levels: { names: Record<string, string> };
}

/** 절대 주소 — 사이트 주소 설정이 비었으면 경로 그대로(운영 전 체크리스트에서 채운다) */
export function absolute(site: SiteSeo, path: string): string {
  return site.site_url ? `${site.site_url}${path}` : path;
}

/** RSS·XML 에 넣을 글자 이스케이프 */
export function xmlEscape(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

/** JSON-LD 를 <script> 안에 넣을 때 — </script> 로 끊기지 않게 < 를 이스케이프한다 */
export function jsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
