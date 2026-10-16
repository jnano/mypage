"""클라이언트 IP — 인증 설계도 §2.3. 요청 수 제한·운영 기록의 IP 는 모두 이 함수 하나로 정한다.

Server Action·Route Handler 의 FastAPI 호출은 Next 가 새로 만드는 요청이라 FastAPI 는 Next 의 주소(127.0.0.1)를
본다. 그래서 Next 가 nginx 의 X-Real-IP 를 X-Client-IP 로 실어 보내고, FastAPI 는 **내부 비밀이 맞을 때만** 그 값을 믿는다.
uvicorn 의 X-Forwarded-For 신뢰(127.0.0.1 의 모든 프로세스를 믿는다)에 기대지 않는다.
"""

import ipaddress

from fastapi import Request

from app.core.csrf import is_internal

HEADER = "X-Client-IP"


def client_ip(request: Request) -> str:
    """내부 비밀 + 올바른 IP 형식의 X-Client-IP 면 그 값, 아니면 연결 주소(rewrites 경로는 nginx 값이 반영됨)"""
    given = request.headers.get(HEADER)
    if given and is_internal(request):
        try:
            return str(ipaddress.ip_address(given.strip()))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"
