# mypage — 프로젝트 규칙

전역 규칙(`~/.claude/CLAUDE.md`)을 따르며, 이 문서는 프로젝트 고유 정보만 담는다.
문서(계획서·보고서 등)는 `~/projects/mypage/doc/` 에 둔다 — 이 저장소(`src`)에 두지 않는다.

## 기술 스택
- 프론트엔드: Next.js 16 (App Router) · React 19 · TypeScript — `frontend/` (CSS 프레임워크 없음: 골격은 class 없는 시맨틱 HTML + data-slot, 모양은 스킨 — 설계도 §13.1)
  - Next 16 은 학습 데이터와 다를 수 있다. 코드 작성 전 `frontend/node_modules/next/dist/docs/` 확인 (`frontend/AGENTS.md`)
- 백엔드: FastAPI · Python 3.13 · **uv** (pip/venv 직접 사용 금지) — `backend/`
- DB: PostgreSQL 18 (Postgres.app) · SQLAlchemy 2 **async** + asyncpg · Alembic(async 템플릿)

## 구조
```
frontend/            Next.js 앱. /api/* 는 next.config.ts rewrites 로 백엔드에 프록시
  lib/editor/tokens.gen.json  에디터 토큰(생성 파일 — 직접 고치지 않는다, scripts/gen_editor_tokens.py)
  app/boards/        라우트(목록·글 보기·글쓰기·수정) + actions.ts(Server Action 쓰기 → updateTag)
  app/dev/login/     개발 로그인(APP_ENV=dev + DEV_VIEWER_LOGIN 전용)
  components/boards/ 헤드리스 구조 컴포넌트 — 시맨틱 HTML + data-slot, class·스타일 없음(설계도 §13.1)
  lib/server/        서버 전용: backend.ts(publicGet=쿠키 금지 / personalGet·personalSend) · boards.ts(쪽 단위 캐시 판정) · invalidate.ts
  lib/boards/        순수 로직(plan.ts 캐시 판정)·응답 타입 — Vitest 대상
  instrumentation.ts 기동 가드(개발 로그인은 dev 전용, prod 는 INTERNAL_API_SECRET 필수)
backend/
  app/main.py        FastAPI 앱. 모든 라우터는 prefix="/api"
  app/core/config.py 설정 (pydantic-settings, backend/.env)
  app/db/            base.py(Base·제약 이름 규칙) · session.py(engine, get_db) · models.py(모델 등록)
  app/models/        ORM 모델(설계도 §4 와 일대일). 관계는 모두 lazy="raise", 열거형 값은 enums.py
  app/auth/          Viewer(보는 사람)·get_viewer — 골격은 개발용 헤더(ENV=dev 전용)
  app/permissions/   권한 판정 한 곳: load_board_roles(DB) · can/post_mask(순수) · 목록/열람 판정 절(SQL)
  app/core/problems.py  오류 응답(RFC 9457) — 모든 API 공용
  app/core/          rate_limit(UNLOGGED 고정 창) · idempotency · outbox · invalidation(§3.4 무효화 표) · threads(작업별 한도)
  app/editor/        본문 파이프라인: tokens(원본) · markdown(서버 변환 한 곳) · sanitize(nh3) · render(읽기용) · content(공용 진입점)
  app/boards/        게시판 JSONB 설정 형식·기본값(settings.py)
  app/posts/         queries(읽기, 판정 절 경유) · service(쓰기) · present(응답 모양) · schemas(요청)
  scripts/seed_dev.py  개발용 시드 — `uv run python -m scripts.seed_dev`
  alembic/           마이그레이션 (env.py 가 settings.database_url 사용)
  tests/             pytest (conftest 가 테스트 DB 를 비우고 마이그레이션을 처음부터 적용한다)
                     schema_spec.py = 설계도 §4 를 옮긴 대조 기준 — §4 를 바꾸면 같이 바꾼다
scripts/ci/          CI 검사 스크립트 (도메인 중립 등)
.github/workflows/   GitHub Actions — 금지어 검사 + 백엔드 테스트(postgres:18)
```

