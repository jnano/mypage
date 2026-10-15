// 에디터 의미 토큰 — 원본은 backend/app/editor/tokens.py, 이 폴더의 tokens.gen.json 은 생성 파일(설계도 §8.3)
import generated from "./tokens.gen.json";

export const editorTokens = generated;

export type VideoProvider = keyof typeof generated.videoProviders;

/** 한 줄 주소 → 동영상 토큰. 서버 변환(§8.4)과 같은 정규식을 쓴다 */
export function matchVideo(url: string): { provider: VideoProvider; videoId: string } | null {
  for (const [provider, spec] of Object.entries(generated.videoProviders)) {
    for (const pattern of spec.urlPatterns) {
      const m = new RegExp(pattern).exec(url.trim());
      if (m) return { provider: provider as VideoProvider, videoId: m[1] };
    }
  }
  return null;
}
