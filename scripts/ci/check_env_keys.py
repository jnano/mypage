#!/usr/bin/env python3
"""환경 변수 대조 검사 — 설계도 §0.2 '환경 변수'·§3.7 표시 시간대.

규칙
1. 백엔드 설정 칸(backend/app/core/config.py 의 Settings)은 모두 개발 틀 backend/.env.example 에
   있다(값 줄 또는 '# KEY=' 주석 줄). 틀에 있는 키는 모두 설정 칸이다(오타 방지).
   설정 칸이 아닌데 틀에 둘 수 있는 키: WEB_CONCURRENCY(uvicorn), TEST_DATABASE_URL(pytest).
2. 운영 틀 deploy/env/backend.env.example 의 키도 설정 칸(또는 위 예외)이고, deploy/README.md
   '3. 환경 변수' 표의 백엔드 키도 그렇다.
3. 프런트 설정 키(frontend/lib/api/config.ts 의 env.X, next.config.ts 의 process.env.X)는 모두
   frontend/.env.example 에 있고, 프런트 틀(개발·운영)의 키는 모두 프런트 설정 키다.
4. 사이트 시간대는 한 값이다 — config.py 의 site_time_zone 기본값 = frontend/lib/format/time.ts 의
   SITE_TIME_ZONE = 운영 틀의 '# SITE_TIME_ZONE=' 값 = deploy/README.md 표의 값(D-103).
5. BACKEND_URL 기본값은 lib/api/config.ts 와 next.config.ts 가 같다(rewrites 는 빌드 때 굳는다 — §17.1).

사용법
  python3 scripts/ci/check_env_keys.py             # 저장소 검사
  python3 scripts/ci/check_env_keys.py --self-test # 틀린 샘플(음성 대조군)·정상 샘플 검사
"""

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FILES = {
    "config_py": "backend/app/core/config.py",
    "backend_env": "backend/.env.example",
    "deploy_backend_env": "deploy/env/backend.env.example",
    "deploy_readme": "deploy/README.md",
    "frontend_config": "frontend/lib/api/config.ts",
    "next_config": "frontend/next.config.ts",
    "frontend_env": "frontend/.env.example",
    "deploy_frontend_env": "deploy/env/frontend.env.example",
    "time_ts": "frontend/lib/format/time.ts",
}
NON_SETTINGS_KEYS = {"WEB_CONCURRENCY", "TEST_DATABASE_URL"}
ENV_LINE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=(.*)$")


def settings_fields(source: str) -> dict[str, object]:
    """Settings 클래스의 칸 이름(대문자) → 기본값(리터럴이 아니면 None)"""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            out = {}
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    name = item.target.id
                    if name == "model_config":
                        continue
                    default = item.value.value if isinstance(item.value, ast.Constant) else None
                    out[name.upper()] = default
            return out
    raise ValueError("config.py 에 Settings 클래스가 없다")


def env_keys(text: str) -> dict[str, str]:
    """틀의 키 → 값(주석 줄 포함). 설명 주석(# 다음에 KEY= 가 아닌 줄)은 건너뛴다"""
    out = {}
    for line in text.splitlines():
        m = ENV_LINE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def readme_env_table(text: str, heading: str) -> dict[str, str]:
    """README '3. 환경 변수' 절에서 heading 다음 첫 표의 `KEY` → 값 칸"""
    start = text.index("## 3. 환경 변수")
    end = text.find("\n## ", start + 1)
    section = text[start : end if end != -1 else len(text)]
    i = section.index(heading)
    out = {}
    in_table = False
    for line in section[i:].splitlines()[1:]:
        if line.startswith("|"):
            in_table = True
            cells = [c.strip() for c in line.strip("|").split("|")]
            for key in re.findall(r"`([A-Z][A-Z0-9_]*)`", cells[0]):
                out[key] = cells[1] if len(cells) > 1 else ""
        elif in_table:
            break
    return out


def frontend_keys(config_ts: str, next_config: str) -> set[str]:
    return set(re.findall(r"\benv\.([A-Z][A-Z0-9_]*)", config_ts)) | set(
        re.findall(r"process\.env\.([A-Z][A-Z0-9_]*)", next_config)
    )


def ts_default(source: str, pattern: str) -> str | None:
    m = re.search(pattern, source)
    return m.group(1) if m else None