## 서버 실행
```bash
# 백엔드 (포트 8000)
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000
# 프론트엔드 (포트 3000)
cd frontend && npm install && npm run dev
```
확인: `http://localhost:3000/api/health` · `/api/health/db`
- 로컬 개발 설정: `backend/.env` 와 `frontend/.env.local` 에 같은 `INTERNAL_API_SECRET`·`DEV_VIEWER_SECRET`, 백엔드 `DEV_VIEWER_HEADER=true`, 프런트 `APP_ENV=dev`·`DEV_VIEWER_LOGIN=true`(각 `.env.example` 참고)
- 개발 로그인: `http://localhost:3000/dev/login` 에서 회원 번호 입력(시드: `cd backend && uv run python -m scripts.seed_dev`)
- 캐시 동작 확인은 `next dev` 가 아니라 `npm run build && npx next start`(dev 는 자체 캐시를 따로 쓴다)
- 쓰기 경계: 브라우저는 FastAPI 에 직접 쓰지 못한다(내부 비밀 헤더 필수). 쓰기는 Server Action / Route Handler 로만

## 테스트
```bash
cd backend && uv run pytest -q              # 테스트 DB: mypage_test (TEST_DATABASE_URL 로 변경)
python3 scripts/ci/check_neutral_terms.py   # 도메인 중립 검사 (저장소 루트에서, --self-test 는 대조군)
python3 scripts/ci/check_post_clause.py     # select(Post) 가 판정 절을 거치는지 (--self-test 는 대조군)
python3 scripts/gen_editor_tokens.py --check  # 에디터 토큰 생성 파일이 원본과 같은지 (인자 없이 실행하면 다시 생성)
cd frontend && npm run typecheck && npm test && npm run build   # 프런트: 타입 검사·Vitest·빌드(백엔드 없이 — 빌드 때 FastAPI 를 부르지 않는다)
```
- 테스트는 개발 DB(`mypage`)를 쓰지 않는다. conftest 는 DB 이름이 `_test` 로 끝나지 않으면 시작을 거부한다.
- 테스트 DB 만들기(최초 1회): `/Applications/Postgres.app/Contents/Versions/18/bin/createdb -h localhost mypage_test`

## 환경 변수
- `backend/.env` — `.env.example` 복사 후 수정 (`APP_NAME`, `DEBUG`, `DATABASE_URL`)
- `frontend/.env.local` — 선택. `BACKEND_URL` (기본 `http://localhost:8000`)

## DB
- DB: `mypage` · user: `taehunkang` · host: `localhost:5432` (로컬은 비밀번호 없음)
- URL: `postgresql+asyncpg://taehunkang@localhost:5432/mypage`
- 새 모델은 `app/db/models.py` 에서 import 되도록 해야 autogenerate 가 인식한다
- 마이그레이션: `cd backend && uv run alembic revision --autogenerate -m "..." && uv run alembic upgrade head`
- **pg_dump 는 v18 경로를 쓴다**: PATH 의 기본 `pg_dump` 는 16 이라 서버(18)와 버전 불일치로 실패한다
  `/Applications/Postgres.app/Contents/Versions/18/bin/pg_dump -h localhost --schema-only mypage`

## 개발 원칙

### 1. API 통합
- 게시판 형식(일반·갤러리·공지·한 줄·자료실 등)마다 별도 API 를 만들지 않는다. 모든 게시판은 같은 게시판·글 API(`/api/boards/{slug}/posts`, `/api/posts/{id}` …)를 쓴다.
- 형식 차이는 게시판 설정(`kind`·`display`·`meta`)과 응답 칸 선택으로 처리한다. 공지도 시스템 게시판(`slug='notice'`)일 뿐 전용 경로가 없다.
- 오류 형식(RFC 9457)·권한 판정·입력 검증은 모든 API 가 같은 모듈을 쓴다.

### 2. 모듈 재사용과 성능 경계
- 같은 동작을 하는 모듈은 하나만 둔다. 새로 만들기 전에 기존 모듈을 먼저 찾는다.
- 다음 분리는 중복이 아니라 **성능 경계**다. 합치지 않는다.
  1. 여러 건 / 한 건: 여러 건 함수를 기본으로 만들고 한 건 함수는 그것을 감싼다. 한 건 함수를 반복문에서 부르지 않는다(N+1).
  2. 공개 / 개인 캐시 경계: 공개 데이터와 개인 상태(`/api/me/*`)는 API·fetch 도구를 나눈다. 공개 fetch 에 쿠키·인증 헤더를 싣지 않는다(헤더가 캐시 키가 된다).
  3. 용도별 반환 칸: 공용 조회 함수는 projection(필요한 칸·관계) 인자를 받는다. 모든 관계를 미리 읽는 범용 로더를 만들지 않는다.
  4. 캐시 무효화: 공용 함수 하나를 쓰되 사건 종류를 인자로 받아, 만료 방식(`expire: 0` / `'max'`)을 표에서 고른다.
  5. 화면 단위 묶음 응답: 한 화면에 필요한 읽기를 FastAPI 엔드포인트 하나로 조립한다(내부는 같은 모듈 호출). HTTP 왕복과 권한 로드 반복을 막기 위함이다.
