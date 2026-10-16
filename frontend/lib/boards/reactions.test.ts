import { describe, expect, it } from "vitest";
import { optimistic, settle } from "./reactions";

describe("추천·스크랩 낙관적 갱신(설계도 §6.1)", () => {
  it("켜면 +1, 끄면 −1, 같은 상태는 그대로, 0 아래로 가지 않는다", () => {
    expect(optimistic({ on: false, count: 3 }, true)).toEqual({ on: true, count: 4 });
    expect(optimistic({ on: true, count: 4 }, false)).toEqual({ on: false, count: 3 });
    expect(optimistic({ on: true, count: 4 }, true)).toEqual({ on: true, count: 4 });
    expect(optimistic({ on: true, count: 0 }, false)).toEqual({ on: false, count: 0 });
    expect(optimistic({ on: false, count: null }, true)).toEqual({ on: true, count: null });
  });

  it("서버 값으로 바로잡고, 수가 없으면 지금 수를 둔다", () => {
    expect(settle({ on: true, count: 4 }, true, 9)).toEqual({ on: true, count: 9 });
    expect(settle({ on: false, count: 3 }, false, undefined)).toEqual({ on: false, count: 3 });
    expect(settle({ on: true, count: null }, true, 9)).toEqual({ on: true, count: null });
  });
});
