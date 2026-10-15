// 서버 설정 — 환경 변수 해석과 기동 가드. 순수 함수라 테스트에서 그대로 쓴다(값을 읽는 곳은 lib/server/config.ts)

export type AppEnv = "dev" | "test" | "prod";

export interface ServerConfig {
  backendUrl: string;
  appEnv: AppEnv;
  /** Next 서버 → FastAPI 쓰기에 싣는 공유 비밀(FastAPI INTERNAL_API_SECRET 과 같은 값) */
  internalApiSecret: string;
  /** 개발 로그인 쿠키를 X-Dev-Member 헤더로 바꿀지(ENV=dev 전용, 설계도 §5.1·§11) */
  devViewerLogin: boolean;
  devViewerSecret: string;
}

type Env = Record<string, string | undefined>;

export function parseServerConfig(env: Env): ServerConfig {
  const appEnv = (env.APP_ENV ?? "prod") as AppEnv;
  if (!["dev", "test", "prod"].includes(appEnv)) {
    throw new Error(`APP_ENV 는 dev | test | prod 입니다: ${appEnv}`);
  }
  return {
    backendUrl: env.BACKEND_URL ?? "http://localhost:8000",
    appEnv,
    internalApiSecret: env.INTERNAL_API_SECRET ?? "",
    devViewerLogin: env.DEV_VIEWER_LOGIN === "true",
    devViewerSecret: env.DEV_VIEWER_SECRET ?? "",
  };
}

/** 기동 가드 — FastAPI 의 가드와 같은 규칙. 두 프로세스가 각자의 환경 변수를 읽으므로 양쪽에 둔다 */
export function assertSafeConfig(config: ServerConfig): void {
  if (config.devViewerLogin && config.appEnv !== "dev") {
    throw new Error("DEV_VIEWER_LOGIN 은 APP_ENV=dev 에서만 켤 수 있습니다");
  }
  if (config.devViewerLogin && config.devViewerSecret.length < 16) {
    throw new Error("DEV_VIEWER_LOGIN 을 켜려면 DEV_VIEWER_SECRET(16자 이상)이 필요합니다");
  }
  if (config.appEnv === "prod" && config.internalApiSecret.length < 32) {
    throw new Error("APP_ENV=prod 에서는 INTERNAL_API_SECRET(32자 이상)이 필요합니다");
  }
}
