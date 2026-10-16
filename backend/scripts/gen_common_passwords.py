"""흔한 비밀번호 목록 만들기 — 인증 설계도 §7.2. 원본을 받아 app/auth/data/common_passwords.txt 를 다시 만든다.

실행: uv run python -m scripts.gen_common_passwords <원본 100k-most-used-passwords-NCSC.txt>
출처·라이선스·가공 규칙은 app/auth/data/common_passwords.SOURCE.md.
"""

import hashlib
import importlib.util
import sys
import unicodedata
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "app" / "auth" / "data"
CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "check_neutral_terms.py"
MIN_LENGTH_FLOOR = 8  # 사이트 설정 최소 길이의 하한(§3.7) — 그보다 짧은 비밀번호는 길이 규칙이 먼저 거부한다


def _forbidden():
    # 도메인 중립 검사(CLAUDE.md 4)의 금지어 규칙을 그대로 쓴다 — 목록을 두 곳에 두지 않는다
    spec = importlib.util.spec_from_file_location("check_neutral_terms", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._forbidden_re


def main(source: Path) -> None:
    raw = source.read_bytes()
    forbidden = _forbidden()
    keys = {unicodedata.normalize("NFKC", line).lower() for line in raw.decode("utf-8").splitlines() if line}
    long_enough = {k for k in keys if len(k) >= MIN_LENGTH_FLOOR}
    kept = sorted(k for k in long_enough if not forbidden.search(k))
    (DATA / "common_passwords.txt").write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(f"원본 sha256 {hashlib.sha256(raw).hexdigest()}")
    print(f"원본 {len(raw.splitlines())}줄 → 정규화 고유 {len(keys)} → {MIN_LENGTH_FLOOR}자 이상 {len(long_enough)}")
    print(f"→ 도메인 중립 금지어를 포함한 {len(long_enough) - len(kept)}개 제외 → {len(kept)}개")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
