# 흔한 비밀번호 목록 — 출처

인증 설계도 §7.2 '흔한 비밀번호 목록과 대조(늘 켬)'.

| 항목 | 값 |
|---|---|
| 저장소 | SecLists — https://github.com/danielmiessler/SecLists |
| 커밋 | `f1196104c5594a19d78b486c52c0794b9d947993` (2026-10-16 확인) |
| 경로 | `Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt` |
| 원본 sha256 | `c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0` (99,840줄) |
| 라이선스 | MIT — 저장소 루트 `LICENSE`, 같은 폴더의 `common_passwords.LICENSE` 가 그 사본 |

가공(`backend/scripts/gen_common_passwords.py` — 원본을 받아 다시 만든다)
1. 줄마다 NFKC + 소문자 → 고유 97,746개
2. 8자 이상만(사이트 최소 길이 설정의 하한 — 그보다 짧으면 길이 규칙이 먼저 거부한다) → **46,483개**

도메인 중립 검사: 이 파일은 우리가 쓴 문구가 아니라 바깥 보안 데이터라 검사에서 통째로 뺀다(`CLAUDE.md` '4. 도메인 중립', `scripts/ci/check_neutral_terms.py` 의 `EXEMPT_FILES`). 금지어가 든 항목도 흔한 비밀번호이므로 지우지 않는다.

한계: 영어권 유출 자료에서 온 목록이라 한국어(한글) 비밀번호는 없다. 한국어 사용자에게는 길이 규칙(기본 15자)이 주된 방어다.
