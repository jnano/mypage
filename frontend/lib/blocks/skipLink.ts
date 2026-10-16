// 건너뛰기 링크의 대상 고르기(홈블록 설계도 §3.2) — 클라이언트 이동 뒤 이전 화면이 숨겨진 채(display:none) DOM 에 남아
// main#main 이 여럿일 수 있다. 보이는 본문 하나를 고른다

/** 요소가 보이는가 — checkVisibility 가 없는 브라우저(구형)·jsdom 에서는 조상의 hidden 속성·display:none 을 직접 본다 */
export function isShown(el: HTMLElement): boolean {
  if (typeof el.checkVisibility === "function") return el.checkVisibility();
  for (let e: HTMLElement | null = el; e; e = e.parentElement) {
    if (e.hidden || e.ownerDocument.defaultView?.getComputedStyle(e).display === "none") return false;
  }
  return true;
}

/** 보이는 본문(main#main)에 초점을 옮긴다. 옮겼으면 true — 없으면 링크의 기본 동작(#main)에 맡긴다 */
export function focusVisibleMain(doc: Document): boolean {
  const main = [...doc.querySelectorAll<HTMLElement>("main#main")].find(isShown);
  if (!main) return false;
  if (!main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
  main.focus();
  main.scrollIntoView?.();
  return true;
}
