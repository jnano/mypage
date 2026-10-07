from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "mypage"
    debug: bool = False
    database_url: str = "postgresql+asyncpg://taehunkang@localhost:5432/mypage"


settings = Settings()
