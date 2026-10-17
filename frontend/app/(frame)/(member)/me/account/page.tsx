import Link from "next/link";
import { MyTabs } from "@/components/me/MyTabs";
import { Suspense } from "react";
import { logoutAllAction } from "@/app/auth/actions";
import { cancelLevelRequestAction, changePasswordAction, requestLevelAction, revokeSessionAction, withdrawAction } from "./actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { ApiError } from "@/lib/api/problem";
import { formatDateTime } from "@/lib/format/time";
import { hasSessionCookie, personalGet } from "@/lib/server/backend";
import { redirectIfExpired } from "@/lib/server/session";

export const metadata = { title: "내 계정", robots: { index: false } };

interface Account {
  email: string;
  display_name: string;
  level: number;
  is_admin: boolean;
  created_at: string;
  password_changed_at: string | null;
}
interface LevelRequests {
  level: number;
  names: Record<string, string>;
  requestable: number[];
  items: { id: number; to_level: number; reason: string; status: string; decision_note: string | null; created_at: string }[];
}
const REQUEST_STATUS: Record<string, string> = { pending: "검토 중", approved: "승인", rejected: "거부", cancelled: "취소" };

interface Device {
  id: number;
  user_agent: string | null;
  created_at: string;
  last_write_at: string;
  expires_at: string;
  persistent: boolean;
  current: boolean;
}

// 내 계정(인증 설계도 §6) — 비밀번호 변경·기기 목록·승급 신청·탈퇴
export default function AccountPage(props: PageProps<"/me/account">) {
  return (
    <section data-slot="account">
      <h1>내 계정</h1>
      <MyTabs />
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <AccountView {...props} />
      </Suspense>
    </section>
  );
}

async function AccountView({ searchParams }: PageProps<"/me/account">) {
  if (!(await hasSessionCookie())) {
    return (
      <p>
        <Link href="/login?next=%2Fme%2Faccount">로그인</Link> 하면 내 계정을 볼 수 있습니다.
      </p>
    );
  }
  let me: Account;
  let devices: Device[];
  let levels: LevelRequests;
  try {
    const [a, d, l] = await Promise.all([
      personalGet<Account>("/api/me/account"),
      personalGet<{ items: Device[] }>("/api/me/sessions"),
      personalGet<LevelRequests>("/api/me/level-requests"),
    ]);
    me = a;
    devices = d.items;
    levels = l;
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401) await redirectIfExpired("personal");
      return <p role="alert">{e.problem.title}</p>;
    }
    throw e;
  }
  const notice = (await searchParams).notice;
  return (
    <>
      {notice === "password_reset_by_admin" && (
        <p role="status">운영자가 발급한 링크로 비밀번호가 바뀌었습니다. 본인이 바꾼 것이 아니면 운영자에게 알려 주세요.</p>
      )}
      <dl data-slot="account-info">
        <dt>표시 이름</dt>
        <dd>{me.display_name}</dd>
        <dt>이메일</dt>
        <dd>{me.email}(바꾸려면 운영자에게 요청합니다)</dd>
        <dt>가입</dt>
        <dd>
          <time dateTime={me.created_at}>{formatDateTime(me.created_at)}</time>
        </dd>
      </dl>

      <h2>비밀번호 바꾸기</h2>
      <AdminForm action={changePasswordAction} submitLabel="비밀번호 바꾸기" label="비밀번호 바꾸기">
        <label htmlFor="pw-current">지금 비밀번호</label>
        <input id="pw-current" name="current_password" type="password" autoComplete="current-password" required />
        <label htmlFor="pw-new">새 비밀번호</label>
        <input id="pw-new" name="new_password" type="password" autoComplete="new-password" required aria-describedby="pw-new-help" />
        <p id="pw-new-help">띄어쓰기를 포함한 문장도 됩니다. 바꾸면 이 기기를 뺀 다른 기기는 로그아웃됩니다.</p>
        <label htmlFor="pw-again">새 비밀번호 한 번 더</label>
        <input id="pw-again" name="new_password_again" type="password" autoComplete="new-password" required />
      </AdminForm>

      <h2>로그인한 기기</h2>
      <ul data-slot="devices">
        {devices.map((d) => (
          <li key={d.id}>
            <p>
              {d.user_agent ?? "알 수 없는 브라우저"}
              {d.current ? " · 지금 이 기기" : ""}
            </p>
            <p data-slot="post-meta">
              로그인 <time dateTime={d.created_at}>{formatDateTime(d.created_at)}</time> · 마지막 활동(글쓰기 등){" "}
              <time dateTime={d.last_write_at}>{formatDateTime(d.last_write_at)}</time>
              {d.persistent ? " · 로그인 상태 유지" : ""}
            </p>
            {!d.current && <AdminForm action={revokeSessionAction.bind(null, d.id)} submitLabel="이 기기 로그아웃" label={`기기 ${d.id} 로그아웃`} />}
          </li>
        ))}
      </ul>
      <form action={logoutAllAction} data-slot="logout-all">
        <button type="submit">모든 기기에서 로그아웃</button>
      </form>

      <h2>레벨</h2>
      <p>
        지금 레벨: {levels.names[String(levels.level)] ?? `레벨 ${levels.level}`}({levels.level})
      </p>
      {levels.items.length > 0 && (
        <ul data-slot="level-requests">
          {levels.items.map((r) => (
            <li key={r.id}>
              {levels.names[String(r.to_level)] ?? `레벨 ${r.to_level}`} 신청 · {REQUEST_STATUS[r.status] ?? r.status} ·{" "}
              <time dateTime={r.created_at}>{formatDateTime(r.created_at)}</time>
              {r.decision_note && <> · {r.decision_note}</>}
              {r.status === "pending" && (
                <AdminForm action={cancelLevelRequestAction.bind(null, r.id)} submitLabel="신청 취소" label={`신청 ${r.id} 취소`} />
              )}
            </li>
          ))}
        </ul>
      )}
      {levels.requestable.length > 0 && !levels.items.some((r) => r.status === "pending") && (
        <AdminForm action={requestLevelAction} submitLabel="승급 신청" label="승급 신청">
          <label htmlFor="level-to">신청할 레벨</label>
          <select id="level-to" name="to_level" required>
            {levels.requestable.map((lv) => (
              <option key={lv} value={lv}>
                {levels.names[String(lv)] ?? `레벨 ${lv}`}({lv})
              </option>
            ))}
          </select>
          <label htmlFor="level-reason">사유</label>
          <textarea id="level-reason" name="reason" rows={3} maxLength={1000} required />
        </AdminForm>
      )}

      <h2>탈퇴</h2>
      <AdminForm action={withdrawAction} submitLabel="탈퇴하기" label="탈퇴" danger>
        <p>탈퇴하면 이메일·비밀번호가 지워지고, 쓴 글과 댓글은 남되 작성자가 &apos;탈퇴 회원&apos;으로 바뀝니다. 되돌릴 수 없습니다.</p>
        <label htmlFor="withdraw-password">비밀번호</label>
        <input id="withdraw-password" name="password" type="password" autoComplete="current-password" required />
        <label>
          <input type="checkbox" name="confirm" required /> 위 내용을 확인했고 탈퇴합니다
        </label>
      </AdminForm>
    </>
  );
}
