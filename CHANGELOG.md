# Changelog

이 프로젝트의 모든 주요 변경 사항을 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.0.0/), 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

### Added
- DB 연결 풀 설정(`DB_POOL_SIZE`·`DB_MAX_OVERFLOW`·`DB_POOL_TIMEOUT`·`DB_POOL_RECYCLE`·`DB_POOL_PRE_PING`) — 같은 서버 DB 기준으로 `pool_pre_ping` 기본 끔
- 권한 판정(설계도 v3.0.2 §5): Viewer·게시판별 역할(쿼리 1회)·`can`·`post_mask`·목록/열람 판정 절, 게시판 단위 정지, 담당자의 열람 통과, 명부 쓰기의 댓글·첨부 적용
- 개발용 Viewer 헤더(`X-Dev-Member`, ENV=dev 전용·공유 비밀 필수, 그 밖에는 기동 실패)와 RFC 9457 오류 응답
- CI 검사: `select(Post)` 가 판정 절을 거치는지(검색 모듈의 목록 절 사용 금지)
- 통합 게시판 스키마 35개 표(설계도 v3.0.1 §4) 와 첫 Alembic 마이그레이션 — 회원·게시판·글·댓글·첨부·신고·운영 기록·제재·알림·작업 큐·멱등 키·요청 수 제한·검색어
- 스키마 대조 테스트(설계도 §4 ↔ 모델), 마이그레이션 차이 검사, 지연 로딩 금지·삭제 규칙 테스트
- pytest 테스트 기반(테스트 DB `mypage_test`, 개발 DB 사용 차단) 및 GitHub Actions CI(도메인 중립 금지어 검사 + 백엔드 테스트)

## [0.1.0] - 2026-10-07

### Added
- Next.js 16 프론트엔드 골격 (App Router · TypeScript · Tailwind v4)
- FastAPI 백엔드 골격 (uv · Python 3.13) 및 `/api/health` 엔드포인트
- 프론트엔드 `/api/*` → FastAPI 프록시 (Next `rewrites`, `BACKEND_URL` 환경변수)
- PostgreSQL 연결 (SQLAlchemy 2 async · asyncpg) 및 Alembic(async) 마이그레이션 설정, `/api/health/db` 엔드포인트

[Unreleased]: https://github.com/jnano/mypage/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jnano/mypage/releases/tag/v0.1.0
