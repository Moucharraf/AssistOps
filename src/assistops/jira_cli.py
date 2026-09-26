"""Read-only Jira setup checks and explicit operator reconciliation."""

import argparse
import json
from uuid import UUID

import httpx

from assistops.config import Settings
from assistops.jira import JiraClient, JiraError
from assistops.ticket_delivery import reconcile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", help="HTTPS Jira Cloud site, without trailing slash")
    parser.add_argument("--project", help="Project key")
    parser.add_argument("--discover-cloud-id", action="store_true")
    parser.add_argument("--reconcile", type=UUID, metavar="PROPOSAL_ID")
    parser.add_argument("--issue", help="Existing Jira issue key, for reconciliation only")
    args = parser.parse_args()
    overrides = {}
    if args.site:
        overrides["jira_site"] = args.site.rstrip("/")
    if args.project:
        overrides["jira_project_key"] = args.project
    settings = Settings(**overrides)
    try:
        if args.discover_cloud_id:
            if not settings.jira_site:
                raise JiraError("jira_site_missing")
            response = httpx.get(settings.jira_site + "/_edge/tenant_info", timeout=10)
            response.raise_for_status()
            print(json.dumps({"cloud_id": str(UUID(response.json()["cloudId"]))}))
            return
        if args.reconcile:
            if not args.issue:
                parser.error("--reconcile requires --issue")
            reconcile(settings, args.reconcile, args.issue)
            print(json.dumps({"status": "reconciled", "issue_key": args.issue}))
            return
        if args.issue:
            parser.error("--issue requires --reconcile")
        if not settings.jira_project_key:
            raise JiraError("jira_project_missing")
        client = JiraClient(settings)
        try:
            permissions = client.request(
                "GET",
                "mypermissions",
                params={
                    "projectKey": settings.jira_project_key,
                    "permissions": "BROWSE_PROJECTS,CREATE_ISSUES",
                },
            ).get("permissions", {})
            if not all(
                permissions.get(p, {}).get("havePermission")
                for p in ("BROWSE_PROJECTS", "CREATE_ISSUES")
            ):
                raise JiraError("jira_project_permissions_missing")
            types = client.request(
                "GET",
                f"issue/createmeta/{settings.jira_project_key}/issuetypes",
                params={"maxResults": 100},
            )
            report = {
                "project": settings.jira_project_key,
                "issue_types": [
                    {"id": t["id"], "name": t["name"]} for t in types.get("issueTypes", [])
                ],
                "total_issue_types": types.get("total"),
            }
            if settings.jira_issue_type_id:
                fields = client.request(
                    "GET",
                    f"issue/createmeta/{settings.jira_project_key}/issuetypes/"
                    + settings.jira_issue_type_id,
                    params={"maxResults": 100},
                )
                report["required_fields"] = [
                    {"id": f["fieldId"], "has_default": bool(f.get("hasDefaultValue"))}
                    for f in fields.get("fields", [])
                    if f.get("required")
                ]
                report["total_fields"] = fields.get("total")
                report["returned_fields"] = len(fields.get("fields", []))
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            client.close()
    except (JiraError, httpx.HTTPError, ValueError, KeyError) as exc:
        print(
            json.dumps({"error": exc.code if isinstance(exc, JiraError) else "jira_check_failed"})
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
