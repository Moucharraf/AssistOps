from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASSISTOPS_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["local", "test", "production"] = "local"
    database_url: SecretStr = SecretStr(
        "postgresql://assistops:assistops-local-only@localhost:5432/assistops"
    )
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    dependency_timeout_seconds: float = Field(default=3.0, ge=0.1, le=30)
