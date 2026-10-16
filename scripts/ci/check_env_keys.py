#!/usr/bin/env python3
"""환경 변수 대조 검사 — 설계도 §0.2 '환경 변수'·§3.7 표시 시간대.

저장소 쪽 정본은 deploy/README.md '3. 환경 변수' 표와 틀(*.env.example)이다. 설계도(저장소 밖)의 표는
CI 가 볼 수 없으므로 대조 밖이다.

규칙
1. 백엔드 설정 칸(backend/app/core/config.py 의 Settings)은 모두 개발 틀 backend/.env.example 에
   있다(값 줄 또는 '# KEY=' 주석 줄). 틀·README 표에 있는 키는 모두 설정 칸이다(오타 방지).
   설정 칸이 아닌데 둘 수 있는 키: WEB_CONCURRENCY(uvicorn), TEST_DATABASE_URL(pytest).
2. 운영 필수 키(REQUIRED_DEPLOY)는 운영 틀에 값 줄(주석 아님)로, README 표에 행으로 있다.
3. 프런트 설정 키(frontend/lib/api/config.ts 의 env.X, next.config.ts 의 process.env.X)는 모두
   frontend/.env.example 에 있고, 프런트 틀(개발·운영)·README 표의 키는 모두 프런트 설정 키다.
4. 틀에 같은 키가 두 번(값 줄·주석 줄 포함) 나오면 실패 — 어느 값이 쓰일지 읽는 사람이 헷갈린다.
5. 사이트 시간대(D-103): 프런트 상수 frontend/lib/format/time.ts 는 빌드에 들어가 바뀌지 않으므로
   백엔드도 운영에서 바꾸지 않는다 — config.py 기본값 = time.ts 상수 = 개발 틀 주석 값이고,
   운영 틀·README 표에는 SITE_TIME_ZONE 이 없어야 한다(바꾸는 법은 README 1절 안내).
6. BACKEND_URL 기본값은 lib/api/config.ts 와 next.config.ts 가 같다(rewrites 는 빌드 때 굳는다 — §17.1).
7. 추출할 수 없는 형식(Field(alias=…)·env_prefix·env["X"]·process.env["X"]·구조 분해)은 실패 —
   검사가 조용히 칸을 놓치지 않게.

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
REQUIRED_DEPLOY = {
    "backend": {"ENV", "DATABASE_URL", "INTERNAL_API_SECRET", "EMAIL_HMAC_SECRET", "DB_POOL_SIZE",
                "DB_MAX_OVERFLOW", "MEDIA_ROOT", "PRIVATE_ROOT", "FILE_SENDER"},
    "frontend": {"APP_ENV", "BACKEND_URL", "INTERNAL_API_SECRET"},
}  # fmt: skip
README_SECTION = "## 3. 환경 변수"
README_BACKEND = "`/etc/mypage/backend.env`"
README_FRONTEND = "`/etc/mypage/frontend.env`"
ENV_LINE = re.compile(r"^(#?)\s*([A-Z][A-Z0-9_]*)=(.*)$")


class FormatError(Exception):
    """검사가 읽을 수 없는 모양 — 조용히 넘어가지 않고 실패로 보고한다"""


def settings_fields(source: str) -> dict[str, object]:
    """Settings 클래스의 칸 이름(대문자) → 기본값(리터럴이 아니면 None)"""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            out = {}
            for item in node.body:
                if isinstance(item, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "model_config" for t in item.targets
                ):
                    if "env_prefix" in ast.unparse(item.value):
                        raise FormatError("config.py: model_config 의 env_prefix 는 이 검사가 읽지 못한다")
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    name = item.target.id
                    if name == "model_config":
                        continue
                    if isinstance(item.value, ast.Call) and any(
                        k.arg in {"alias", "validation_alias"} for k in item.value.keywords
                    ):
                        raise FormatError(f"config.py: {name} 의 alias 는 이 검사가 읽지 못한다")
                    default = item.value.value if isinstance(item.value, ast.Constant) else None
                    out[name.upper()] = default
            return out
    raise FormatError("config.py 에 Settings 클래스가 없다")


def env_lines(text: str, path: str) -> tuple[dict[str, str], set[str], list[str]]:
    """틀의 키 → 값, 값 줄(주석 아님)의 키, 중복 문제. 설명 주석(# 다음에 KEY= 가 아닌 줄)은 건너뛴다"""
    values: dict[str, str] = {}
    live: set[str] = set()
    problems = []
    for line in text.splitlines():
        m = ENV_LINE.match(line.strip())
        if not m:
            continue
        commented, key, value = m.groups()
        if commented and re.search(r"\s", value.strip()):
            continue  # '# ENV=prod 에서는 …' 같은 설명 문장 — 주석 키 줄의 값에는 공백이 없다
        if key in values:
            problems.append(f"{path}: {key} 가 두 번 나온다(값 줄·주석 줄 포함) — 한 줄만 둔다")
        values[key] = value.strip()
        if not commented:
            live.add(key)
    return values, live, problems


def readme_env_table(text: str, heading: str) -> dict[str, str]:
    """README '3. 환경 변수' 절에서 heading 다음 첫 표의 `KEY` → 값 칸"""
    start = text.find(README_SECTION)
    if start == -1:
        raise FormatError(f"{FILES['deploy_readme']}: '{README_SECTION}' 절이 없다")
    end = text.find("\n## ", start + 1)
    section = text[start : end if end != -1 else len(text)]
    i = section.find(heading)
    if i == -1:
        raise FormatError(f"{FILES['deploy_readme']}: '{README_SECTION}' 절에 {heading} 표가 없다")
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
    for path, src in ((FILES["frontend_config"], config_ts), (FILES["next_config"], next_config)):
        if re.search(r"\benv\s*\[|process\.env\s*\[|=\s*process\.env\b\s*;|\}\s*=\s*(process\.)?env\b", src):
            raise FormatError(f"{path}: env[…]·구조 분해는 이 검사가 읽지 못한다 — env.KEY 로 쓴다")
    return set(re.findall(r"\benv\.([A-Z][A-Z0-9_]*)", config_ts)) | set(
        re.findall(r"process\.env\.([A-Z][A-Z0-9_]*)", next_config)
    )


def ts_default(source: str, pattern: str) -> str | None:
    m = re.search(pattern, source)
    return m.group(1) if m else None


def check(texts: dict[str, str], required: dict[str, set[str]] = REQUIRED_DEPLOY) -> list[str]:
    try:
        return _check(texts, required)
    except FormatError as e:
        return [str(e)]


def _check(texts: dict[str, str], required: dict[str, set[str]]) -> list[str]:
    problems = []
    fields = settings_fields(texts["config_py"])
    allowed = set(fields) | NON_SETTINGS_KEYS

    dev, _, dup = env_lines(texts["backend_env"], FILES["backend_env"])
    problems += dup
    dep, dep_live, dup = env_lines(texts["deploy_backend_env"], FILES["deploy_backend_env"])
    problems += dup
    rb = readme_env_table(texts["deploy_readme"], README_BACKEND)
    for key in sorted(set(fields) - set(dev)):
        problems.append(f"{FILES['backend_env']}: 설정 칸 {key} 가 없다(값 줄 또는 '# {key}=' 주석 줄로 둔다)")
    for name, keys in (("backend_env", dev), ("deploy_backend_env", dep), ("deploy_readme", rb)):
        for key in sorted(set(keys) - allowed):
            problems.append(f"{FILES[name]}: {key} 는 백엔드 설정 칸이 아니다(오타이거나 config.py 에 없다)")
    for key in sorted(required["backend"] - dep_live):
        problems.append(f"{FILES['deploy_backend_env']}: 운영 필수 키 {key} 의 값 줄이 없다")
    for key in sorted(required["backend"] - set(rb)):
        problems.append(f"{FILES['deploy_readme']}: backend.env 표에 운영 필수 키 {key} 가 없다")

    fkeys = frontend_keys(texts["frontend_config"], texts["next_config"])
    fdev, _, dup = env_lines(texts["frontend_env"], FILES["frontend_env"])
    problems += dup
    fdep, fdep_live, dup = env_lines(texts["deploy_frontend_env"], FILES["deploy_frontend_env"])
    problems += dup
    rf = readme_env_table(texts["deploy_readme"], README_FRONTEND)
    for key in sorted(fkeys - set(fdev)):
        problems.append(f"{FILES['frontend_env']}: 프런트 설정 키 {key} 가 없다")
    for name, keys in (("frontend_env", fdev), ("deploy_frontend_env", fdep), ("deploy_readme", rf)):
        for key in sorted(set(keys) - fkeys):
            problems.append(f"{FILES[name]}: {key} 는 프런트 설정 키가 아니다")
    for key in sorted(required["frontend"] - fdep_live):
        problems.append(f"{FILES['deploy_frontend_env']}: 운영 필수 키 {key} 의 값 줄이 없다")
    for key in sorted(required["frontend"] - set(rf)):
        problems.append(f"{FILES['deploy_readme']}: frontend.env 표에 운영 필수 키 {key} 가 없다")

    # 사이트 시간대 — 빌드에 들어가는 프런트 상수와 같은 값, 운영에서 바꾸지 않는다
    zones = {
        FILES["config_py"]: fields.get("SITE_TIME_ZONE"),
        FILES["time_ts"]: ts_default(texts["time_ts"], r'export const SITE_TIME_ZONE\s*=\s*"([^"]+)"'),
        FILES["backend_env"]: dev.get("SITE_TIME_ZONE"),
    }
    if None in zones.values() or len(set(zones.values())) != 1:
        problems.append("사이트 시간대가 한 값이 아니다(D-103): " + ", ".join(f"{k}={v}" for k, v in zones.items()))
    for name, keys in (("deploy_backend_env", dep), ("deploy_readme", rb)):
        if "SITE_TIME_ZONE" in keys:
            problems.append(
                f"{FILES[name]}: SITE_TIME_ZONE 을 두지 않는다 — 프런트 상수는 빌드에 들어가 운영 값과 갈라진다(D-103)"
            )

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


GOOD = {
    "config_py": 'class Settings:\n    model_config = SettingsConfigDict(env_file=".env")\n    env: str = "prod"\n'
    '    database_url: str = "x"\n    site_time_zone: str = "Asia/Seoul"\n',
    "backend_env": "# 설명 줄\nENV=dev\nDATABASE_URL=x\n# SITE_TIME_ZONE=Asia/Seoul\n# WEB_CONCURRENCY=2\n",
    "deploy_backend_env": "ENV=\nDATABASE_URL=\n# WEB_CONCURRENCY=2\n",
    "deploy_readme": "## 3. 환경 변수\n\n`/etc/mypage/backend.env` 설명\n\n| 키 | 값 |\n|---|---|\n| `ENV` | `prod` |\n"
    "| `DATABASE_URL` | 위 |\n\n`/etc/mypage/frontend.env`:\n\n| 키 | 값 |\n|---|---|\n| `APP_ENV` | `prod` |\n"
    "| `BACKEND_URL` | x |\n\n## 4. 다음\n",
    "frontend_config": 'const a = env.APP_ENV;\nconst b = env.BACKEND_URL ?? "http://localhost:8000";\n',
    "next_config": 'const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";\n',
    "frontend_env": "APP_ENV=dev\nBACKEND_URL=http://localhost:8000\n",
    "deploy_frontend_env": "APP_ENV=\nBACKEND_URL=\n",
    "time_ts": 'export const SITE_TIME_ZONE = "Asia/Seoul";\n',
}
# 대조군: 이름 → (바꿀 파일, 새 내용, 기대 메시지 조각)
BAD_CASES = {
    "설정 칸이 개발 틀에 없다": ("backend_env", "ENV=dev\n# SITE_TIME_ZONE=Asia/Seoul\n", "설정 칸 DATABASE_URL 가 없다"),
    "개발 틀에 오타 키": ("backend_env", GOOD["backend_env"] + "DATABSE_URL=x\n", "DATABSE_URL 는 백엔드 설정 칸이 아니다"),
    "운영 틀에 오타 키": ("deploy_backend_env", "ENV=\nDATABASE_URL=\nENVV=\n", "ENVV 는 백엔드 설정 칸이 아니다"),
    "README 백엔드 표에 오타 키": ("deploy_readme", GOOD["deploy_readme"].replace("`ENV`", "`ENVIRONMENT`"), "ENVIRONMENT 는 백엔드"),
    "운영 틀에서 필수 키가 빠짐": ("deploy_backend_env", "ENV=\n# DATABASE_URL=\n", "운영 필수 키 DATABASE_URL 의 값 줄이 없다"),
    "README 에서 필수 키가 빠짐": ("deploy_readme", GOOD["deploy_readme"].replace("| `DATABASE_URL` | 위 |\n", ""), "backend.env 표에 운영 필수 키 DATABASE_URL"),
    "프런트 키가 개발 틀에 없다": ("frontend_env", "APP_ENV=dev\n", "프런트 설정 키 BACKEND_URL 가 없다"),
    "프런트 개발 틀에 모르는 키": ("frontend_env", GOOD["frontend_env"] + "API_URL=x\n", "API_URL 는 프런트 설정 키가 아니다"),
    "프런트 운영 틀에 모르는 키": ("deploy_frontend_env", "APP_ENV=\nBACKEND_URL=\nAPI_URL=\n", "API_URL 는 프런트 설정 키가 아니다"),
    "프런트 운영 틀에서 필수 키가 빠짐": ("deploy_frontend_env", "APP_ENV=\n", "운영 필수 키 BACKEND_URL 의 값 줄이 없다"),
    "README 프런트 표에 모르는 키": ("deploy_readme", GOOD["deploy_readme"].replace("| `APP_ENV` | `prod` |", "| `APP_ENV` · `API_URL` | `prod` |"), "API_URL 는 프런트 설정 키가 아니다"),
    "README 프런트 표에서 필수 키가 빠짐": ("deploy_readme", GOOD["deploy_readme"].replace("| `BACKEND_URL` | x |\n", ""), "frontend.env 표에 운영 필수 키 BACKEND_URL"),
    "틀의 중복 키": ("backend_env", GOOD["backend_env"] + "# ENV=prod\n", "ENV 가 두 번 나온다"),
    "시간대 — 프런트 상수가 다름": ("time_ts", 'export const SITE_TIME_ZONE = "UTC";\n', "사이트 시간대가 한 값이 아니다"),
    "시간대 — config.py 기본값이 다름": ("config_py", GOOD["config_py"].replace("Asia/Seoul", "UTC"), "사이트 시간대가 한 값이 아니다"),
    "시간대 — 개발 틀 주석이 다름": ("backend_env", GOOD["backend_env"].replace("Asia/Seoul", "UTC"), "사이트 시간대가 한 값이 아니다"),
    "시간대 — 운영 틀에 둠": ("deploy_backend_env", GOOD["deploy_backend_env"] + "# SITE_TIME_ZONE=Asia/Seoul\n", "SITE_TIME_ZONE 을 두지 않는다"),
    "시간대 — README 표에 둠": ("deploy_readme", GOOD["deploy_readme"].replace("| `DATABASE_URL` | 위 |\n", "| `DATABASE_URL` | 위 |\n| `SITE_TIME_ZONE` | `Asia/Seoul` |\n"), "SITE_TIME_ZONE 을 두지 않는다"),
    "BACKEND_URL 기본값 다름(next.config)": ("next_config", 'const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";\n', "BACKEND_URL 기본값이 다르다"),
    "BACKEND_URL 기본값 다름(config.ts)": ("frontend_config", 'const a = env.APP_ENV;\nconst b = env.BACKEND_URL ?? "http://127.0.0.1:8000";\n', "BACKEND_URL 기본값이 다르다"),
    "읽지 못하는 형식 — alias": ("config_py", GOOD["config_py"] + '    debug: bool = Field(False, alias="DBG")\n', "alias 는 이 검사가 읽지 못한다"),
    "읽지 못하는 형식 — env_prefix": ("config_py", GOOD["config_py"].replace('env_file=".env"', 'env_prefix="APP_"'), "env_prefix 는 이 검사가 읽지 못한다"),
    "읽지 못하는 형식 — env[…]": ("frontend_config", GOOD["frontend_config"] + 'const c = env["X"];\n', "env[…]·구조 분해는"),
    "README 절이 없다": ("deploy_readme", "## 다른 절\n", "'## 3. 환경 변수' 절이 없다"),
}  # fmt: skip


SAMPLE_REQUIRED = {"backend": {"ENV", "DATABASE_URL"}, "frontend": {"APP_ENV", "BACKEND_URL"}}


def self_test() -> int:
    failed = []
    if check(GOOD, SAMPLE_REQUIRED):
        failed.append(f"정상 샘플이 실패: {check(GOOD, SAMPLE_REQUIRED)}")
    for label, (key, text, expect) in BAD_CASES.items():
        found = check({**GOOD, key: text}, SAMPLE_REQUIRED)
        if not any(expect in p for p in found):
            failed.append(f"대조군을 잡지 못함: {label} — 기대 '{expect}', 실제 {found}")
    prose = check({**GOOD, "backend_env": GOOD["backend_env"] + "# ENV=prod 에서는 32자 이상\n"}, SAMPLE_REQUIRED)
    if prose:
        failed.append(f"설명 문장을 키 줄로 읽음: {prose}")
    if failed:
        print("\n".join(failed))
        return 1
    print(f"대조군 통과 — 정상 1 · 위반 {len(BAD_CASES)}")
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
