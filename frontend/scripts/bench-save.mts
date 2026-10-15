// Server Action 저장 p95 — 설계도 §15.1 '글 저장(Server Action 왕복) p95 ≤ 300ms'(1단계 측정).
// 실제 브라우저(Playwright Chromium)로 글쓰기 화면에서 '등록'을 누르고
//   ① Server Action 응답 헤더 도착(저장 완료)까지  ② 새 글 화면으로 옮겨 갈 때까지 를 잰다.
// 예열은 빼고, 요청 수 한도(글쓰기 1분 10회)를 피하려고 측정용 회원 여러 명에게 나눈다.
//
// 전제: next start(APP_ENV=dev, DEV_VIEWER_LOGIN=true) + 측정 DB 로 띄운 FastAPI.
// 실행: node scripts/bench-save.mts --base http://localhost:3000 --members 101,102,… --runs 50 --board free
import { chromium } from "playwright";
import { parseArgs } from "node:util";

const { values } = parseArgs({
  options: {
    base: { type: "string", default: "http://localhost:3000" },
    members: { type: "string" },
    runs: { type: "string", default: "50" },
    warmup: { type: "string", default: "5" },
    board: { type: "string", default: "free" },
  },
});
const base = values.base!;
const members = (values.members ?? "").split(",").filter(Boolean);
const runs = Number(values.runs);
const warmup = Number(values.warmup);
if (members.length === 0) throw new Error("--members 를 주세요(쉼표로 나눈 회원 id)");

const pct = (xs: number[], p: number) => {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.round((p / 100) * (s.length - 1)))];
};

const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();
page.setDefaultTimeout(15_000); // 멈추면 바로 실패하게
const action: number[] = [];
const total: number[] = [];

for (let i = 0; i < warmup + runs; i++) {
  const member = members[i % members.length];
  await context.addCookies([{ name: "dev_member", value: member, url: base }]);
  await page.goto(`${base}/boards/${values.board}/write`);
  await page.fill("#title", `측정 글 ${i}`);
  await page.fill("#content", `저장 측정 본문 ${i}\n\n**굵게** 한 줄`);

  const started = performance.now();
  const actionDone = page.waitForResponse((r) => r.request().method() === "POST" && r.request().headers()["next-action"] !== undefined);
  await page.click('button[type="submit"]');
  // 응답 헤더 도착 = 저장·무효화가 끝나고 redirect 응답이 시작된 시점.
  // (redirect 응답은 새 화면을 같은 응답에 이어 스트리밍하므로 본문 끝은 저장 시점이 아니다)
  await actionDone;
  const tAction = performance.now() - started;
  await page.waitForURL(new RegExp(`/boards/${values.board}/\\d+$`));
  const tTotal = performance.now() - started;
  if (i >= warmup) {
    action.push(tAction);
    total.push(tTotal);
  }
}
await browser.close();

const fmt = (xs: number[]) => `p50 ${pct(xs, 50).toFixed(0)}ms · p95 ${pct(xs, 95).toFixed(0)}ms · 최대 ${Math.max(...xs).toFixed(0)}ms`;
console.log(`Server Action 왕복(n=${action.length}): ${fmt(action)}`);
console.log(`새 글 화면까지(n=${total.length}): ${fmt(total)}`);
