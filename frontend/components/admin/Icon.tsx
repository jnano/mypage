import { createElement } from "react";
import { ICONS, type IconName } from "./icons.gen";

// 관리 화면 아이콘 하나 — 장식이다(aria-hidden). 이름이 필요하면 단추 쪽에 글자나 aria-label 로 준다(지시서 §2.2).
// 모양은 Lucide 선 아이콘, 획 1.8(ProjectM). 크기·색은 스킨(currentColor, [data-slot=admin] … > svg)이 정한다. class 없음(§13.1)
export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      data-icon={name}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {ICONS[name].map(([tag, attrs], i) => createElement(tag, { key: i, ...attrs }))}
    </svg>
  );
}

// 편집기 줄 단추(블록·메뉴 항목·목록 칸)의 글자 → 아이콘. 글자는 그대로 보이고 아이콘은 그 앞에 붙는다(지시서 §2.2 — 모바일에서도 글자와 함께)
export const ROW_ICONS: Partial<Record<string, IconName>> = {
  위로: "arrow-up",
  아래로: "arrow-down",
  빼기: "trash-2",
  설정: "settings",
  "설정 닫기": "x",
};
