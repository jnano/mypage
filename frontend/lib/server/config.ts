import "server-only";
import { assertSafeConfig, parseServerConfig, type ServerConfig } from "@/lib/api/config";

let cached: ServerConfig | null = null;

/** 요청 시점에 읽는다(빌드 때 값으로 굳지 않게 — 호출부는 요청 시점 코드여야 한다) */
export function serverConfig(): ServerConfig {
  if (!cached) {
    cached = parseServerConfig(process.env);
    assertSafeConfig(cached);
  }
  return cached;
}
