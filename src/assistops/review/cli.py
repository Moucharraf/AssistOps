"""Provision or revoke a reviewer without transmitting passwords through CLI arguments."""

import argparse
import getpass

import psycopg

from assistops.config import Settings
from assistops.events import EventError
from assistops.review.auth import disable, provision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("set-password", help="Create/update account and revoke sessions")
    create.add_argument("username")
    create.add_argument("--tenant", required=True)
    create.add_argument("--user", required=True)
    create.add_argument("--connector", action="append", required=True)
    revoke = commands.add_parser("disable", help="Disable account and revoke every session")
    revoke.add_argument("username")
    args = parser.parse_args()
    settings = Settings()
    try:
        if args.command == "disable":
            if not disable(settings, args.username):
                parser.exit(1, "Account not found.\n")
            print("Account disabled; sessions revoked.")
        else:
            password = getpass.getpass("New password (15–256 characters): ")
            if password != getpass.getpass("Confirm password: "):
                parser.exit(1, "Passwords do not match.\n")
            provision(settings, args.username, args.tenant, args.user, args.connector, password)
            print("Account saved; previous sessions revoked.")
    except (ValueError, EventError) as exc:
        parser.exit(1, f"Invalid account: {exc.code if isinstance(exc, EventError) else exc}\n")
    except psycopg.Error:
        parser.exit(1, "Database unavailable. Check configuration and migrations.\n")


if __name__ == "__main__":
    main()
