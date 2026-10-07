# Changelog

이 프로젝트의 모든 주요 변경 사항을 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.0.0/), 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

## [0.1.0] - 2026-10-07

### Added
- Next.js 16 프론트엔드 골격 (App Router · TypeScript · Tailwind v4)
- FastAPI 백엔드 골격 (uv · Python 3.13) 및 `/api/health` 엔드포인트
- 프론트엔드 `/api/*` → FastAPI 프록시 (Next `rewrites`, `BACKEND_URL` 환경변수)
- PostgreSQL 연결 (SQLAlchemy 2 async · asyncpg) 및 Alembic(async) 마이그레이션 설정, `/api/health/db` 엔드포인트

[Unreleased]: https://github.com/jnano/mypage/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jnano/mypage/releases/tag/v0.1.0
