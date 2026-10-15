import { describe, expect, it } from "vitest";
import { editorTokens, matchVideo } from "./tokens";

describe("에디터 토큰(생성 파일)", () => {
  it("백엔드 원본의 값을 담고 있다", () => {
    expect(editorTokens.sanitizerVersion).toBeGreaterThanOrEqual(1);
    expect(editorTokens.tags.figure).toContain("data-attachment-id");
    expect(editorTokens.urlSchemes).toEqual(["http", "https", "mailto"]);
  });

  it("동영상 주소를 서버와 같은 규칙으로 알아본다", () => {
    expect(matchVideo("https://youtu.be/dQw4w9WgXcQ")).toEqual({
      provider: "youtube",
      videoId: "dQw4w9WgXcQ",
    });
    expect(matchVideo("https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ")?.videoId).toBe(
      "dQw4w9WgXcQ",
    );
    expect(matchVideo("https://vimeo.com/123")).toBeNull();
    expect(matchVideo("영상: https://youtu.be/dQw4w9WgXcQ")).toBeNull();
  });
});
