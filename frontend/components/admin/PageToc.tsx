// 긴 관리 화면의 목차(관리디자인 4단계 screens.css — 새 슬롯 page-toc). 각 카드·묶음의 id 로 간다.
// 위험 항목(비우기·삭제 등)은 data-danger 로 표시만 다르게(글자에 '삭제'·'탈퇴' 낱말이 이미 있다)
export function PageToc({ items }: { items: { id: string; label: string; danger?: boolean }[] }) {
  return (
    <nav aria-label="이 화면 목차" data-slot="page-toc">
      <p>목차</p>
      <ol>
        {items.map((it) => (
          <li key={it.id}>
            <a href={`#${it.id}`} data-danger={it.danger || undefined}>
              {it.label}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
