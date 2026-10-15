from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "mypage"
    debug: bool = False
    database_url: str = "postgresql+asyncpg://taehunkang@localhost:5432/mypage"

    # DB 연결 풀 — 연결 수 계산식은 설계도 §17. 값은 측정(§15)으로 조정한다
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: float = 30.0
    # 같은 서버의 DB 는 pool_recycle, 원격 DB 일 때만 pool_pre_ping 을 켠다(§15.2)
    db_pool_recycle: int = 3600
    db_pool_pre_ping: bool = False


settings = Settings()
