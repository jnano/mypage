"use client";

import Link from "next/link";
import { useState } from "react";
import { addRelationAction, removeRelationAction } from "@/app/boards/actions";
import { parseTargetId, type RelationItem } from "@/lib/boards/relations";

// 관련 글 편집(설계도 §6.2) — 글 수정 화면 아래. 헤드리스, 결과는 role=status
const LIMIT = 10;

export function RelationsPanel({ postId, initial }: { postId: number; initial: RelationItem[] }) {
  const [items, setItems] = useState(initial);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function run(task: () => ReturnType<typeof addRelationAction>, done: string) {
    setBusy(true);
    const res = await task();
    setBusy(false);
    if (res.problem || !res.items) {
      setMessage(res.problem?.errors?.[0]?.message ?? res.problem?.title ?? "처리하지 못했습니다");
      return;
    }
    setItems(res.items);
    setMessage(done);
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const target = parseTargetId(input);
    if (target === null) {
      setMessage("글 주소나 번호를 넣어 주세요");
      return;
    }
    await run(() => addRelationAction(postId, target), "관련 글을 붙였습니다");
    setInput("");
  }

  return (
    <section data-slot="relations-editor" aria-labelledby="relations-heading">
      <h2 id="relations-heading">관련 글</h2>
      {items.length === 0 ? (
        <p>붙인 관련 글이 없습니다.</p>
      ) : (
        <ul>
          {items.map((r) => (
            <li key={r.id}>
              {r.readable && r.board_slug ? <Link href={`/boards/${r.board_slug}/${r.id}`}>{r.title}</Link> : <span>볼 수 없는 글</span>}{" "}
              <button
                type="button"
                aria-label={`${r.title ?? "볼 수 없는 글"} 관련 글에서 빼기`}
                aria-disabled={busy || undefined}
                onClick={() => !busy && run(() => removeRelationAction(postId, r.id), "관련 글에서 뺐습니다")}
              >
                빼기
              </button>
            </li>
          ))}
        </ul>
      )}
      {items.length < LIMIT && (
        <form onSubmit={add} aria-label="관련 글 붙이기">
          <label>
            글 주소 또는 번호 <input value={input} onChange={(e) => setInput(e.target.value)} maxLength={300} />
          </label>{" "}
          <button type="submit" aria-disabled={busy || undefined}>
            붙이기
          </button>
        </form>
      )}
      <p role="status" data-slot="form-status">
        {message}
      </p>
    </section>
  );
}
