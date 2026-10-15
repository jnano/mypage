#!/usr/bin/env python3
"""에디터 토큰 생성 — 설계도 §8.3.

원본 backend/app/editor/tokens.py → frontend/lib/editor/tokens.gen.json(커밋한다).
프런트는 자기 폴더 안의 생성 파일만 읽는다.

사용법
  python3 scripts/gen_editor_tokens.py          # 생성
  python3 scripts/gen_editor_tokens.py --check  # 원본과 다르면 실패(CI)
"""

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "backend" / "app" / "editor" / "tokens.py"
TARGET = REPO_ROOT / "frontend" / "lib" / "editor" / "tokens.gen.json"


def render() -> str:
    # tokens.py 는 표준 라이브러리만 쓰므로 백엔드 의존성 없이 파일로 직접 읽는다
    spec = importlib.util.spec_from_file_location("editor_tokens", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = {"$generated": "scripts/gen_editor_tokens.py — 직접 고치지 않는다", **module.as_json()}
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str]) -> int:
    content = render()
    if argv == ["--check"]:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != content:
            print(f"{TARGET.relative_to(REPO_ROOT)} 가 원본과 다르다 — scripts/gen_editor_tokens.py 를 실행해 커밋하라", file=sys.stderr)
            return 1
        print("에디터 토큰 생성 파일 일치")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(content, encoding="utf-8")
    print(f"생성: {TARGET.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
