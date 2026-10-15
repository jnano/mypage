import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// 단위 테스트 — lib/ 의 순수 모듈(fetch 도구·캐시 판정 등). 화면 동작은 빌드와 수동 확인으로
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    include: ["lib/**/*.test.ts"],
    environment: "node",
  },
});
