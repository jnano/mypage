import Link from "next/link";
import { Suspense } from "react";
import { ApiError, type ProblemBody } from "@/lib/api/problem";
import { personalGet } from "@/lib/server/backend";
import { getSearchTerms } from "@/lib/server/search";
import { formatDate } from "@/lib/format/time";

// 검색 — 결과는 캐시하지 않는다(검색어는 사용자가 마음대로 넣는 값, 설계도 §9). 보는 사람 기준(요청 시점)
export const metadata = { title: "검색", robots: { index: false, follow: false } };

interface SearchResponse {
  q: string;
  results: { id: number; title: string; author_name: string; published_at: string | null; board: { slug: string; name: string } }[];
  page: { page: number; total: number; total_capped: boolean; last_page: number };
}

export default function SearchPage(props: PageProps<"/search">) {
  return (
    <section data-slot="search">
      <h1>검색</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <SearchScreen {...props} />
      </Suspense>
    </section>
  );
}

function one(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

async function SearchScreen({ searchParams }: PageProps<"/search">) {
  const sp = await searchParams;
  const q = one(sp.q);
  const scope = one(sp.scope) === "title" ? "title" : "all";
  const page = Math.max(1, Number.parseInt(one(sp.page) || "1", 10) || 1);

  let data: SearchResponse | null = null;
  let problem: ProblemBody | null = null;
  if (q.trim()) {
    const params = new URLSearchParams({ q, scope, page: String(page) });
    try {
      data = await personalGet<SearchResponse>(`/api/search?${params}`);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      problem = e.problem;
    }
  }
  const error = problem?.errors?.[0]?.message ?? problem?.title;

  return (
    <>
      <form action="/search" role="search">
        <label htmlFor="q">검색어</label>
        <input
          id="q"
          name="q"
          type="search"
          defaultValue={q}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "q-error" : undefined}
        />
        <label>
          <input type="checkbox" name="scope" value="title" defaultChecked={scope === "title"} /> 제목만
        </label>
        <button type="submit">찾기</button>
        {error && (
          <p id="q-error" role="alert">
            {error}
          </p>
        )}
      </form>

      {!q.trim() && <TermLists />}

      {data && (
        <div aria-live="polite">
          <p>
            결과 {data.page.total_capped ? `${data.page.total}+` : data.page.total}건
          </p>
          {data.results.length === 0 ? (
            <p data-slot="empty">찾는 글이 없습니다.</p>
          ) : (
            <ol data-slot="post-list">
              {data.results.map((r) => (
                <li key={r.id} data-slot="post-item">
                  <Link href={`/boards/${r.board.slug}/${r.id}`} data-slot="post-title">
                    {r.title}
                  </Link>{" "}
                  <span data-slot="post-meta">
                    {r.board.name} · {r.author_name} · <time dateTime={r.published_at ?? undefined}>{formatDate(r.published_at)}</time>
                  </span>
                </li>
              ))}
            </ol>
          )}
          {data.page.last_page > 1 && (
            <nav aria-label="쪽 넘김" data-slot="pagination">
              <ul>
                {Array.from({ length: data.page.last_page }, (_, i) => i + 1).map((p) => (
                  <li key={p}>
                    <Link
                      href={`/search?${new URLSearchParams({ q, scope, page: String(p) })}`}
                      aria-current={p === page ? "page" : undefined}
                    >
                      {p}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          )}
        </div>
      )}
    </>
  );
}

/** 검색어가 없을 때만 — 검색 결과 화면의 호출 수를 늘리지 않는다(§9.1) */
async function TermLists() {
  const { popular, recommended } = await getSearchTerms();
  const href = (term: string) => `/search?${new URLSearchParams({ q: term })}`;
  return (
    <>
      {popular.length > 0 && (
        <section data-slot="popular-terms" aria-labelledby="popular-terms-heading">
          <h2 id="popular-terms-heading">인기 검색어</h2>
          <ol>
            {popular.map((p) => (
              <li key={p.term}>
                <Link href={href(p.display)}>{p.display}</Link>
              </li>
            ))}
          </ol>
        </section>
      )}
      {recommended.length > 0 && (
        <section data-slot="recommended-terms" aria-labelledby="recommended-terms-heading">
          <h2 id="recommended-terms-heading">추천 검색어</h2>
          <ul>
            {recommended.map((t) => (
              <li key={t}>
                <Link href={href(t)}>{t}</Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
