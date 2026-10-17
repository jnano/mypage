// 부하 시험(설계도 §15.3·§16.4) — k6. 예산(§15.1)을 thresholds 로 적어 통과·실패를 판정한다.
// 시나리오(SCENARIO): guest ① 비회원 목록 → 글 보기 → 검색 · member ② 회원 목록 → 글쓰기 → 목록 복귀
//                    upload ③ 사진 업로드 · api ④ FastAPI 직접(Server-Timing 으로 서버 시간·쿼리 수·연결 풀 최고치)
//                    home ⑤ 홈블록(홈블록 설계도 §12) — 비회원이 최대 구성 페이지·게시판 화면(블록 틀)·첫 화면을 보고, VU 1 은 글을 쓴다
//                      (글이 쓰이면 동적 블록이 있는 틀 묶음이 만료된다 — 캐시 적중 간접 지표·M-2 판단). 측정 DB mypage_hb_bench + seed_blocks
// 전제: 개발 로그인(ENV=dev·APP_ENV=dev)으로 띄운 측정 스택 + 측정 DB(mypage_bench).
// 회원 글 저장은 Server Action 이 FastAPI 에 보내는 것과 같은 요청(POST + 내부 비밀 + 개발 헤더)을 직접 보내 'FastAPI 쓰기 p95' 로 본다.
//   Server Action 번호는 빌드마다 바뀌어 스크립트로 부를 수 없다 — 'Server Action 왕복 p95 ≤ 300ms' 예산은 Playwright(bench-save.mts)로 따로 판정한다.
// 비밀 값(INTERNAL_API_SECRET·DEV_VIEWER_SECRET)은 -e 로만 넘긴다(저장소에 적지 않는다).
// 실행 예: k6 run -e SCENARIO=guest -e BASE=http://localhost:8080 frontend/scripts/k6/load.js
import http from "k6/http";
import { check, group, sleep } from "k6";
import { parseHTML } from "k6/html";
import { Trend } from "k6/metrics";

const BASE = __ENV.BASE || "http://localhost:8080";
const API = __ENV.API || "http://127.0.0.1:8000";
const SCENARIO = __ENV.SCENARIO || "guest";
const VUS = Number(__ENV.VUS || 20);
const DURATION = __ENV.DURATION || "60s";
const MEMBERS = (__ENV.MEMBERS || "3,5,6").split(",");
const DEV_SECRET = __ENV.DEV_VIEWER_SECRET || "";
const INTERNAL = __ENV.INTERNAL_API_SECRET || "";
const BOARDS = (__ENV.BOARDS || "free,qna,consult").split(",");
const PHOTO = __ENV.PHOTO ? open(__ENV.PHOTO, "b") : null;

const serverApp = new Trend("server_app_ms", true);
const serverDb = new Trend("server_db_ms", true);
const serverQueries = new Trend("server_queries");
const poolPeak = new Trend("pool_peak");

// §15.1 예산 — 화면 단위로 옮긴 값은 [설계판단](보고서에 근거)
const THRESHOLDS = {
  guest: {
    "http_req_waiting{page:list}": ["p(95)<100"], // 비회원 목록 TTFB(캐시 적중) ≤ 100ms
    "http_req_waiting{page:post}": ["p(95)<100"],
    "http_req_waiting{page:search}": ["p(95)<300"], // 검색 API ≤ 150ms + 화면
    http_req_failed: ["rate<0.01"],
  },
  member: {
    "http_req_waiting{page:list}": ["p(95)<300"],
    "http_req_duration{api:save}": ["p(95)<300"], // FastAPI 쓰기(글 저장) — 화면 예산 300ms 를 넘지 않는지만
    http_req_failed: ["rate<0.01"],
  },
  upload: {
    "http_req_duration{page:upload}": ["p(95)<1500"], // 사진 1장 5MB ≤ 1.5s
    http_req_failed: ["rate<0.01"],
  },
  // API p95 예산(목록 50·글 보기 30·검색 150ms)은 순차 서버 내부 시간 기준이라(§15.1) 여기서 판정하지 않는다 —
  // 동시 부하의 API 시간·풀 최고치는 진단값(프로세스 수·CPU·연결 풀). 순차 판정은 backend/scripts/bench_api.py
  home: {
    "http_req_waiting{page:home}": ["p(95)<100"], // 비회원 첫 화면 TTFB(캐시 적중) ≤ 100ms(홈블록 §12)
    "http_req_waiting{page:block-page}": ["p(95)<100"], // 최대 구성 페이지 — 같은 예산을 적용해 본다[설계판단]
    "http_req_waiting{page:block-board}": ["p(95)<100"], // 블록 틀의 게시판 목록
    http_req_failed: ["rate<0.01"],
  },
  api: {
    // 아래 세 칸은 판정이 아니라 요약에 p95 를 내려고 둔 넉넉한 경계
    "server_app_ms{api:list}": ["p(95)<10000"],
    "server_app_ms{api:post}": ["p(95)<10000"],
    "server_app_ms{api:search}": ["p(95)<10000"],
    "server_queries": ["max<=8"], // 화면당 쿼리 ≤ 8
    http_req_failed: ["rate<0.01"],
  },
};

