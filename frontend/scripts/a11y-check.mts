// 접근성 구조 검사 — 설계도 §13·§16.3-6. 실제 브라우저(Playwright Chromium)로 주요 화면을 열고 axe-core 를 돌린다.
// 규칙: WCAG 2.0·2.1·2.2 A/AA + axe best-practice(랜드마크·제목 단계 등 구조 규칙). 위반이 하나라도 있으면 종료 코드 1.
// 골격은 스타일이 없어(§13.1) 색 대비·크기는 브라우저 기본값이다 — 스킨이 붙으면 --skin 으로 모든 규칙을 다시 돈다.
//
// 전제: next start(APP_ENV=dev, DEV_VIEWER_LOGIN=true) + 개발 시드(scripts/seed_dev)로 띄운 FastAPI.
// 실행: node scripts/a11y-check.mts --base http://localhost:3000 --admin 1 --member 3
import { AxeBuilder } from "@axe-core/playwright";
import { chromium, type Browser, type Page } from "playwright";
import { parseArgs } from "node:util";

const { values } = parseArgs({
  options: {
    base: { type: "string", default: "http://localhost:3000" },
    admin: { type: "string", default: "1" },
    member: { type: "string", default: "3" },
    // 스킨이 붙으면 켠다 — 골격은 스타일이 없어 링크·단추 크기가 브라우저 기본값이다
    skin: { type: "boolean", default: false },
    // 대조군 — 일부러 틀린 화면에서 위반을 잡는지(검사 도구가 실제로 도는지) 확인한다
    "self-test": { type: "boolean", default: false },
  },
});
const base = values.base!;
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
// 골격에서 빼는 규칙: target-size(WCAG 2.5.8) — 스타일이 없어 크기를 브라우저가 정한다('사용자 에이전트 제어' 예외).
// 크기는 스킨의 몫(§13 '터치 대상 44px 목표, 하한 24px', §13.1). 에디터 도구 단추는 이미 24/44px(§8.5 A7)
const SKELETON_EXCLUDED = values.skin ? [] : ["target-size"];
// 외부 동영상 플레이어(제공자의 마크업)는 우리가 고칠 수 없어 검사에서 뺀다. 교차 출처 프레임은 안쪽만 빼는
// 선택자가 듣지 않아(실측) iframe 째로 빼고, 우리 몫인 iframe 제목(frame-title)은 아래에서 직접 확인한다
const THIRD_PARTY_FRAMES = ['iframe[src^="https://www.youtube-nocookie.com/"]'];

interface Finding {
  page: string;
  rule: string;
  impact: string | null | undefined;
  help: string;
  targets: string[];
}

async function open(browser: Browser, member: string | null): Promise<Page> {
  const context = await browser.newContext({ locale: "ko-KR" });
  if (member) await context.addCookies([{ name: "dev_member", value: member, url: base }]);
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  return page;
}

/** 스트리밍이 끝나 '불러오는 중' 자리 표시가 사라질 때까지 */
async function settle(page: Page, ready?: string) {
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => document.querySelectorAll('[data-slot="loading"]').length === 0);
  if (ready) await page.locator(ready).first().waitFor();
}

async function check(page: Page, path: string, label: string, ready?: string): Promise<Finding[]> {
  await page.goto(base + path);
  await settle(page, ready);
  let builder = new AxeBuilder({ page }).withTags(TAGS).disableRules(SKELETON_EXCLUDED);
  for (const frame of THIRD_PARTY_FRAMES) builder = builder.exclude(frame);
  const result = await builder.analyze();
  const untitled = await page.locator(THIRD_PARTY_FRAMES.join(", ")).evaluateAll((els) => els.filter((e) => !e.getAttribute("title")?.trim()).length);
  if (untitled) result.violations.push({ id: "frame-title", impact: "serious", help: "외부 동영상 iframe 에 제목이 있어야 합니다", nodes: [] } as unknown as (typeof result.violations)[number]);
  const findings = result.violations.map((v) => ({
    page: `${label} ${path}`,
    rule: v.id,
    impact: v.impact,
    help: v.help,
    targets: v.nodes.slice(0, 3).map((n) => n.target.join(" ")),
  }));
  console.log(`${findings.length ? "✗" : "✓"} ${label} ${path}${findings.length ? ` — ${findings.length}개 규칙` : ""}`);
  return findings;
}

const browser = await chromium.launch();

if (values["self-test"]) {
  const page = await (await browser.newContext()).newPage(); // axe 는 문맥(context)에서 만든 쪽을 요구한다
  await page.setContent('<html><body><main><img src="data:,"><button></button><h3>제목</h3></main></body></html>');
  const result = await new AxeBuilder({ page }).withTags(TAGS).disableRules(SKELETON_EXCLUDED).analyze();
  await browser.close();
  const got = new Set(result.violations.map((v) => v.id));
  const expected = ["html-has-lang", "image-alt", "button-name", "page-has-heading-one"];
  const missing = expected.filter((r) => !got.has(r));
  console.log(missing.length ? `대조군 실패 — 잡지 못한 규칙: ${missing.join(", ")}` : `대조군 통과 — ${expected.join(", ")} 를 잡았다`);
  process.exit(missing.length ? 1 : 0);
}

const findings: Finding[] = [];
try {
  // 비회원
  const guest = await open(browser, null);
  await guest.goto(base + "/boards/free");
  await settle(guest);
  const postPath = await guest.locator('[data-slot="post-title"] a, [data-slot="post-list"] a[href^="/boards/free/"]').first().getAttribute("href");
  for (const path of ["/", "/boards/free", "/boards/notice", ...(postPath ? [postPath] : []), "/search?q=회의", "/dev/login", "/login", "/signup", "/privacy", "/reset"]) {
    findings.push(...(await check(guest, path, "비회원")));
  }
  // 회원 — 글쓰기(마크다운·리치)·알림·글 보기(댓글 폼)
  const member = await open(browser, values.member!);
  findings.push(...(await check(member, "/boards/free/write", "회원")));
  findings.push(...(await check(member, "/boards/meeting/write", "회원", '[data-slot="editor-content"]')));
  if (postPath) findings.push(...(await check(member, postPath, "회원")));
  findings.push(...(await check(member, "/me/notifications", "회원")));
  findings.push(...(await check(member, "/me/account", "회원")));
  // 운영자 — 관리 화면
  const admin = await open(browser, values.admin!);
  for (const path of [
    "/admin",
    "/admin/boards",
    "/admin/boards/free",
    "/admin/posts",
    "/admin/pending",
    "/admin/comments",
    "/admin/reports",
    "/admin/logs",
    "/admin/settings",
    "/admin/jobs",
    "/admin/members",
    "/admin/members/pending",
    "/admin/member-groups",
    "/admin/level-requests",
    "/admin/privacy-notices",
  ]) {
    findings.push(...(await check(admin, path, "운영자")));
  }
} finally {
  await browser.close();
}

if (findings.length) {
  console.log("\n위반");
  for (const f of findings) console.log(`- [${f.impact}] ${f.rule} — ${f.help}\n  ${f.page}\n  ${f.targets.join("\n  ")}`);
  process.exitCode = 1;
} else {
  console.log("\n위반 없음");
}
