from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from assistops.events import Identifier


class SlackSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SLACK_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    bot_token: SecretStr
    app_token: SecretStr
    team_id: str = Field(pattern=r"^T[A-Z0-9]+$")
    channel_id: str = Field(pattern=r"^[CG][A-Z0-9]+$")
    user_map: dict[str, Identifier] = Field(min_length=1)
    connector_id: Identifier = "slack-demo"
    review_url: str = "http://localhost:8000/review"

    @field_validator("user_map")
    @classmethod
    def valid_members(cls, mapping):
        import re

        if any(not re.fullmatch(r"[UW][A-Z0-9]+", key) for key in mapping):
            raise ValueError("Slack member IDs are required")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("Each Slack member must have a distinct AssistOps identity")
        return mapping

    @field_validator("review_url")
    @classmethod
    def valid_url(cls, value):
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1"})
        ):
            raise ValueError("Review URL requires HTTPS, except on localhost")
        return value

    def connector(self, settings):
        connector = settings.webhook_connectors.get(self.connector_id)
        if (
            connector is None
            or connector.source != "slack"
            or not set(self.user_map.values()) <= connector.allowed_user_ids
        ):
            raise ValueError("Slack identities require an explicitly configured Slack connector")
        return connector
