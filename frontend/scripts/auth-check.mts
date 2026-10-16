// 인증 점검(실제 브라우저) — 검토 v3 R-6 두 건 + 인증 운영 공개 조건(인증 설계도 §1: Server Action 경로에서 FastAPI 가
// 실제 클라이언트 IP 를 받는다). 전제: next start(APP_ENV=dev) + 개발 시드(scripts.seed_dev)로 띄운 FastAPI, psql.
// 실행: node scripts/auth-check.mts --base http://localhost:3000 --db postgresql://mypage:mypage@localhost:5432/mypage
import { execFileSync } from "node:child_process";
import { parseArgs } from "node:util";
import { chromium, type Browser, type BrowserContext } from "playwright";

const { values } = parseArgs({
  options: {
    base: { type: "string", default: "http://localhost:3000" },
    db: { type: "string", default: "postgresql://mypage:mypage@localhost:5432/mypage" },
    psql: { type: "string", default: "psql" },
    // 개발 시드의 회원(로컬 개발 DB 를 채움 스크립트로 올렸다면 m{id}@example.test)
    email: { type: "string", default: "member1@example.test" },
  },
});
const base = values.base!;
const PASSWORD = "dev-password-0123456789"; // 개발 시드의 비밀번호(backend/README.md '개발')
const EMAIL = values.email!;
let failed = 0;

function sql(query: string): string {
  return execFileSync(values.psql!, [values.db!, "-tAqc", query], { encoding: "utf8" }).trim();
}

function check(ok: boolean, label: string) {
  console.log(`${ok ? "✓" : "✗"} ${label}`);
  if (!ok) failed++;
}

async function login(context: BrowserContext, email: string, password: string, next = "/") {
  const page = await context.newPage();
  await page.goto(`${base}/login?next=${encodeURIComponent(next)}`);
  await page.fill("#login-email", email);
  await page.fill("#login-password", password);
  await page.click("form[data-slot=login-form] button");
  return page;
}

async function sessionCookie(context: BrowserContext): Promise<boolean> {
  return (await context.cookies()).some((c) => c.name === "session" || c.name === "__Host-session");
}

async function revokeAll(email: string) {
  sql(`UPDATE sessions SET revoked_at = now() WHERE revoked_at IS NULL AND member_id = (SELECT id FROM members WHERE email = '${email}')`);
}

const browser: Browser = await chromium.launch();
try {
  // 1. 실제 IP — nginx 가 덮어쓴 X-Real-IP 를 Next 가 X-Client-IP 로 넘기고, FastAPI 가 그 IP 로 센다(로그인 = Server Action)
  const ip = "203.0.113.77";
  const viaProxy = await browser.newContext({ extraHTTPHeaders: { "x-real-ip": ip } });
  const page = await login(viaProxy, EMAIL, "wrong password for check");
  await page.waitForSelector("text=이메일 또는 비밀번호가 맞지 않습니다");
  const counted = Number(sql(`SELECT count(*) FROM rate_limit_counters WHERE key = 'auth.login_ip:${ip}'`));
  check(counted === 1, `Server Action 경로에서 FastAPI 가 본 IP = ${ip}(Next 주소가 아님)`);
  await viaProxy.close();

  // 2. 폐기된 세션 쿠키로 게시판 → 쿠키가 지워지고 같은 화면이 비회원으로(스트리밍 중 redirect — meta 로 이동)
  const ctx = await browser.newContext();
  let p = await login(ctx, EMAIL, PASSWORD, "/boards/free");
  await p.waitForURL(`${base}/boards/free`);
  check(await sessionCookie(ctx), "로그인 뒤 세션 쿠키");
  await revokeAll(EMAIL);
  await p.goto(`${base}/boards/free`);
  await p.waitForURL(`${base}/boards/free`);
  await p.waitForSelector("header[data-slot=site-header] >> text=로그인");
  check(!(await sessionCookie(ctx)), "게시판: 폐기된 쿠키가 지워지고 같은 화면(비회원)");

  // 3. 같은 상태로 개인 화면 → 쿠키를 지우고 로그인 화면으로(돌아올 곳 = 그 화면)
  p = await login(ctx, EMAIL, PASSWORD, "/me/notifications");
  await p.waitForURL(`${base}/me/notifications`);
  await revokeAll(EMAIL);
  await p.goto(`${base}/me/notifications`);
  await p.waitForURL(`${base}/login?next=%2Fme%2Fnotifications`);
  check(!(await sessionCookie(ctx)), "개인 화면: 쿠키를 지우고 /login?next=/me/notifications");

  // 4. 다른 사이트가 부른 /auth/expired 는 쿠키를 지우지 않는다(검토 v3 R-5)
  p = await login(ctx, EMAIL, PASSWORD, "/search");
  await p.waitForURL(`${base}/search`);
  const res = await ctx.request.get(`${base}/auth/expired?next=%2F`, { headers: { "sec-fetch-site": "cross-site" }, maxRedirects: 0 });
  const cleared = (res.headers()["set-cookie"] ?? "").includes("session=");
  check(res.status() === 303 && !cleared, "다른 사이트에서 부른 /auth/expired 는 쿠키를 지우지 않는다");
  await ctx.close();

  // 5. 조회 신호(설계도 §6.1) — 서로 다른 실제 IP 의 비회원이 Route Handler 를 거쳐 따로 세어지고, 조회 쿠키가 심어진다.
  //    자동화 브라우저는 ViewBeacon 이 보내지 않으므로(navigator.webdriver) 화면에서 직접 한 번 부른다
  const postId = sql(
    "SELECT p.id FROM posts p JOIN boards b ON b.id = p.board_id WHERE b.slug = 'free' AND p.status = 'published' AND NOT p.is_secret AND NOT p.is_blinded ORDER BY p.id LIMIT 1",
  );
  check(postId !== "", "조회 점검용 공개 글이 시드에 있다");
  for (const viewer of ["203.0.113.81", "203.0.113.82"]) {
    const vctx = await browser.newContext({ extraHTTPHeaders: { "x-real-ip": viewer } });
    const vp = await vctx.newPage();
    await vp.goto(`${base}/boards/free/${postId}`);
    const status = await vp.evaluate((id) => fetch(`/api/posts/${id}/view`, { method: "POST" }).then((r) => r.status), postId);
    const n = Number(sql(`SELECT coalesce(sum(count), 0) FROM rate_limit_counters WHERE key = 'post.view:${viewer}'`));
    const hasCookie = (await vctx.cookies()).some((c) => c.name.endsWith("view_id") && c.httpOnly);
    check(status === 204 && n === 1 && hasCookie, `조회: IP ${viewer} 가 따로 세어지고 조회 쿠키(HttpOnly)가 심어진다`);
    const cross = await vctx.request.post(`${base}/api/posts/${postId}/view`, { headers: { origin: "https://elsewhere.example", "sec-fetch-site": "cross-site" } });
    check(cross.status() === 403, "조회: 다른 사이트가 부르면 403");
    await vctx.close();
  }
} finally {
  await browser.close();
  sql("DELETE FROM rate_limit_counters WHERE key LIKE 'auth.%' OR key LIKE 'post.view:%'");
}
console.log(failed ? `\n인증 점검 실패 ${failed}건` : "\n인증 점검 통과");
process.exitCode = failed ? 1 : 0;
