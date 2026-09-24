from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Connector(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    secret: SecretStr = Field(min_length=32)
    tenant_id: str
    allowed_user_ids: frozenset[str] = Field(min_length=1)
    source: Literal["webhook", "slack", "email"] = "webhook"


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
    webhook_connectors: dict[str, Connector] = Field(default_factory=dict)
    webhook_body_timeout_seconds: float = Field(default=10, ge=0.1, le=30)
