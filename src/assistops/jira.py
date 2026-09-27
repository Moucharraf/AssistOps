"""Jira Cloud transport. No implicit retries of external writes."""

import re

import httpx


class JiraError(Exception):
    def __init__(self, code, *, uncertain=False, retry_after=None):
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain
        self.retry_after = retry_after


class JiraClient:
    def __init__(self, settings, *, transport=None):
        if not settings.jira_site or not settings.jira_email or not settings.jira_api_token:
            raise JiraError("jira_credentials_missing")
        self.settings = settings
        base = (
            f"https://api.atlassian.com/ex/jira/{settings.jira_cloud_id}"
            if settings.jira_cloud_id
            else settings.jira_site
        )
        self.client = httpx.Client(
            base_url=base + "/rest/api/3/",
            timeout=10,
            follow_redirects=False,
            auth=(settings.jira_email, settings.jira_api_token.get_secret_value()),
            headers={"Accept": "application/json"},
            transport=transport,
        )

    def close(self):
        self.client.close()

    def request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise JiraError("jira_transport_error", uncertain=method == "POST") from None
        if response.status_code == 429:
            raw = response.headers.get("Retry-After", "60")
            delay = int(raw) if raw.isdigit() and len(raw) < 8 else 86400
            raise JiraError("jira_rate_limited", retry_after=max(1, delay))
        expected = 201 if method == "POST" else 200
        if response.status_code != expected:
            # A server error or unexpected response may follow an already committed write.
            raise JiraError(
                f"jira_http_{response.status_code}",
                uncertain=method == "POST"
                and response.status_code not in {400, 401, 403, 404, 422},
            )
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except ValueError:
            raise JiraError("jira_invalid_response", uncertain=method == "POST") from None

    def create(self, proposal):
        args = proposal["arguments"]
        target = args["ticket_target"]
        # Source CRM data is still fictional, even though the destination ticket is real.
        text = (
            "[AssistOps: données métier synthétiques — test d’intégration]\n"
            + args["description"]
            + "\nFacture fictive : "
            + args["invoice_id"]
            + "\nRéférence AssistOps : "
            + str(proposal["id"])
        )
        result = self.request(
            "POST",
            "issue",
            json={
                "fields": {
                    "project": {"key": target["project"]},
                    "issuetype": {"id": target["issue_type_id"]},
                    "summary": args["subject"],
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
                        ],
                    },
                },
                "properties": [
                    {
                        "key": "assistops.proposal",
                        "value": {
                            "id": str(proposal["id"]),
                            "arguments_hash": proposal["arguments_hash"],
                        },
                    }
                ],
            },
        )
        key = result.get("key", "")
        if not isinstance(key, str) or not re.fullmatch(
            re.escape(target["project"]) + r"-[0-9]+", key
        ):
            raise JiraError("jira_invalid_issue_key", uncertain=True)
        return key

    def verify_issue(self, proposal, key):
        target = proposal["arguments"]["ticket_target"]
        if not re.fullmatch(re.escape(target["project"]) + r"-[0-9]+", key):
            raise JiraError("jira_issue_mismatch")
        issue = self.request("GET", f"issue/{key}", params={"fields": "project,issuetype"})
        marker = self.request("GET", f"issue/{key}/properties/assistops.proposal")
        if (
            issue.get("key") != key
            or issue.get("fields", {}).get("project", {}).get("key") != target["project"]
            or issue.get("fields", {}).get("issuetype", {}).get("id") != target["issue_type_id"]
            or marker.get("value")
            != {"id": str(proposal["id"]), "arguments_hash": proposal["arguments_hash"]}
        ):
            raise JiraError("jira_issue_mismatch")
