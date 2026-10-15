# mypage 배포 설명서 (운영자용)

설계도 §17 의 구성을 서버 한 대(Ubuntu LTS)에 올리는 순서다. 이 폴더의 파일:

| 파일 | 둘 곳 |
|---|---|
| `nginx/mypage.conf` | `/etc/nginx/conf.d/mypage.conf` |
| `nginx/mypage-security-headers.conf` | `/etc/nginx/snippets/mypage-security-headers.conf` |
| `systemd/mypage-backend.service` · `mypage-worker.service` · `mypage-frontend.service` | `/etc/systemd/system/` |
| `env/backend.env.example` · `env/frontend.env.example` | 키 목록 — 값을 채워 `/etc/mypage/backend.env`·`frontend.env` |
| `build.sh` | 빌드(서버·로컬 공용) |

```
요청 → nginx(80/443) ─┬─ /media/        → /srv/mypage/shared/media (공개 파일 직접)
                      ├─ /_private/…    → internal(X-Accel-Redirect 로만)
                      └─ 그 밖          → Next 127.0.0.1:3000 ─(/api/*)→ FastAPI 127.0.0.1:8000 ×2
                                                               작업자(outbox·주기 작업) ─┘   └→ PostgreSQL
```

배포 전 검사는 CI 작업 `deploy-check` 가 한다(`nginx -t`, `systemd-analyze verify`).

## 1. 서버 준비

1. Ubuntu LTS, 시간대는 UTC 그대로(사이트 시간대는 앱 설정 `SITE_TIME_ZONE`).
2. 패키지: `nginx`, PostgreSQL 18(PGDG 저장소), Node.js 22(22.22.2 이상 — `frontend/package.json` `engines`), `uv`(Astral 설치 스크립트), `certbot`·`python3-certbot-nginx`, `git`.
3. 사용자와 폴더:
   ```bash
   sudo useradd --system --create-home --home-dir /srv/mypage --shell /usr/sbin/nologin mypage
   sudo -u mypage mkdir -p /srv/mypage/shared/media /srv/mypage/shared/private
   sudo mkdir -p /etc/mypage && sudo chown root:mypage /etc/mypage && sudo chmod 750 /etc/mypage
   ```
4. 저장소: `sudo -u mypage git clone <저장소 주소> /srv/mypage/app`

## 2. 데이터베이스

```bash
sudo -u postgres createuser mypage
sudo -u postgres createdb -O mypage mypage
```
같은 서버라 연결은 유닉스 소켓(peer 인증)으로 한다: `DATABASE_URL=postgresql+asyncpg:///mypage?host=/var/run/postgresql`.

연결 수 계산(§17): `uvicorn 프로세스 수 × (DB_POOL_SIZE + DB_MAX_OVERFLOW) + 작업자 풀 + LISTEN 1 + 여유 ≤ max_connections`.
기본값으로 2 × (5 + 5) + (5 + 5) + 1 + 여유 ≈ 40 — PostgreSQL 기본 `max_connections`(100) 안이다. PgBouncer 는 쓰지 않는다(§17).

## 3. 환경 변수

`/etc/mypage/backend.env`(권한 640, 소유 root:mypage). 키는 `env/backend.env.example` 와 같다.

| 키 | 값 |
|---|---|
| `ENV` | `prod` |
| `DEBUG` | `false` |
| `DATABASE_URL` | 위 2 |
| `DB_POOL_SIZE` · `DB_MAX_OVERFLOW` | `5` · `5`(부하 측정으로 조정 — `doc/측정/`) |
| `INTERNAL_API_SECRET` | 32자 이상 무작위(`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`). frontend.env 와 같은 값 |
| `NEXT_REVALIDATE_URL` | `http://127.0.0.1:3000/api/revalidate` |
| `MEDIA_ROOT` · `PRIVATE_ROOT` | `/srv/mypage/shared/media` · `/srv/mypage/shared/private` |
| `FILE_SENDER` | `nginx`(비공개 파일을 X-Accel-Redirect 로) |
| `SITE_TIME_ZONE` | `Asia/Seoul` |

