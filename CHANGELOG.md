# Changelog

이 프로젝트의 모든 주요 변경 사항을 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.0.0/), 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

### Added
- 작업자 `python -m app.worker`: outbox 처리(SKIP LOCKED·지수 백오프·5회 dead·LISTEN + 폴링), 예약 발행 처리기, 캐시 무효화 이벤트 → Next `POST /api/revalidate`(내부 비밀), 주기 작업 7종(휴지통 자동 정리·알림/멱등 키/요청 수/조회 기록/outbox 정리·게시판 일별 통계), 글 영구 삭제 공용 함수(§4.6)
- 1단계 측정 도구: 10만 건 시드(측정 전용 DB), 핫패스 EXPLAIN(custom/generic), API p95(Server-Timing), 저장 p95(Playwright), 요청 계측 `SERVER_TIMING`
- 검색 최소 구현(설계도 §9): 2글자 토큰 색인(NFKC·casefold·공백 제거, 쓰기 때 갱신), `GET /api/search`(최신순·제목만·게시판 안·300+), 비회원은 비정규화 조건·회원은 열람 판정, `/search` 화면, 전체 재색인 CLI, `/api/health/search`
- Next 화면(스타일 없음): 게시판 목록·글 보기·글쓰기·수정(마크다운 + 미리보기), `cacheComponents` 공개 캐시 + 쪽 단위 캐시 판정(mask 제목 얹기·hide EXISTS·담당자 요청마다), Server Action 쓰기 후 `updateTag`
- 개인 조각 `GET /api/me/page-state`, 게시판 응답의 `has_restricted_posts`
- 개발 로그인(`/dev/login`, ENV=dev 전용 쿠키 → 서버에서 개발 헤더로 변환)과 Next 기동 가드
- FastAPI 쓰기 경계: 상태 변경 요청은 Next 서버의 내부 비밀 헤더(`INTERNAL_API_SECRET`) 필수
- 프런트 테스트(Vitest)와 CI 프런트 작업(타입 검사·테스트·백엔드 없는 빌드)
- 게시판 화면 묶음 응답 `GET /api/boards/{slug}/page`(고정 글 띠·목록·카테고리·지난 글 탭·mask/hide·옛 주소 308)과 글 화면 묶음 응답 `GET /api/posts/{id}/page`(이전·다음 글·관련 글·410)
- 회원 글 작성·수정 API(마크다운 서버 변환 + nh3 정화, 낙관적 잠금 `If-Match`, `Idempotency-Key`, 요청 수 제한, outbox, 무효화 태그 응답)와 마크다운 미리보기 `POST /api/editor/preview`
- 에디터 의미 토큰 원본과 프런트용 생성 파일(`frontend/lib/editor/tokens.gen.json`), 개발용 시드 스크립트
- 권한 판정(설계도 v3.0.2 §5): Viewer·게시판별 역할(쿼리 1회)·`can`·`post_mask`·목록/열람 판정 절, 게시판 단위 정지, 담당자의 열람 통과, 명부 쓰기의 댓글·첨부 적용
- 개발용 Viewer 헤더(`X-Dev-Member`, ENV=dev 전용·공유 비밀 필수, 그 밖에는 기동 실패)와 RFC 9457 오류 응답
- CI 검사: `select(Post)` 가 판정 절을 거치는지(검색 모듈의 목록 절 사용 금지)
- 통합 게시판 스키마 35개 표(설계도 v3.0.1 §4) 와 첫 Alembic 마이그레이션 — 회원·게시판·글·댓글·첨부·신고·운영 기록·제재·알림·작업 큐·멱등 키·요청 수 제한·검색어
- 스키마 대조 테스트(설계도 §4 ↔ 모델), 마이그레이션 차이 검사, 지연 로딩 금지·삭제 규칙 테스트
- pytest 테스트 기반(테스트 DB `mypage_test`, 개발 DB 사용 차단) 및 GitHub Actions CI(도메인 중립 금지어 검사 + 백엔드 테스트)
- DB 연결 풀 설정(`DB_POOL_SIZE`·`DB_MAX_OVERFLOW`·`DB_POOL_TIMEOUT`·`DB_POOL_RECYCLE`·`DB_POOL_PRE_PING`) — 같은 서버 DB 기준으로 `pool_pre_ping` 기본 끔

### Changed
- 성능(1단계 측정): 이전·다음 글 행 값 비교(74 → 0.07ms), 목록 지연 조인 + `ix_posts_board_list INCLUDE (expires_at)`(목록 p95 74 → 30ms), 검색어 리터럴 렌더와 회원 검색 정렬(회원 검색 p95 801 → 131ms)
- Tailwind 제거 — 골격은 class 없는 시맨틱 HTML + `data-slot`(스킨은 디자인 단계)

## [0.1.0] - 2026-10-07

### Added
- Next.js 16 프론트엔드 골격 (App Router · TypeScript · Tailwind v4)
- FastAPI 백엔드 골격 (uv · Python 3.13) 및 `/api/health` 엔드포인트
- 프론트엔드 `/api/*` → FastAPI 프록시 (Next `rewrites`, `BACKEND_URL` 환경변수)
- PostgreSQL 연결 (SQLAlchemy 2 async · asyncpg) 및 Alembic(async) 마이그레이션 설정, `/api/health/db` 엔드포인트

[Unreleased]: https://github.com/jnano/mypage/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jnano/mypage/releases/tag/v0.1.0
