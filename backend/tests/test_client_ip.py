"""클라이언트 IP 판정 — 인증 설계도 §2.3·§9 '클라이언트 IP'"""

import pytest
from starlette.requests import Request

from app.core.client_ip import client_ip
from tests.conftest import INTERNAL_SECRET


def _request(headers: dict[str, str], peer: str = "127.0.0.1") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw, "client": (peer, 5000)})


def test_internal_request_uses_forwarded_client_ip() -> None:
    assert client_ip(_request({"X-Internal-Secret": INTERNAL_SECRET, "X-Client-IP": "203.0.113.9"})) == "203.0.113.9"
    # IPv6 는 정규형으로
    assert client_ip(_request({"X-Internal-Secret": INTERNAL_SECRET, "X-Client-IP": "2001:DB8::0:1"})) == "2001:db8::1"


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Client-IP": "203.0.113.9"},  # 내부 비밀 없음 — 브라우저가 rewrites 로 직접 보낸 값
        {"X-Internal-Secret": "wrong", "X-Client-IP": "203.0.113.9"},
        {"X-Internal-Secret": INTERNAL_SECRET, "X-Client-IP": "203.0.113.9, 10.0.0.1"},  # 형식이 틀림
        {"X-Internal-Secret": INTERNAL_SECRET, "X-Client-IP": "evil"},
        {"X-Internal-Secret": INTERNAL_SECRET},
    ],
)
def test_otherwise_connection_address(headers: dict[str, str]) -> None:
    assert client_ip(_request(headers, peer="198.51.100.7")) == "198.51.100.7"
