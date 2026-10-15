#!/usr/bin/env python3
"""도메인 중립 검사 — 저장소에 특정 종교·외부 프로젝트 관련 금지어가 있으면 실패한다.

규칙: CLAUDE.md '개발 원칙 4. 도메인 중립', 설계도 §2.4. 금지어 목록은 이 파일 한 곳에 둔다.

사용법
  python3 scripts/ci/check_neutral_terms.py            # git 이 추적하는 파일 전체
  python3 scripts/ci/check_neutral_terms.py 파일...     # 지정한 파일만
  python3 scripts/ci/check_neutral_terms.py --self-test # 대조군 검사(금지어를 잡는지·오탐이 없는지)
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()

FORBIDDEN_KO = [
    "가톨릭", "천주교", "본당", "성당", "교회", "교구", "미사", "주보", "신자", "세례",
    "성직자", "신부", "수녀", "성인", "전례", "위령", "감사", "청원", "기도", "성경", "주일",
]
FORBIDDEN_EN = [
    "catholic", "church", "parish", "cathedral", "diocese", "liturgy", "liturgical",
    "sacrament", "baptism", "priest", "faithandme",
]

# 한국어 부분 일치 오탐. 이 패턴에 걸린 구간은 금지어 검사에서 뺀다.
ALLOWED_PATTERNS = [
    r"미사용",
    r"(?:미리보|하|되|있|없|보|쓰|받|오|가|나|읽|만들|바꾸|늘|줄|크|작|많|적|길|빠르|느리|시)기도(?!문|회)",
    r"주기도(?!문)",
    r"(?:\d+|일|이|삼|사|한|두|세|네)\s?주일",
    r"전례\s?없",
]

_forbidden_re = re.compile(
    "|".join(map(re.escape, FORBIDDEN_KO))
    + "|"
    + "|".join(rf"{re.escape(w)}" for w in FORBIDDEN_EN),
    re.IGNORECASE,
)
_allowed_re = re.compile("|".join(ALLOWED_PATTERNS))

# 금지어를 설명하는 구간: (파일, 시작 제목). 그 제목부터 같은 수준 이상의 다음 제목 전까지 뺀다.
EXEMPT_SECTIONS = [("CLAUDE.md", "### 4. 도메인 중립")]


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, check=True, capture_output=True
    ).stdout
    return [REPO_ROOT / p for p in out.decode().split("\0") if p]


def exempt_lines(path: Path, lines: list[str]) -> set[int]:
    skip: set[int] = set()
    rel = path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else ""
    for file, heading in EXEMPT_SECTIONS:
        if rel != file:
            continue
        level = len(heading) - len(heading.lstrip("#"))
        inside = False
        for i, line in enumerate(lines):
            if line.startswith(heading):
                inside = True
            elif inside and re.match(rf"#{{1,{level}}} ", line):
                inside = False
            if inside:
                skip.add(i)
    return skip


def scan(path: Path) -> list[tuple[int, str, str]]:
    try:
        data = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError):
        return []
    if b"\0" in data:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    lines = text.splitlines()
    skip = exempt_lines(path, lines)
    hits = []
    for i, line in enumerate(lines):
        if i in skip:
            continue
        masked = _allowed_re.sub(lambda m: " " * len(m.group()), line)
        for m in _forbidden_re.finditer(masked):
            hits.append((i + 1, m.group(), line.strip()))
    return hits


def self_test() -> int:
    """음성·양성 대조군. 금지어 문자열을 다른 파일에 적지 않도록 이 파일 안에서 만든다."""
    import tempfile

    cases = {
        f"{FORBIDDEN_KO[4]} 모임 안내\n{FORBIDDEN_EN[1].title()} notice\n": 2,  # 반드시 잡아야 함
        "미사용 칸, 미리보기도 쓴다, 일주일, 3주일, 그렇게 하기도 한다, 전례 없는\n": 0,  # 오탐 금지
    }
    ok = True
    with tempfile.TemporaryDirectory() as d:
        for i, (body, expected) in enumerate(cases.items()):
            p = Path(d) / f"case{i}.txt"
            p.write_text(body, encoding="utf-8")
            got = len(scan(p))
            if got != expected:
                ok = False
                print(f"self-test 실패: case{i} 기대 {expected}건, 실제 {got}건", file=sys.stderr)
    print("self-test 통과" if ok else "self-test 실패")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        return self_test()
    paths = [Path(a).resolve() for a in argv] if argv else tracked_files()
    found = 0
    for path in paths:
        if path == SELF:
            continue
        for lineno, word, line in scan(path):
            found += 1
            print(f"{path}:{lineno}: 금지어 '{word}' — {line[:120]}")
    if found:
        print(f"\n도메인 중립 검사 실패: {found}건. CLAUDE.md '도메인 중립' 참고.", file=sys.stderr)
        return 1
    print("도메인 중립 검사 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
