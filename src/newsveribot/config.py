from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="NEWSVERIBOT_",
        env_ignore_empty=True,
        extra="ignore",
    )

    log_level: str = "INFO"
    http_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    max_download_bytes: int = Field(default=2_000_000, ge=10_000, le=10_000_000)
    max_article_chars: int = Field(default=20_000, ge=1_000, le=100_000)
    max_claims: int = Field(default=5, ge=1, le=20)
    max_redirects: int = Field(default=3, ge=0, le=10)
    fact_check_page_size: int = Field(default=20, ge=1, le=100)
    claim_model_path: Path | None = None

    fact_check_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GOOGLE_FACT_CHECK_API_KEY",
            "NEWSVERIBOT_FACT_CHECK_API_KEY",
        ),
    )
    discord_bot_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("DISCORD_BOT_TOKEN", "NEWSVERIBOT_DISCORD_BOT_TOKEN"),
    )
    discord_guild_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("DISCORD_GUILD_ID", "NEWSVERIBOT_DISCORD_GUILD_ID"),
    )
    api_base_url: str = "http://127.0.0.1:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
