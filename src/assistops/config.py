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
    api_rate_limit_requests: int = Field(default=120, ge=1, le=100000)
    api_rate_limit_period_seconds: int = Field(default=60, ge=1, le=3600)
    worker_processor: Literal["disabled", "demo", "rag", "supervisor"] = "disabled"
    rag_model: Literal["gpt-4.1-mini-2025-04-14"] = "gpt-4.1-mini-2025-04-14"
    # Resolve permissions from trusted configuration, never from message content.
    rag_user_roles: dict[str, dict[str, frozenset[str]]] = Field(default_factory=dict)
    rag_embedding_cache: Path = Path(".cache/embeddings")
    business_backend: Literal["disabled", "synthetic"] = "disabled"
    business_user_roles: dict[
        str, dict[str, frozenset[Literal["customer", "support_agent", "ticket_approver"]]]
    ] = Field(default_factory=dict)
    approval_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    ticket_backend: Literal["synthetic", "jira"] = "synthetic"
    jira_site: str = Field(default="", pattern=r"^(|https://[a-z0-9-]+\.atlassian\.net)$")
    jira_project_key: str = Field(default="", pattern=r"^[A-Z][A-Z0-9_]*$|^$")
    jira_issue_type_id: str = Field(default="", pattern=r"^[0-9]*$")
    jira_tenant_id: str = ""
    jira_cloud_id: str = Field(default="", pattern=r"^[a-fA-F0-9-]*$")
    jira_email: str = Field(
        default="", validation_alias=AliasChoices("ASSISTOPS_JIRA_EMAIL", "JIRA_EMAIL")
    )
    jira_api_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ASSISTOPS_JIRA_API_TOKEN", "JIRA_API_TOKEN")
    )
    worker_poll_seconds: float = Field(default=1, ge=0.1, le=30)
    worker_timeout_seconds: float = Field(default=20, ge=0.1, le=300)
    worker_lease_seconds: int = Field(default=60, ge=20, le=600)
    worker_max_attempts: int = Field(default=3, ge=1, le=10)
    worker_retry_seconds: float = Field(default=2, ge=0.1, le=60)

    @model_validator(mode="after")
    def validate_worker(self):
        if self.ticket_backend == "jira" and not all(
            (self.jira_site, self.jira_project_key, self.jira_issue_type_id, self.jira_tenant_id)
        ):
            raise ValueError(
                "Jira tickets require a site, project, issue type and authorized tenant"
            )
        if self.environment == "production" and self.business_backend == "synthetic":
            raise ValueError("Synthetic business services cannot be enabled in production")
        if self.worker_lease_seconds < self.worker_timeout_seconds + 15:
            raise ValueError("Worker lease must exceed processing timeout by at least 15 seconds")
        if self.environment == "production" and self.worker_processor == "demo":
            raise ValueError("Demo processor is only available in local and test environments")
        return self
