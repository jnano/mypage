// 부하 시험(설계도 §15.3·§16.4) — k6. 예산(§15.1)을 thresholds 로 적어 통과·실패를 판정한다.
// 시나리오(SCENARIO): guest ① 비회원 목록 → 글 보기 → 검색 · member ② 회원 목록 → 글쓰기 → 목록 복귀
//                    upload ③ 사진 업로드 · api ④ FastAPI 직접(Server-Timing 으로 서버 시간·쿼리 수·연결 풀 최고치)
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
  api: {
    "server_app_ms{api:list}": ["p(95)<50"], // 목록 API ≤ 50ms
    "server_app_ms{api:post}": ["p(95)<30"], // 글 보기 API ≤ 30ms
    "server_app_ms{api:search}": ["p(95)<150"], // 통합 검색 ≤ 150ms
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
  group(SCENARIO, { guest, member, upload, api }[SCENARIO]);
}
