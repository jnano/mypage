# backend — FastAPI

실행·테스트 명령은 저장소 루트 `CLAUDE.md` 의 '서버 실행'·'테스트'. 이 문서는 개발 DB 에서 알아야 할 것만 적는다.

## 개발

### 개발용 계정

`scripts.seed_dev`(개발 DB)와 `scripts.seed_posts`(측정 DB)가 만드는 회원, `scripts.fill_auth_dev` 가 채운 회원은 모두 같은 비밀번호를 쓴다.

- 비밀번호: `dev-password-0123456789` (`scripts/dev_auth.py` — 운영에서 쓰지 않는다)
- 이메일: 시드 `admin@example.test`·`moderator@example.test`·`member1@example.test`·`member3@example.test`, 측정 DB `bench0000@example.test`…, 채움 스크립트 `m{회원 id}@example.test`
- 개인정보 고지 판: `dev-notice`(개발·측정용). 운영의 첫 판은 첫 운영자 CLI 가 실제 고지문으로 만든다(`deploy/README.md`)

### 인증 이전의 DB 를 올리기 (인증 설계도 §3.1)

인증 마이그레이션은 둘로 나뉜다 — `66efce5894cc`(칸·표 추가) → `6aae850ab6db`(회원 인증 칸 CHECK).
인증 칸이 비어 있는 회원이 있으면 두 번째가 자리 값을 넣지 않고 안내와 함께 실패한다. 개발·측정 DB 는 사이에 채운다.

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://taehunkang@localhost:5432/mypage_bench uv run alembic upgrade 66efce5894cc
DATABASE_URL=postgresql+asyncpg://taehunkang@localhost:5432/mypage_bench uv run python -m scripts.fill_auth_dev --database mypage_bench
DATABASE_URL=postgresql+asyncpg://taehunkang@localhost:5432/mypage_bench uv run alembic upgrade head
```

- 처음부터 `upgrade head` 를 돌리면 두 리비전이 한 트랜잭션이라 안내와 함께 **통째로 되돌아간다**(앞 리비전도 남지 않음). 그래서 `66efce5894cc` 까지 먼저 올린다.
- `fill_auth_dev` 는 `ENV` 가 `dev`·`test` 일 때만 돈다(`ENV=prod` 는 무조건 거부). `--database` 는 확인 값 — 실제로 연결된 DB 이름과 다르면 거부한다.
- 표시 이름의 정규화 키가 겹치는 활동 회원은 이름 뒤에 `#회원 id` 를 붙인다.
- 개발 DB(`mypage`)는 다시 시드해도 된다(`DROP`·`createdb` → `alembic upgrade head` → `scripts.seed_dev`).

### 흔한 비밀번호 목록

`app/auth/data/common_passwords.txt` — 출처·라이선스·가공은 같은 폴더의 `common_passwords.SOURCE.md`. 다시 만들 때는 `scripts.gen_common_passwords`.