export const options = {
  scenarios: { main: { executor: "constant-vus", vus: SCENARIO === "upload" ? Math.min(VUS, 4) : VUS, duration: DURATION } },
  thresholds: THRESHOLDS[SCENARIO],
  summaryTrendStats: ["avg", "p(50)", "p(95)", "p(99)", "max", "count"],
};

function devHeader(member) {
  return `${member}; key=${DEV_SECRET}`;
}

function postIds(html) {
  const ids = [];
  parseHTML(html)
    .find('a[href^="/boards/"]')
    .each((_, a) => {
      const m = /^\/boards\/[a-z0-9-]+\/(\d+)$/.exec(a.attributes().href?.value || "");
      if (m) ids.push(m[1]);
    });
  return ids;
}

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

const WORDS = ["회의", "안내", "모집", "일정", "자료", "공지", "질문"];

function guest() {
  const board = pick(BOARDS);
  const page = 1 + Math.floor(Math.random() * 3);
  const list = http.get(`${BASE}/boards/${board}?page=${page}`, { tags: { page: "list" } });
  check(list, { "목록 200": (r) => r.status === 200 });
  const ids = postIds(list.body || "");
  if (ids.length) {
    const post = http.get(`${BASE}/boards/${board}/${pick(ids)}`, { tags: { page: "post" } });
    check(post, { "글 200": (r) => r.status === 200 });
  }
  const search = http.get(`${BASE}/search?q=${encodeURIComponent(pick(WORDS))}`, { tags: { page: "search" } });
  check(search, { "검색 200": (r) => r.status === 200 });
  sleep(0.5);
}

function member() {
  const id = MEMBERS[(__VU - 1) % MEMBERS.length];
  const jar = http.cookieJar();
  jar.set(BASE, "dev_member", id);
  const list = http.get(`${BASE}/boards/free`, { tags: { page: "list" } });
  check(list, { "목록 200": (r) => r.status === 200 });
  http.get(`${BASE}/boards/free/write`, { tags: { page: "write" } });
  const body = JSON.stringify({ title: `부하 시험 글 ${__VU}-${__ITER}`, content: `회의 안내 본문 ${Date.now()}` });
  const saved = http.post(`${API}/api/boards/free/posts`, body, {
    tags: { api: "save" },
    headers: { "content-type": "application/json", "X-Dev-Member": devHeader(id), "X-Internal-Secret": INTERNAL },
  });
  check(saved, { "저장 201": (r) => r.status === 201 });
  const back = http.get(`${BASE}/boards/free`, { tags: { page: "list" } });
  check(back, { "복귀 200": (r) => r.status === 200 });
  sleep(6); // 회원 한 명의 글쓰기 한도(1분 10회) 안에서
}

