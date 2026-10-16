"use client";

import Link from "next/link";
import { useState } from "react";
import { setReactionAction } from "@/app/boards/actions";
import { optimistic, settle, type Toggle } from "@/lib/boards/reactions";

// 추천·스크랩·공유 단추(설계도 §6.1·§13) — 헤드리스. 토글은 aria-pressed, 결과는 live region.
// 낙관적 갱신: 누르면 바로 바꾸고 Action 응답으로 바로잡는다. 처리 중에는 그 단추를 aria-disabled 로 막아 응답 순서가 뒤바뀌지 않게.

interface Props {
  postId: number;
  path: string;
  title: string;
  likeCount: number;
  liked: boolean;
  scrapped: boolean;
  /** 로그인한 사람 — 아니면 추천·스크랩 자리에 로그인 링크 */
  member: boolean;
  allowShare: boolean;
}

type Kind = "like" | "scrap";
const LABEL: Record<Kind, [string, string]> = { like: ["추천했습니다", "추천을 취소했습니다"], scrap: ["스크랩했습니다", "스크랩을 취소했습니다"] };

export function PostReactions({ postId, path, title, likeCount, liked, scrapped, member, allowShare }: Props) {
  const [state, setState] = useState<Record<Kind, Toggle>>({ like: { on: liked, count: likeCount }, scrap: { on: scrapped, count: null } });
  const [busy, setBusy] = useState<Record<Kind, boolean>>({ like: false, scrap: false });
  const [message, setMessage] = useState("");

  async function toggle(kind: Kind) {
    if (busy[kind]) return;
    const prev = state[kind];
    const on = !prev.on;
    setState((s) => ({ ...s, [kind]: optimistic(prev, on) }));
    setBusy((b) => ({ ...b, [kind]: true }));
    const res = await setReactionAction(postId, kind, on);
    setBusy((b) => ({ ...b, [kind]: false }));
    if (res.problem || res.on === undefined) {
      setState((s) => ({ ...s, [kind]: prev })); // 되돌림
      setMessage(res.problem?.title ?? "처리하지 못했습니다");
      return;
    }
    setState((s) => ({ ...s, [kind]: settle(prev, res.on as boolean, res.count) }));
    setMessage(LABEL[kind][res.on ? 0 : 1]);
  }

  async function share() {
    const url = new URL(path, window.location.origin).toString();
    try {
      if (navigator.share) {
        await navigator.share({ title, url });
        setMessage("공유했습니다");
      } else {
        await navigator.clipboard.writeText(url);
        setMessage("주소를 복사했습니다");
      }
    } catch {
      return; // 취소·거부 — 세지 않는다
    }
    fetch(`/api/posts/${postId}/share`, { method: "POST", keepalive: true }).catch(() => {});
  }

  const login = `/login?next=${encodeURIComponent(path)}`;
  return (
    <section data-slot="post-reactions" aria-label="글 반응">
      {member ? (
        <>
          <button type="button" data-slot="like" aria-pressed={state.like.on} aria-disabled={busy.like || undefined} onClick={() => toggle("like")}>
            추천 <span data-slot="count">{state.like.count}</span>
          </button>{" "}
          <button type="button" data-slot="scrap" aria-pressed={state.scrap.on} aria-disabled={busy.scrap || undefined} onClick={() => toggle("scrap")}>
            스크랩
          </button>
        </>
      ) : (
        <p data-slot="login-hint">
          추천 <span data-slot="count">{likeCount}</span> · <Link href={login}>로그인</Link> 하면 추천·스크랩할 수 있습니다.
        </p>
      )}
      {allowShare && (
        <>
          {" "}
          <button type="button" data-slot="share" onClick={share}>
            공유
          </button>
        </>
      )}
      <p role="status" data-slot="form-status">
        {message}
      </p>
    </section>
  );
}
