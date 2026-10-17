"use client";

import { useEffect, useRef, useState } from "react";

// 표 머리의 '이 쪽 모두 고르기' — 같은 표 몸의 고르기 체크(name)를 한꺼번에 켜고 끈다. 몇 개만 고르면 반쯤 상태.
// JS 가 없으면 아무 일도 하지 않으므로 그때는 숨긴다(처음 그릴 때 hidden, 붙은 뒤 보임)
export function SelectAll({ name, label }: { name: string; label: string }) {
  const ref = useRef<HTMLInputElement>(null);
  const [ready, setReady] = useState(false);
  const boxes = (): HTMLInputElement[] => [...(ref.current?.closest("table")?.querySelectorAll<HTMLInputElement>(`tbody input[type="checkbox"][name="${name}"]`) ?? [])];
  useEffect(() => {
    const me = ref.current;
    const table = me?.closest("table");
    if (!me || !table) return;
    setReady(true);
    const sync = () => {
      const all = boxes();
      const on = all.filter((b) => b.checked).length;
      me.checked = all.length > 0 && on === all.length;
      me.indeterminate = on > 0 && on < all.length;
    };
    table.addEventListener("change", sync);
    sync();
    return () => table.removeEventListener("change", sync);
  }, [name]);
  return (
    <input
      ref={ref}
      type="checkbox"
      hidden={!ready}
      aria-label={label}
      onChange={(e) => {
        for (const b of boxes()) b.checked = e.currentTarget.checked;
        e.currentTarget.indeterminate = false;
      }}
    />
  );
}
