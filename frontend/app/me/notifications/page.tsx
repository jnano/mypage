import Link from "next/link";
import { Suspense } from "react";
import { markNotificationsReadAction, saveNotificationPrefsAction } from "@/app/boards/actions";
import { ApiError } from "@/lib/api/problem";
import { hasViewer, personalGet } from "@/lib/server/backend";

// 알림함 — 개인 데이터(요청 시점, 캐시 안 함). 열 수 없게 된 글은 서버가 제목을 가려 보낸다(§7)
export const metadata = { title: "알림", robots: { index: false, follow: false } };

interface Inbox {
  items: {
    id: number;
    type: string;
    actor_name: string | null;
    actor_count: number;
    title: string | null;
    masked: "deleted" | "hidden" | null;
    path: string | null;
    read: boolean;
    updated_at: string;
  }[];
  next_cursor: string | null;
}
interface Prefs {
  items: { type: string; label: string; enabled: boolean }[];
}

const VERB: Record<string, string> = {
  "comment.on_my_post": "내 글에 댓글을 남겼습니다",
  "comment.reply": "내 댓글에 답글을 남겼습니다",
  "board.new_post": "구독한 게시판에 새 글",
  "moderation.blinded": "내 글·댓글이 가려졌습니다",
  "moderation.moved": "내 글이 옮겨졌습니다",
  "admin.guest_pending": "승인 대기 글",
  "admin.report": "신고가 접수되었습니다",
  "report.resolved": "내 신고가 처리되었습니다",
};

export default function NotificationsPage(props: PageProps<"/me/notifications">) {
  return (
    <section data-slot="notifications">
      <h1>알림</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Inbox {...props} />
      </Suspense>
    </section>
  );
}

async function Inbox({ searchParams }: PageProps<"/me/notifications">) {
  if (!(await hasViewer())) {
    return (
      <p>
        <Link href="/dev/login">로그인</Link> 하면 알림을 볼 수 있습니다.
      </p>
    );
  }
  const cursor = (await searchParams).cursor;
  const q = typeof cursor === "string" && cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  let inbox: Inbox;
  let prefs: Prefs;
  try {
    [inbox, prefs] = await Promise.all([personalGet<Inbox>(`/api/me/notifications${q}`), personalGet<Prefs>("/api/me/notification-prefs")]);
  } catch (e) {
    if (e instanceof ApiError) return <p role="alert">{e.problem.title}</p>;
    throw e;
  }
  const types = prefs.items.map((p) => p.type);
  return (
    <>
      <form action={markNotificationsReadAction.bind(null, "all")}>
        <button type="submit">모두 읽음</button>
      </form>
      {inbox.items.length === 0 ? (
        <p data-slot="empty">알림이 없습니다.</p>
      ) : (
        <ol data-slot="notification-list">
          {inbox.items.map((n) => {
            const who = n.actor_name ? `${n.actor_name}${n.actor_count > 1 ? ` 님 외 ${n.actor_count - 1}명` : " 님"}` : "";
            const title = n.masked === "deleted" ? "삭제된 글" : n.masked === "hidden" ? "볼 수 없는 글" : n.title;
            return (
              <li key={n.id} data-slot="notification" data-read={n.read || undefined}>
                <p>
                  {who && <b>{who}</b>} {VERB[n.type] ?? n.type}
                </p>
                <p>{n.path ? <Link href={n.path}>{title}</Link> : title}</p>
                <p data-slot="post-meta">
                  <time dateTime={n.updated_at}>{n.updated_at.slice(0, 16).replace("T", " ")}</time>
                  {n.read ? " · 읽음" : ""}
                </p>
                {!n.read && (
                  <form action={markNotificationsReadAction.bind(null, [n.id])}>
                    <button type="submit">읽음 표시</button>
                  </form>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {inbox.next_cursor && (
        <p>
          <Link href={`/me/notifications?cursor=${encodeURIComponent(inbox.next_cursor)}`}>더 보기</Link>
        </p>
      )}
      <form id="prefs" action={saveNotificationPrefsAction.bind(null, types)}>
        <fieldset>
          <legend>받을 알림</legend>
          {prefs.items.map((p) => (
            <label key={p.type}>
              <input type="checkbox" name={p.type} defaultChecked={p.enabled} /> {p.label}
            </label>
          ))}
        </fieldset>
        <button type="submit">설정 저장</button>
      </form>
    </>
  );
}