def check(texts: dict[str, str]) -> list[str]:
    problems = []
    fields = settings_fields(texts["config_py"])
    allowed = set(fields) | NON_SETTINGS_KEYS

    dev = env_keys(texts["backend_env"])
    for key in sorted(set(fields) - set(dev)):
        problems.append(f"{FILES['backend_env']}: 설정 칸 {key} 가 없다(값 줄 또는 '# {key}=' 주석 줄로 둔다)")
    for name, keys in (
        ("backend_env", dev),
        ("deploy_backend_env", env_keys(texts["deploy_backend_env"])),
        ("deploy_readme", readme_env_table(texts["deploy_readme"], "`/etc/mypage/backend.env`")),
    ):
        for key in sorted(set(keys) - allowed):
            problems.append(f"{FILES[name]}: {key} 는 백엔드 설정 칸이 아니다(오타이거나 config.py 에 없다)")

    fkeys = frontend_keys(texts["frontend_config"], texts["next_config"])
    fdev = env_keys(texts["frontend_env"])
    for key in sorted(fkeys - set(fdev)):
        problems.append(f"{FILES['frontend_env']}: 프런트 설정 키 {key} 가 없다")
    for name, keys in (
        ("frontend_env", fdev),
        ("deploy_frontend_env", env_keys(texts["deploy_frontend_env"])),
        ("deploy_readme", readme_env_table(texts["deploy_readme"], "`/etc/mypage/frontend.env`")),
    ):
        for key in sorted(set(keys) - fkeys):
            problems.append(f"{FILES[name]}: {key} 는 프런트 설정 키가 아니다")

    # 사이트 시간대 — 네 곳이 한 값
    zones = {
        FILES["config_py"]: fields.get("SITE_TIME_ZONE"),
        FILES["time_ts"]: ts_default(texts["time_ts"], r'export const SITE_TIME_ZONE\s*=\s*"([^"]+)"'),
        FILES["deploy_backend_env"]: env_keys(texts["deploy_backend_env"]).get("SITE_TIME_ZONE"),
        FILES["deploy_readme"]: readme_env_table(texts["deploy_readme"], "`/etc/mypage/backend.env`")
        .get("SITE_TIME_ZONE", "")
        .strip("`")
        or None,
    }
    if None in zones.values() or len(set(zones.values())) != 1:
        problems.append("사이트 시간대가 한 값이 아니다(D-103): " + ", ".join(f"{k}={v}" for k, v in zones.items()))

    # BACKEND_URL 기본값
    urls = {
        FILES["frontend_config"]: ts_default(texts["frontend_config"], r'BACKEND_URL \?\? "([^"]+)"'),
        FILES["next_config"]: ts_default(texts["next_config"], r'BACKEND_URL \?\? "([^"]+)"'),
    }
    if None in urls.values() or len(set(urls.values())) != 1:
        problems.append("BACKEND_URL 기본값이 다르다: " + ", ".join(f"{k}={v}" for k, v in urls.items()))
    return problems


def load() -> dict[str, str]:
    return {k: (REPO_ROOT / v).read_text(encoding="utf-8") for k, v in FILES.items()}


def self_test() -> int:
    good = {
        "config_py": 'class Settings:\n    model_config = 1\n    env: str = "prod"\n    site_time_zone: str = "Asia/Seoul"\n',
        "backend_env": "# 설명 줄\nENV=dev\n# SITE_TIME_ZONE=Asia/Seoul\n# WEB_CONCURRENCY=2\n",
        "deploy_backend_env": "ENV=\n# SITE_TIME_ZONE=Asia/Seoul\n",
        "deploy_readme": "## 3. 환경 변수\n\n`/etc/mypage/backend.env` 설명\n\n| 키 | 값 |\n|---|---|\n| `ENV` | `prod` |\n"
        "| `SITE_TIME_ZONE` | `Asia/Seoul` |\n\n`/etc/mypage/frontend.env`:\n\n| 키 | 값 |\n|---|---|\n| `APP_ENV` | `prod` |\n\n## 4. 다음\n",
        "frontend_config": 'const a = env.APP_ENV;\nconst b = env.BACKEND_URL ?? "http://localhost:8000";\n',
        "next_config": 'const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";\n',
        "frontend_env": "APP_ENV=dev\nBACKEND_URL=http://localhost:8000\n",
        "deploy_frontend_env": "APP_ENV=\nBACKEND_URL=\n",
        "time_ts": 'export const SITE_TIME_ZONE = "Asia/Seoul";\n',
    }
    bad_cases = {
        "설정 칸이 개발 틀에 없다": ("backend_env", "ENV=dev\n"),
        "틀에 오타 키": ("deploy_backend_env", "ENV=\nENVV=\n# SITE_TIME_ZONE=Asia/Seoul\n"),
        "README 표에 설정 칸이 아닌 키": ("deploy_readme", good["deploy_readme"].replace("`ENV`", "`ENVIRONMENT`")),
        "프런트 키가 개발 틀에 없다": ("frontend_env", "APP_ENV=dev\n"),
        "프런트 틀에 모르는 키": ("deploy_frontend_env", "APP_ENV=\nBACKEND_URL=\nAPI_URL=\n"),
        "시간대 — 프런트 상수가 다름": ("time_ts", 'export const SITE_TIME_ZONE = "UTC";\n'),
        "시간대 — 운영 틀이 다름": ("deploy_backend_env", "ENV=\n# SITE_TIME_ZONE=Asia/Tokyo\n"),
        "BACKEND_URL 기본값 다름": ("next_config", 'const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";\n'),
    }
    failed = []
    if check(good):
        failed.append(f"정상 샘플이 실패: {check(good)}")
    for label, (key, text) in bad_cases.items():
        if not check({**good, key: text}):
            failed.append(f"대조군을 잡지 못함: {label}")
    if failed:
        print("\n".join(failed))
        return 1
    print(f"대조군 통과 — 정상 1 · 위반 {len(bad_cases)}")
    return 0


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()
    problems = check(load())
    if problems:
        print("\n".join(problems))
        return 1
    print("환경 변수 대조 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
