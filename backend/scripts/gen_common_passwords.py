"""흔한 비밀번호 목록 만들기 — 인증 설계도 §7.2. 원본을 받아 app/auth/data/common_passwords.txt 를 다시 만든다.

실행: uv run python -m scripts.gen_common_passwords <원본 100k-most-used-passwords-NCSC.txt>
출처·라이선스·가공 규칙은 app/auth/data/common_passwords.SOURCE.md.
바깥 보안 데이터라 도메인 중립 검사의 파일 예외다(CLAUDE.md '4. 도메인 중립') — 금지어로 거르지 않는다.
"""

import hashlib
import sys
import unicodedata
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "app" / "auth" / "data"
MIN_LENGTH_FLOOR = 8  # 사이트 설정 최소 길이의 하한(§3.7) — 그보다 짧은 비밀번호는 길이 규칙이 먼저 거부한다


def main(source: Path) -> None:
    raw = source.read_bytes()
    keys = {unicodedata.normalize("NFKC", line).lower() for line in raw.decode("utf-8").splitlines() if line}
    long_enough = {k for k in keys if len(k) >= MIN_LENGTH_FLOOR}
    kept = sorted(long_enough)
    (DATA / "common_passwords.txt").write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"원본 sha256 {hashlib.sha256(raw).hexdigest()}")
    print(f"원본 {len(raw.splitlines())}줄 → 정규화 고유 {len(keys)} → {MIN_LENGTH_FLOOR}자 이상 {len(kept)}개")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
