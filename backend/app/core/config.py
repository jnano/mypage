from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "mypage"
    debug: bool = False
    # 실행 환경 — 기본값은 가장 엄격한 prod. 로컬 개발은 .env 에 ENV=dev
    env: Literal["dev", "test", "prod"] = "prod"
    database_url: str = "postgresql+asyncpg://taehunkang@localhost:5432/mypage"

    # DB 연결 풀 — 연결 수 계산식은 설계도 §17. 값은 측정(§15)으로 조정한다
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: float = 30.0
    # 같은 서버의 DB 는 pool_recycle, 원격 DB 일 때만 pool_pre_ping 을 켠다(§15.2)
    db_pool_recycle: int = 3600
    db_pool_pre_ping: bool = False

    # Next 서버 → FastAPI 내부 호출 확인용 공유 비밀(§3.5, §6). 상태를 바꾸는 요청은 이 값이 있어야 한다.
    # 비어 있으면 모든 쓰기를 거부한다(fail closed). Next 의 같은 이름 환경 변수와 같은 값
    internal_api_secret: str = ""

    # 작업자(§3.2) — `python -m app.worker`
    worker_poll_seconds: float = 30.0  # LISTEN 으로 놓친 일을 줍는 폴링 간격
    worker_batch: int = 50  # 한 번 깨어날 때 처리할 최대 이벤트 수
    # 작업자 → Next 캐시 무효화(Route Handler, 내부 비밀 헤더 INTERNAL_API_SECRET)
    next_revalidate_url: str = "http://localhost:3000/api/revalidate"

    # 파일 저장소(§12) — 공개(/media 로 직접 내줌)·비공개(권한 판정 뒤 전송) 폴더
    media_root: str = "var/media"
    private_root: str = "var/private"
    # 파일 전송 방식(§12.2): stream(FastAPI 직접, 개발) | nginx(X-Accel-Redirect, 배포)
    file_sender: Literal["stream", "nginx"] = "stream"
    nginx_private_prefix: str = "/_private/"  # nginx internal location

    # 요청 계측(§15.3) — 응답에 Server-Timing(app·db 시간, 쿼리 수). 측정할 때만 켠다
    server_timing: bool = False

    # 개발용 Viewer 헤더(설계도 §5.1, §11) — 인증을 붙이기 전 골격 전용
    dev_viewer_header: bool = False
    dev_viewer_secret: str = ""

    @model_validator(mode="after")
    def _guard_secrets(self) -> Self:
        # 방어선 ①: ENV=dev 가 아니면 기동 실패. 방어선 ②: 공유 비밀 값 필수
        if self.dev_viewer_header and self.env != "dev":
            raise ValueError("DEV_VIEWER_HEADER 는 ENV=dev 에서만 켤 수 있습니다")
        if self.dev_viewer_header and len(self.dev_viewer_secret) < 16:
            raise ValueError("DEV_VIEWER_HEADER 를 켜려면 DEV_VIEWER_SECRET(16자 이상)이 필요합니다")
        if self.env == "prod" and len(self.internal_api_secret) < 32:
            raise ValueError("ENV=prod 에서는 INTERNAL_API_SECRET(32자 이상)이 필요합니다")
        return self


settings = Settings()