- 서버 컴포넌트에서 서로 독립인 호출은 순서대로 `await` 하지 않고 `Promise.all` 로 병렬화한다.
- 읽기에는 Server Action 을 쓰지 않는다(클라이언트가 한 번에 하나씩 보낸다).
- 쿼리의 고정 조건(예: `status='published'`)은 바인드 파라미터가 아니라 상수로 쓴다. 부분 인덱스를 쓰게 하기 위함이다.
  - 구현: `literal_column("'published'")` 또는 `literal('published', literal_execute=True)` 로 SQL 리터럴 렌더. `plan_cache_mode` 전역 변경은 쓰지 않는다.
  - 근거(실측, PG18): 범용 계획에서 바인드 조건은 Seq Scan, 리터럴은 부분 인덱스 Index Only Scan.
- 최적화는 측정을 근거로 한다(EXPLAIN·p95, 설계도의 성능 예산). 측정 없이 구조를 복잡하게 만들지 않는다.
- 근거와 세부는 설계도 최종본(`doc/설계도_통합게시판_v3.0_최종_2026-10-15.md`) §2. 설계 기준은 이 최종본 하나이며, 이전 판(v1~v2.4)과 검토 문서는 이력이다.

### 3. 공식 권장 방식
- 개발 툴·개발사가 공식 문서에서 권장하는 방식으로 개발한다. 우회하거나 변칙적인 방법으로 작업·코딩하지 않는다.
  - 금지 예: 내부(비공개) API·패키지 내부 경로 import, 몽키패치, 원인을 고치지 않고 경고·타입 검사를 끄는 주석(`eslint-disable`·`@ts-ignore`·`# type: ignore`), async 세션의 `run_sync`, 문서에 없는 설정 키
- 근거는 설치된 버전의 공식 문서로 확인한다(Next 는 `frontend/node_modules/next/dist/docs/`).
- 권장 방식으로는 요구사항을 맞출 수 없으면 우회하지 않는다. 전역 ② 규칙대로 충돌을 보고하고 대안·승인을 거친다.

### 4. 도메인 중립 (종교·외부 프로젝트와 분리)
- 이 프로젝트는 특정 종교·단체와 무관한 범용 사이트 기반이다. 처음부터 새로 시작하는 프로젝트로 다룬다.
- 코드·주석·식별자·문서·테스트·시드 데이터·화면 문구·커밋 메시지에 가톨릭 등 종교 관련 용어·이름·문구를 쓰지 않는다.
  - 예: 본당·성당·교회·미사·주보·신자·세례명·성직자·성인·전례·위령·감사·청원·기도 같은 말, 그런 뜻의 영문 식별자(parish·cathedral 등)
  - 예시 데이터는 '공지·자유게시판·모집 공고·회의 안내'처럼 중립어로 쓴다.
- faithandme(`~/projects/faithandme`)를 참조하거나 코드를 이식할 때는 **기술 구조만** 가져온다.
  - 그 프로젝트의 도메인 기능·문구·이름·식별자·색 이름·예시 데이터·규칙 번호·문서 이름은 가져오지 않는다.
  - 이식한 코드는 중립어로 바꾼 뒤 커밋하고, 원본 경로와 commit 은 커밋 메시지에만 남긴다.
  - 설계 근거로 faithandme 를 인용하지 않는다. 필요한 사실은 이 프로젝트에서 다시 확인해 적는다.
- CI 금지어 검사(`scripts/ci/check_neutral_terms.py`)가 저장소 전체에서 금지어를 찾는다. 금지어 목록은 그 스크립트 한 곳에 둔다.
  - 이 CLAUDE.md 의 이 절과 스크립트 자신은 검사에서 제외한다.
  - 한국어는 부분 일치 오탐이 있다(예: '미사용'·'미리보기도'). 그런 말은 스크립트의 예외 목록에 넣는다.

## 백업 시 (전역 ③ 규칙 보정)
- RESTORE.md 의 백엔드 의존성 설치는 venv/pip 대신 `cd backend && uv sync`
- `.venv` 도 제외 대상에 넣는다 (`--exclude='.venv'`)
- DB 스키마 덤프는 위 v18 `pg_dump` 경로 사용
