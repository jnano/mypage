# mypage — 프로젝트 규칙

전역 규칙(`~/.claude/CLAUDE.md`)을 따르며, 이 문서는 프로젝트 고유 정보만 담는다.
문서(계획서·보고서 등)는 `~/projects/mypage/doc/` 에 둔다 — 이 저장소(`src`)에 두지 않는다.

## 기술 스택
- 프론트엔드: Next.js 16 (App Router) · React 19 · TypeScript · Tailwind v4 — `frontend/`
  - Next 16 은 학습 데이터와 다를 수 있다. 코드 작성 전 `frontend/node_modules/next/dist/docs/` 확인 (`frontend/AGENTS.md`)
- 백엔드: FastAPI · Python 3.13 · **uv** (pip/venv 직접 사용 금지) — `backend/`
- DB: PostgreSQL 18 (Postgres.app) · SQLAlchemy 2 **async** + asyncpg · Alembic(async 템플릿)

## 구조
```
frontend/            Next.js 앱. /api/* 는 next.config.ts rewrites 로 백엔드에 프록시
backend/
  app/main.py        FastAPI 앱. 모든 라우터는 prefix="/api"
  app/core/config.py 설정 (pydantic-settings, backend/.env)
  app/db/            base.py(Base) · session.py(engine, get_db) · models.py(모델 등록)
  alembic/           마이그레이션 (env.py 가 settings.database_url 사용)
```

## 서버 실행
```bash
# 백엔드 (포트 8000)
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000
# 프론트엔드 (포트 3000)
cd frontend && npm install && npm run dev
```
확인: `http://localhost:3000/api/health` · `/api/health/db`

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

## 백업 시 (전역 ③ 규칙 보정)
- RESTORE.md 의 백엔드 의존성 설치는 venv/pip 대신 `cd backend && uv sync`
- `.venv` 도 제외 대상에 넣는다 (`--exclude='.venv'`)
- DB 스키마 덤프는 위 v18 `pg_dump` 경로 사용