// 홈블록(⑤) — VU 1 은 글쓴이(6초마다 FastAPI 로 글 저장 — outbox 작업자가 Next 태그를 만료), 나머지는 비회원 화면
const HOME_PAGES = (__ENV.HOME_PAGES || "/bench-max").split(",");
function home() {
  if (__VU === 1) {
    const id = MEMBERS[0];
    const body = JSON.stringify({ title: `홈블록 측정 글 ${__ITER}`, content: `안내 본문 ${Date.now()}` });
    const saved = http.post(`${API}/api/boards/free/posts`, body, {
      tags: { api: "save" },
      headers: { "content-type": "application/json", "X-Dev-Member": devHeader(id), "X-Internal-Secret": INTERNAL },
    });
    check(saved, { "저장 201": (r) => r.status === 201 });
    // 화면의 Server Action 은 저장 응답의 무효화 태그를 updateTag 로 바로 적용한다(설계도 §3.4). k6 는 FastAPI 를 직접 부르므로
    // 같은 태그를 작업자용 재검증 경로(즉시 만료)로 보내 흉내 낸다 — 이게 없으면 캐시가 끝까지 적중해 적중률이 부풀려진다
    const inv = saved.status === 201 ? saved.json("invalidate") : null;
    if (inv) {
      const send = () =>
        http.post(`${BASE}/api/revalidate`, JSON.stringify(inv), {
          tags: { api: "revalidate" },
          headers: { "content-type": "application/json", "X-Internal-Secret": INTERNAL },
        });
      // 6초 쉰 뒤의 연결 재사용은 Next 의 keep-alive(5초)가 이미 닫았을 수 있다(상태 0) — 측정 도구 쪽 일이라 한 번 다시 보낸다
      let res = send();
      if (res.status === 0) res = send();
      if (!check(res, { "재검증 200": (r) => r.status === 200 })) console.warn(`재검증 실패 ${res.status} ${String(res.body).slice(0, 200)}`);
    }
    sleep(6);
    return;
  }
  const first = http.get(`${BASE}/`, { tags: { page: "home" } });
  check(first, { "첫 화면 200": (r) => r.status === 200 });
  const page = http.get(`${BASE}${pick(HOME_PAGES)}`, { tags: { page: "block-page" } });
  check(page, { "페이지 200": (r) => r.status === 200 });
  const board = http.get(`${BASE}/boards/${pick(BOARDS)}`, { tags: { page: "block-board" } });
  check(board, { "게시판 200": (r) => r.status === 200 });
  sleep(0.5);
}

function upload() {
  const id = MEMBERS[(__VU - 1) % MEMBERS.length];
  const jar = http.cookieJar();
  jar.set(BASE, "dev_member", id);
  const res = http.post(`${BASE}/api/uploads?board=free`, PHOTO, {
    tags: { page: "upload" },
    // 업로드 Route Handler 는 같은 출처의 Origin 을 요구한다(CSRF, lib/api/origin.ts) — 브라우저처럼 싣는다
    headers: { origin: BASE, "content-type": "image/jpeg", "x-upload-filename": "load.jpg", "idempotency-key": `${__VU}-${__ITER}-${Date.now()}` },
  });
  check(res, { "업로드 201": (r) => r.status === 201 });
  sleep(2.1); // 회원 한 명의 업로드 한도(1분 30회) 안에서
}

function timed(res, api) {
  const m = /app;dur=([\d.]+), db;dur=([\d.]+);desc="q=(\d+)"(?:, pool;desc="peak=(\d+)\/(\d+)")?/.exec(res.headers["Server-Timing"] || "");
  if (!m) return;
  serverApp.add(Number(m[1]), { api });
  serverDb.add(Number(m[2]), { api });
  serverQueries.add(Number(m[3]), { api });
  if (m[4]) poolPeak.add(Number(m[4]), { api });
}

function api() {
  const board = pick(BOARDS);
  const list = http.get(`${API}/api/boards/${board}/page?page=${1 + Math.floor(Math.random() * 5)}`, { tags: { api: "list" } });
  timed(list, "list");
  const posts = (list.json("posts") || []).map((p) => p.id);
  // 비밀·등급 제한 글은 비회원에게 403 — 예상된 응답
  if (posts.length) timed(http.get(`${API}/api/posts/${pick(posts)}/page`, { tags: { api: "post" }, responseCallback: http.expectedStatuses(200, 403) }), "post");
  timed(http.get(`${API}/api/search?q=${encodeURIComponent(pick(WORDS))}`, { tags: { api: "search" } }), "search");
}

export default function () {
  group(SCENARIO, { guest, member, upload, api, home }[SCENARIO]); // home 은 SCENARIO=home 일 때만(기본 guest — 게시판 기반 부하 측정 재현 그대로)
}
