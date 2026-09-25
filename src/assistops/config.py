from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, model_validator
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
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ASSISTOPS_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    embedding_model: Literal["text-embedding-3-small"] = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=256, le=1536)
    dependency_timeout_seconds: float = Field(default=3.0, ge=0.1, le=30)
    webhook_connectors: dict[str, Connector] = Field(default_factory=dict)
    webhook_body_timeout_seconds: float = Field(default=10, ge=0.1, le=30)
    worker_processor: Literal["disabled", "demo", "rag"] = "disabled"
    rag_model: Literal["gpt-4.1-mini-2025-04-14"] = "gpt-4.1-mini-2025-04-14"
    # Resolve permissions from trusted configuration, never from message content.
    rag_user_roles: dict[str, dict[str, frozenset[str]]] = Field(default_factory=dict)
    rag_daily_attempts: int = Field(default=5, ge=0, le=20)
    rag_embedding_cache: Path = Path(".cache/embeddings")
    worker_poll_seconds: float = Field(default=1, ge=0.1, le=30)
    worker_timeout_seconds: float = Field(default=20, ge=0.1, le=300)
    worker_lease_seconds: int = Field(default=60, ge=20, le=600)
    worker_max_attempts: int = Field(default=3, ge=1, le=10)
    worker_retry_seconds: float = Field(default=2, ge=0.1, le=60)

    @model_validator(mode="after")
    def validate_worker(self):
        if self.worker_lease_seconds < self.worker_timeout_seconds + 15:
            raise ValueError("Worker lease must exceed processing timeout by at least 15 seconds")
        if self.environment == "production" and self.worker_processor == "demo":
            raise ValueError("Demo processor is only available in local and test environments")
        return self
