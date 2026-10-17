"""검증 오류 문구 — 홈블록 설계도 M-9(사용자 결정: 전역 한 곳, app/core/validation_messages.py)."""

import pytest

pytestmark = pytest.mark.anyio


async def test_request_validation_messages_are_korean(client) -> None:
    """M-9(사용자 결정 — 전역 한 곳): 요청 본문 검증의 문구도 한국어. 칸 경로·코드는 그대로(화면이 경로로 칸을 찾는다)"""
    from app.core.validation_messages import ko_message

    res = await client.post("/api/auth/login", json={"email": 1})
    body = res.json()
    assert res.status_code == 422 and body["code"] == "validation_error"
    assert all(not e["message"].isascii() for e in body["errors"]), body["errors"]  # 영문 Pydantic 문구가 남지 않는다
    assert ko_message({"type": "brand_new_type", "msg": "원문"}) == "원문"  # 모르는 종류는 원문 그대로(숨기지 않는다)
