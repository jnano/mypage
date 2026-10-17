// 접근성 구조 검사 — 설계도 §13·§16.3-6. 실제 브라우저(Playwright Chromium)로 주요 화면을 열고 axe-core 를 돌린다.
// 규칙: WCAG 2.0·2.1·2.2 A/AA + axe best-practice(랜드마크·제목 단계 등 구조 규칙). 위반이 하나라도 있으면 종료 코드 1.
// 골격은 스타일이 없어(§13.1) 색 대비·크기는 브라우저 기본값이다 — 스킨이 모양을 정한 요소(SKINNED)는 빼던 규칙도 돈다. --skin 은 모든 화면·요소에서.
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
    // 모든 화면을 스킨 규칙으로 — 골격만 있는 화면은 링크·단추 크기가 브라우저 기본값이다
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
// 스킨이 붙은 화면과 그 스킨이 모양을 정한 요소 — 그 요소에는 골격에서 빼던 규칙(target-size)도 돈다.
// 관리 화면은 단계마다 넓혔다(관리디자인 지시서 §4): 1단계 단추 → 2단계 골격·폼·안내까지 관리 화면 전체와 그 화면의 건너뛰기 링크
const SKINNED: { prefix: string; targets: string[] }[] = [{ prefix: "/admin", targets: ['[data-slot="admin"]', '[data-slot="skip-link"]'] }];
const skinnedTargets = (path: string) => SKINNED.find(({ prefix }) => path === prefix || path.startsWith(`${prefix}/`))?.targets ?? [];

/** 스킨이 모양을 정한 요소에만 골격에서 빼던 규칙을 돈다(그 요소가 화면에 없으면 돌지 않는다) */
async function skinnedViolations(page: Page, targets: string[]) {
  if (!targets.length || !(await page.locator(targets.join(", ")).count())) return [];
  let builder = new AxeBuilder({ page }).withRules(SKELETON_EXCLUDED);
  for (const t of targets) builder = builder.include(t);
  return (await builder.analyze()).violations;
}
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
  if (!values.skin) result.violations.push(...(await skinnedViolations(page, skinnedTargets(path))));
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
  // 스킨 요소 대조군: 관리 스킨 안의 작은 단추 둘(8px, 붙어 있음) — 관리 화면 대상 목록으로 돌리면 target-size 를 잡아야 한다
  await page.setContent('<html lang="ko"><body><main data-slot="admin"><h1>대조</h1><button style="all:unset;width:8px;height:8px">가</button><button style="all:unset;width:8px;height:8px">나</button></main></body></html>');
  const skinned = await skinnedViolations(page, skinnedTargets("/admin"));
  await browser.close();
  const got = new Set([...result.violations, ...skinned].map((v) => v.id));
  const expected = ["html-has-lang", "image-alt", "button-name", "page-has-heading-one", ...(values.skin ? [] : ["target-size"])];
  const missing = expected.filter((r) => !got.has(r));
  console.log(missing.length ? `대조군 실패 — 잡지 못한 규칙: ${missing.join(", ")}` : `대조군 통과 — ${expected.join(", ")} 를 잡았다`);
  process.exit(missing.length ? 1 : 0);
}

const findings: Finding[] = [];
// 홈블록 화면 — 게시판 기반 목록과 따로 묶는다(통합 설계도가 게시판 범위 화면 수를 '전체 − 이 묶음'으로 센다)
const HOMEBLOCK_GUEST_PATHS = ["/sample", "/dev/blocks", "/no-such-page"]; // 없는 주소 — 대체 틀 머리만 쓰는 not-found(걸음 8 결정 ①)
const HOMEBLOCK_ADMIN_LISTS = ["/admin/layouts", "/admin/pages", "/admin/menus"]; // 목록 + 첫 편집 화면
try {
  // 비회원
  const guest = await open(browser, null);
  await guest.goto(base + "/boards/free");
  await settle(guest);
  const postPath = await guest.locator('[data-slot="post-title"] a, [data-slot="post-list"] a[href^="/boards/free/"]').first().getAttribute("href");
  for (const path of ["/", "/boards/free", "/boards/notice", ...(postPath ? [postPath] : []), "/search?q=회의", "/dev/login", "/login", "/signup", "/privacy", "/reset"]) {
    findings.push(...(await check(guest, path, "비회원")));
  }
  // 비회원 글쓰기(설계도 §6.3) — 손님 게시판(시드 open, 쓰기 등급 0)의 글쓰기 폼과 비회원 글의 비밀번호 폼
  findings.push(...(await check(guest, "/boards/open/write", "비회원")));
  await guest.goto(base + "/boards/open");
  await settle(guest);
  const guestPost = await guest.locator('[data-slot="post-list"] a[href^="/boards/open/"]').first().getAttribute("href");
  if (guestPost) findings.push(...(await check(guest, `${guestPost}/guest?purpose=edit`, "비회원")));
  // 회원 — 글쓰기(마크다운·리치)·알림·글 보기(댓글 폼)·내 목록 셋
  const member = await open(browser, values.member!);
  findings.push(...(await check(member, "/boards/free/write", "회원")));
  findings.push(...(await check(member, "/boards/meeting/write", "회원", '[data-slot="editor-content"]')));
  if (postPath) findings.push(...(await check(member, postPath, "회원")));
  findings.push(...(await check(member, "/me/notifications", "회원")));
  findings.push(...(await check(member, "/me/account", "회원")));
  // 내 목록(설계도 §6.2)
  for (const path of ["/me/posts", "/me/comments", "/me/scraps"]) findings.push(...(await check(member, path, "회원")));
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

  // ── 홈블록 화면(홈블록 설계도 §10) — 게시판 기반 화면 수(통합 설계도 §0.4 의 35)와 따로 센다: 출력에 [홈블록] 표식 ──
  // 시드(scripts/seed_homeblock.py)의 견본 페이지·틀·페이지·메뉴. 편집 화면 id 는 목록의 첫 링크에서(시드 순서를 하드코딩하지 않는다)
  // /dev/blocks 는 그림·배너처럼 시드가 실제 파일 없이 만들 수 없는 블록의 견본이라 남긴다
  for (const path of HOMEBLOCK_GUEST_PATHS) findings.push(...(await check(guest, path, "[홈블록] 비회원")));
  for (const path of HOMEBLOCK_ADMIN_LISTS) {
    findings.push(...(await check(admin, path, "[홈블록] 운영자")));
    const editor = await admin.locator(`main a[href^="${path}/"]`).first().getAttribute("href");
    if (editor) findings.push(...(await check(admin, editor, "[홈블록] 운영자")));
  }
  findings.push(...(await check(admin, "/admin/blocks", "[홈블록] 운영자")));
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
