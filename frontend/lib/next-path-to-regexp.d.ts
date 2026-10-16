// Next 에 묶인 path-to-regexp(타입 선언 없음) — 시험에서 rewrites 의 source 를 Next 와 같은 방식으로 맞춰 보려고 쓴다
declare module "next/dist/compiled/path-to-regexp" {
  export function match(
    path: string,
    options?: { decode?: (value: string) => string },
  ): (pathname: string) => false | { path: string; params: Record<string, string | string[]> };
}
