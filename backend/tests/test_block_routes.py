"""예약 첫 단·화면 종류 ↔ 실제 라우트 — 홈블록 설계도 §3.3·§3.5·§13('예약 주소·화면 종류').

frontend/app 의 최상위 항목(경로 그룹 괄호를 벗기고, 메타 파일은 내보내는 이름으로)이 ROUTES 와 같은 집합이어야 한다.
새 라우트를 더하고 ROUTES(→ 예약 첫 단)를 빠뜨리면 사용자 페이지가 그 주소를 가로챌 수 있다(D-201 류).
"""

from pathlib import Path

from app.blocks.routes import RESERVED_FIRST_SEGMENTS, ROUTES

APP = Path(__file__).resolve().parents[2] / "frontend" / "app"
NOT_ROUTES = {"layout.tsx", "not-found.tsx", "globals.css", "page.tsx", "[[...path]]"}  # 라우트가 아닌 것·사용자 페이지 자신
META_FILES = {"robots.ts": "robots.txt", "sitemap.ts": "sitemap.xml"}  # Next 메타 파일 → 내보내는 주소(설치본 문서 metadata files)


def top_level(app_dir: Path) -> set[str]:
    out: set[str] = set()
    for entry in app_dir.iterdir():
        if entry.name in NOT_ROUTES:
            continue
        if entry.is_dir() and entry.name.startswith("(") and entry.name.endswith(")"):
            out |= top_level(entry)  # 경로 그룹은 주소에 들어가지 않는다
        else:
            out.add(META_FILES.get(entry.name, entry.name))
    return out


def test_routes_match_frontend_app() -> None:
    assert top_level(APP) == set(ROUTES)


def test_every_route_is_reserved() -> None:
    assert set(ROUTES) <= RESERVED_FIRST_SEGMENTS
    assert {"media", "_next"} <= RESERVED_FIRST_SEGMENTS  # 앞단(nginx·Next)이 쓰는 주소


def test_contract_catches_a_new_route(tmp_path) -> None:
    """대조군: 라우트 폴더 하나를 더한 가상 목록이면 실패한다"""
    for name in ("admin", "(frame)", "help"):
        (tmp_path / name).mkdir()
    (tmp_path / "(frame)" / "search").mkdir()
    assert top_level(tmp_path) != set(ROUTES)
    assert "help" in top_level(tmp_path) - set(ROUTES)