`/etc/mypage/frontend.env` — 키는 `env/frontend.env.example`:

| 키 | 값 |
|---|---|
| `APP_ENV` | `prod` |
| `BACKEND_URL` | `http://127.0.0.1:8000` |
| `INTERNAL_API_SECRET` | backend.env 와 같은 값 |

운영에는 개발 로그인 키(`DEV_VIEWER_*`)를 넣지 않는다 — 넣으면 기동이 실패하도록 막혀 있다(§5.1·§11). 실제 인증은 실서버 배포 전 별도 단계다.

## 4. 빌드·마이그레이션·기동

```bash
cd /srv/mypage/app
sudo -u mypage ./deploy/build.sh
sudo -u mypage bash -c 'set -a; . /etc/mypage/backend.env; cd backend && .venv/bin/alembic upgrade head'
sudo install -m 644 deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mypage-backend mypage-worker mypage-frontend
```

nginx:
```bash
sudo install -m 644 deploy/nginx/mypage-security-headers.conf /etc/nginx/snippets/
sudo install -m 644 deploy/nginx/mypage.conf /etc/nginx/conf.d/
sudo sed -i 's/example.org/실제.도메인/' /etc/nginx/conf.d/mypage.conf
sudo nginx -t && sudo systemctl reload nginx
```

TLS: `sudo certbot --nginx -d 실제.도메인` — certbot 이 server 블록에 443 과 인증서를 덧붙이고 갱신 타이머를 건다.

## 5. 확인

- `systemctl status mypage-backend mypage-worker mypage-frontend`
- `curl -sf https://도메인/api/health` · `/api/health/db` · `/api/health/search`
- 스트리밍: 로그인 화면의 '불러오는 중'이 먼저 보이고 내용이 이어 붙는다(nginx 가 모아 두지 않음 — Next 가 `X-Accel-Buffering: no` 를 보낸다)
- 비공개 첨부: 권한 있는 사람만 받아지고, `https://도메인/_private/…` 직접 열기는 404
- 업로드 상한: 55MB 넘는 요청은 nginx 가 413

## 6. 운영 전 체크리스트(§10)

- 관리 → 사이트 설정: 사이트 주소(`https://도메인`), 사이트 이름·설명, 검색엔진 확인 값, 색인 허용
- 검색엔진에 `https://도메인/sitemap.xml` 과 `/posts/sitemap/0.xml`… 제출(robots.txt 에 모두 적혀 있다), RSS `/rss.xml`
- 백업: `pg_dump` 일 1회 + `/srv/mypage/shared` 파일 백업(데이터는 저장소에 없다)

## 7. 갱신·되돌리기

```bash
cd /srv/mypage/app && sudo -u mypage git pull
sudo -u mypage ./deploy/build.sh
sudo -u mypage bash -c 'set -a; . /etc/mypage/backend.env; cd backend && .venv/bin/alembic upgrade head'
sudo systemctl restart mypage-backend mypage-worker mypage-frontend
```
되돌리기: 이전 커밋으로 `git checkout <커밋>` 뒤 같은 순서. 마이그레이션을 되돌려야 하면 `alembic downgrade <리비전>` 을 먼저 한다.
Next 의 `'use cache'` 저장소는 프로세스 메모리라 재시작 직후 1분은 '차가운 캐시'다(§15.1 — 부하 측정 보고서에 따로 기록).

## 8. 로그

- nginx: `/var/log/nginx/mypage.*.log` — Ubuntu 기본 logrotate(매일, 14개 보관)
- 앱: `journalctl -u mypage-backend -u mypage-worker -u mypage-frontend` — 보존 기간은 `/etc/systemd/journald.conf` 의 `MaxRetentionSec`(예: `30day`)
- uvicorn 접근 기록은 끈다(`--no-access-log`) — 요청 기록은 nginx 한 곳에
