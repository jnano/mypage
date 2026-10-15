import Link from "next/link";
import { Suspense } from "react";
import { reindexAction, updateSettingsAction } from "@/app/admin/actions";
import { AdminForm } from "@/components/admin/AdminForm";
import { AdminProblem } from "@/components/admin/AdminProblem";
import { SettingField } from "@/components/admin/SettingField";
import { fieldValue } from "@/lib/admin/boardFields";
import { adminGet } from "@/lib/admin/load";
import { SETTINGS_SECTIONS, formatLevelNames } from "@/lib/admin/settingsFields";

// 사이트 설정(§14.3) — SEO·스팸 기본·검색·등급 이름표, 전체 재색인. 운영자 전용. 게시판별 덮어쓰기는 게시판 설정에서
export const metadata = { title: "사이트 설정" };

type Setting = { group: string; value: Record<string, unknown> };

export default function SettingsPage() {
  return (
    <section>
      <h1>사이트 설정</h1>
      <Suspense fallback={<p data-slot="loading">불러오는 중…</p>}>
        <Settings />
      </Suspense>
    </section>
  );
}

async function Settings() {
  const groups = ["levels", ...SETTINGS_SECTIONS.map((s) => s.id)];
  const loaded = await Promise.all(groups.map((g) => adminGet<Setting>(`/api/admin/settings/${g}`)));
  const problem = loaded.find((r) => r.problem)?.problem;
  if (problem) return <AdminProblem problem={problem} />;
  const values = Object.fromEntries(loaded.map((r, i) => [groups[i], r.data?.value ?? {}]));
  return (
    <>
      <p>
        알림 수신 설정은 <Link href="/me/notifications">내 알림</Link>에서 바꿉니다(신고 접수·승인 대기 알림 포함).
      </p>
      <AdminForm action={updateSettingsAction.bind(null, "levels")} submitLabel="등급 이름표 저장" label="등급 이름표">
        <fieldset>
          <legend>등급 이름표</legend>
          <label htmlFor="level-names">줄마다 &quot;등급 이름&quot;(0 = 비회원)</label>
          <textarea id="level-names" name="names" rows={5} defaultValue={formatLevelNames((values.levels.names as Record<string, string>) ?? {})} />
        </fieldset>
      </AdminForm>
      {SETTINGS_SECTIONS.map((section) => (
        <AdminForm key={section.id} action={updateSettingsAction.bind(null, section.id)} submitLabel={`${section.title} 저장`} label={section.title}>
          <fieldset>
            <legend>{section.title}</legend>
            {section.fields.map((field) => (
              <SettingField key={field.name} field={field} value={fieldValue(values[section.id], field)} />
            ))}
            <p>
              <label>
                사유(운영 기록) <input name="reason" maxLength={500} />
              </label>
            </p>
          </fieldset>
        </AdminForm>
      ))}
      <h2>검색 색인</h2>
      <p>글 상태·게시판 설정과 검색 색인이 어긋났을 때 전체를 다시 만듭니다. 작업자가 500글씩 차례로 처리합니다.</p>
      <AdminForm action={reindexAction} submitLabel="전체 재색인" label="전체 재색인" />
    </>
  );
}
