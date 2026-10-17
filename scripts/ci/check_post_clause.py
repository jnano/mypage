#!/usr/bin/env python3
"""글 조회 판정 절 검사 — 설계도 §5.2.

규칙
1. backend/app 안에서 select(Post…) 를 만드는 함수는 판정 절(CLAUSES — listable·readable_posts_clause,
   작성자 본인 글의 own_posts_openable_clause)을 같은 함수 안에서 불러야 한다(권한 우회 방지).
2. 검색 모듈(경로에 'search')은 listable_posts_clause 를 쓰면 안 된다 — 목록 절은
   가려진 글을 거르지 않아, 가려진 글 본문이 검색 매칭에 쓰이면 누설된다.
예외: 관리·작업자·권한 모듈처럼 판정 절 밖에서 글을 읽어야 하는 곳은 select 줄 끝에
   `# post-clause: exempt — 사유` 를 단다. 사유 없는 예외는 실패.

사용법
  python3 scripts/ci/check_post_clause.py            # backend/app 전체
  python3 scripts/ci/check_post_clause.py 파일...     # 지정한 파일만
  python3 scripts/ci/check_post_clause.py --self-test # 위반 샘플(음성 대조군)·정상 샘플 검사
"""

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "backend" / "app"
# own_posts_openable_clause: 작성자 본인 글을 지금 열 수 있는가(내 글 목록, 설계도 §6.2) — can(post.read) 의 작성자 경로
CLAUSES = {"listable_posts_clause", "readable_posts_clause", "own_posts_openable_clause"}
EXEMPT_RE = re.compile(r"#\s*post-clause:\s*exempt\s*[—-]\s*\S")


def _selects_post(call: ast.Call) -> bool:
    fn = call.func
    name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
    if name != "select":
        return False
    for arg in call.args:
        # select(*COLUMNS) 는 무엇을 펼치는지 알 수 없으므로 글 조회로 본다(보수적으로)
        if isinstance(arg, ast.Starred):
            return True
        node = arg.value if isinstance(arg, ast.Attribute) else arg
        if isinstance(node, ast.Name) and node.id == "Post":
            return True
    return False


def _called_names(node: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "")
    return out


def check_source(source: str, path: str) -> list[str]:
    tree = ast.parse(source)
    lines = source.splitlines()
    is_search = "search" in path
    problems = []
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in funcs:
        called = _called_names(fn)
        if is_search and "listable_posts_clause" in called:
            problems.append(f"{path}:{fn.lineno}: 검색 모듈이 listable_posts_clause 를 쓴다(누설 위험)")
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and _selects_post(n):
                line = lines[n.lineno - 1]
                if "post-clause" in line and not EXEMPT_RE.search(line):
                    problems.append(f"{path}:{n.lineno}: 예외 표시에 사유가 없다")
                elif not EXEMPT_RE.search(line) and not (called & CLAUSES):
                    problems.append(
                        f"{path}:{n.lineno}: select(Post) 가 listable/readable_posts_clause 를 거치지 않는다"
                    )
    return problems


SAMPLES_BAD = {
    "app/boards/cols.py": "def f():\n    return select(*LIST_COLUMNS)\n",
    "app/boards/repo.py": "async def f(db):\n    return await db.execute(select(Post.id))\n",
    "app/search/q.py": (
        "async def f(db, v):\n    return await db.execute(select(Post).where(listable_posts_clause(v)))\n"
    ),
    "app/admin/x.py": "def f():\n    return select(Post)  # post-clause: exempt\n",
}
SAMPLES_OK = {
    "app/boards/repo.py": (
        "async def f(db, v):\n    return await db.execute(select(Post).where(listable_posts_clause(v)))\n"
    ),
    "app/search/q.py": (
        "def f(v):\n    return select(Post.id).where(readable_posts_clause(v))\n"
    ),
    "app/admin/x.py": "def f():\n    return select(Post)  # post-clause: exempt — 관리 통합 목록\n",
    "app/other.py": "def f():\n    return select(Board)\n",
}


def self_test() -> int:
    ok = True
    for path, src in SAMPLES_BAD.items():
        if not check_source(src, path):
            ok = False
            print(f"self-test 실패: 위반 샘플을 잡지 못했다 — {path}", file=sys.stderr)
    for path, src in SAMPLES_OK.items():
        if found := check_source(src, path):
            ok = False
            print(f"self-test 실패: 정상 샘플을 잘못 잡았다 — {found}", file=sys.stderr)
    print("self-test 통과" if ok else "self-test 실패")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv == ["--self-test"]:
        return self_test()
    paths = [Path(a).resolve() for a in argv] if argv else sorted(APP_DIR.rglob("*.py"))
    problems = []
    for p in paths:
        rel = p.relative_to(REPO_ROOT).as_posix() if p.is_relative_to(REPO_ROOT) else str(p)
        # 판정 절을 정의하는 권한 모듈 자신은 검사하지 않는다
        if rel.startswith("backend/app/permissions/"):
            continue
        problems += check_source(p.read_text(encoding="utf-8"), rel)
    for line in problems:
        print(line)
    if problems:
        print(f"\n글 조회 판정 절 검사 실패: {len(problems)}건 (설계도 §5.2)", file=sys.stderr)
        return 1
    print("글 조회 판정 절 검사 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
