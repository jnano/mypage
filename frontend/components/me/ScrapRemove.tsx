"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { setReactionAction } from "@/app/boards/actions";

// 스크랩 지우기(설계도 §6.2) — 묶음 A 의 상태 지정 Action 을 그대로 쓴다. 지운 뒤 목록을 다시 그린다
export function ScrapRemove({ postId, label }: { postId: number; label: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function remove() {
    if (busy) return;
    setBusy(true);
    const res = await setReactionAction(postId, "scrap", false);
    setBusy(false);
    if (res.problem) {
      setMessage(res.problem.title);
      return;
    }
    setMessage("스크랩을 지웠습니다");
    router.refresh();
  }

  return (
    <>
      <button type="button" aria-label={`${label} 스크랩 지우기`} aria-disabled={busy || undefined} onClick={remove}>
        지우기
      </button>
      <span role="status" data-slot="form-status">
        {message}
      </span>
    </>
  );
}
