import { assertSafeConfig, parseServerConfig } from "@/lib/api/config";

// 서버 인스턴스가 시작될 때 한 번 — 위험한 설정이면 요청을 받기 전에 기동을 멈춘다(설계도 §11)
export function register() {
  assertSafeConfig(parseServerConfig(process.env));
}
