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

    # 개발용 Viewer 헤더(설계도 §5.1, §11) — 인증을 붙이기 전 골격 전용
    dev_viewer_header: bool = False
    dev_viewer_secret: str = ""

    @model_validator(mode="after")
    def _guard_dev_viewer_header(self) -> Self:
        # 방어선 ①: ENV=dev 가 아니면 기동 실패. 방어선 ②: 공유 비밀 값 필수
        if self.dev_viewer_header and self.env != "dev":
            raise ValueError("DEV_VIEWER_HEADER 는 ENV=dev 에서만 켤 수 있습니다")
        if self.dev_viewer_header and len(self.dev_viewer_secret) < 16:
            raise ValueError("DEV_VIEWER_HEADER 를 켜려면 DEV_VIEWER_SECRET(16자 이상)이 필요합니다")
        return self


settings = Settings()
