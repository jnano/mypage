"use client";

import { useEffect, useState, useTransition } from "react";
import { previewAction, type ActionResult } from "@/app/admin/blockActions";
import type { FieldError } from "@/lib/admin/blocks/schema";
import { draftKey } from "@/lib/admin/blocks/tree";
import type { ProblemBody } from "@/lib/api/problem";
import type { PreviewResult } from "./PreviewBlocks";

// 틀·페이지(·메뉴) 편집기가 함께 쓰는 저장·미리보기·되살리기(홈블록 설계도 §4.6·§8)
// - 저장: 통째 PUT + If-Match. 성공하면 서버가 돌려준 트리(새 블록 id 포함)로 화면을 다시 맞춘다
// - 412: 내 변경을 그 탭의 sessionStorage 에 남기고 "다시 불러오기" — 다시 불러온 편집기가 "내 변경 되살리기"를 권한다.
//   되살린 뒤의 저장도 지금 버전으로 다시 비교한다(조용히 덮어쓰지 않는다)
// - sessionStorage 는 개인 PC 편의(공용 PC 에 남지 않게 탭 수명). 막혀 있으면(사생활 보호 창 등) 남기지 못한다고 알린다

export interface Draft<S> {
  savedAt: string;
  baseVersion: number;
  state: S;
}

function readDraft<S>(key: string): Draft<S> | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Draft<S>) : null;
  } catch {
    return null;
  }
}

function writeDraft<S>(key: string, draft: Draft<S> | null): boolean {
  try {
    if (draft) sessionStorage.setItem(key, JSON.stringify(draft));
    else sessionStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function useOwnerEditor<S, T extends { version: number }>({
  kind,
  id,
  version: initialVersion,
  snapshot,
  restore,
  save,
  previewBody,
  onSaved,
}: {
  kind: "layout" | "page" | "menu";
  id: number;
  version: number;
  snapshot: () => S;
  restore: (state: S) => void;
  save: (version: number) => Promise<ActionResult<T>>;
  previewBody?: (asMember: boolean) => unknown;
  onSaved: (data: T) => void;
}) {
  const key = draftKey(kind, id);
  const [version, setVersion] = useState(initialVersion);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [problem, setProblem] = useState<ProblemBody | null>(null);
  const [status, setStatus] = useState("");
  const [conflict, setConflict] = useState(false);
  const [draft, setDraft] = useState<Draft<S> | null>(null);
  const [preview, setPreview] = useState<{ result: PreviewResult; asMember: boolean } | null>(null);
  const [pending, start] = useTransition();

  useEffect(() => {
    setDraft(readDraft<S>(key)); // 브라우저에서만 — 서버 렌더에는 sessionStorage 가 없다
  }, [key]);

  function fail(p: ProblemBody) {
    setProblem(p);
    // 요청 본문 검증(FastAPI)의 경로는 `body.blocks.0.min_level` 꼴 — 트리 검증과 같은 `blocks[0].min_level` 로 맞춘다
    setErrors(((p.errors ?? []) as FieldError[]).map((e) => ({ ...e, field: e.field.replace(/^body\./, "").replace(/\.(\d+)(?=\.|$)/g, "[$1]") })));
    setStatus(p.title);
  }

  function doSave() {
    start(async () => {
      setStatus("저장하는 중…");
      const res = await save(version);
      if (res.problem) {
        if (res.problem.status === 412) {
          const kept = writeDraft(key, { savedAt: new Date().toISOString(), baseVersion: version, state: snapshot() });
          setConflict(true);
          setProblem(res.problem);
          setErrors([]);
          setStatus(
            kept
              ? "다른 사람이 먼저 고쳤습니다. 내 변경은 이 탭에 남겨 두었습니다 — 다시 불러온 뒤 '내 변경 되살리기'를 고르세요."
              : "다른 사람이 먼저 고쳤습니다. 이 브라우저는 내 변경을 남길 수 없습니다 — 다시 불러오기 전에 바꾼 내용을 따로 적어 두세요.",
          );
          return;
        }
        fail(res.problem);
        return;
      }
      writeDraft(key, null);
      setDraft(null);
      setConflict(false);
      setProblem(null);
      setErrors([]);
      setVersion(res.data.version);
      onSaved(res.data);
      setStatus("저장했습니다.");
    });
  }

  function doPreview(asMember: boolean) {
    if (!previewBody) return;
    start(async () => {
      setStatus("미리보기를 만드는 중…");
      const res = await previewAction(previewBody(asMember));
      if (res.problem) {
        fail(res.problem);
        setPreview(null);
        return;
      }
      setProblem(null);
      setErrors([]);
      setPreview({ result: res.data, asMember });
      setStatus(asMember ? "회원 모습 미리보기입니다." : "비회원 모습 미리보기입니다.");
    });
  }

  return {
    version,
    errors,
    problem,
    status,
    pending,
    conflict,
    draft,
    preview,
    save: doSave,
    showPreview: doPreview,
    restoreDraft() {
      if (!draft) return;
      restore(draft.state);
      writeDraft(key, null);
      setDraft(null);
      setStatus("내 변경을 되살렸습니다. 지금 내용과 비교한 뒤 저장하세요.");
    },
    discardDraft() {
      writeDraft(key, null);
      setDraft(null);
      setStatus("남겨 둔 변경을 버렸습니다.");
    },
  };
}
