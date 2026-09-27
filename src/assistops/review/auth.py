"""Operator-provisioned accounts and revocable, server-side browser sessions."""

import hashlib
import hmac
import re
import secrets

from psycopg.rows import dict_row

from assistops.business import BusinessTools
from assistops.events import EventError
from assistops.storage import connect

ITERATIONS = 600_000
USERNAME = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}\Z")
# Unknown accounts still perform the same expensive password verification.
DUMMY_HASH = f"pbkdf2_sha256${ITERATIONS}${'0' * 32}${'0' * 64}"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password):
    if not 15 <= len(password) <= 256:
        raise ValueError("Use a password of 15 to 256 characters")
    salt = secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${value}"


def verify_password(password, stored):
    algorithm, iterations, salt, expected = stored.split("$")
    if algorithm != "pbkdf2_sha256" or int(iterations) != ITERATIONS:
        return False
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return hmac.compare_digest(value, expected)


def allowed_connectors(settings, account):
    """Review grants are separate from a connector's inbound identity allowlist."""
    if "ticket_approver" not in BusinessTools(settings).roles(
        account["tenant_id"], account["user_id"]
    ):
        raise EventError(403, "approval_not_allowed")
    return [
        name
        for name in account["connector_ids"]
        if (connector := settings.webhook_connectors.get(name))
        and connector.tenant_id == account["tenant_id"]
    ]


def provision(settings, username, tenant_id, user_id, connectors, password):
    if not USERNAME.fullmatch(username):
        raise ValueError("Username must contain 3–64 lowercase letters, digits, dots, - or _")
    account = {"tenant_id": tenant_id, "user_id": user_id, "connector_ids": connectors}
    if not connectors or set(allowed_connectors(settings, account)) != set(connectors):
        raise ValueError("Each connector must exist and belong to this account's tenant")
    hashed = password_hash(password)
    with connect(settings) as connection:
        connection.execute(
            """INSERT INTO review_accounts
               (username, tenant_id, user_id, connector_ids, password_hash)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (username) DO UPDATE SET
                 tenant_id = EXCLUDED.tenant_id, user_id = EXCLUDED.user_id,
                 connector_ids = EXCLUDED.connector_ids, password_hash = EXCLUDED.password_hash,
                 disabled = false, updated_at = clock_timestamp()""",
            (username, tenant_id, user_id, list(dict.fromkeys(connectors)), hashed),
        )
        connection.execute("DELETE FROM review_sessions WHERE username = %s", (username,))


def disable(settings, username):
    with connect(settings) as connection:
        changed = connection.execute(
            "UPDATE review_accounts SET disabled = true WHERE username = %s RETURNING username",
            (username,),
        ).fetchone()
        connection.execute("DELETE FROM review_sessions WHERE username = %s", (username,))
    return bool(changed)


def throttle(settings, keys, seconds):
    denied = False
    # Commit attempts even when rejecting: rolling back would defeat the limiter.
    with connect(settings) as connection:
        connection.execute("DELETE FROM review_rate_limits WHERE expires_at < clock_timestamp()")
        for key, limit in sorted(keys):
            count = connection.execute(
                """INSERT INTO review_rate_limits (key, attempts, expires_at)
                   VALUES (%s, 1, clock_timestamp() + %s * interval '1 second')
                   ON CONFLICT (key) DO UPDATE SET attempts = review_rate_limits.attempts + 1
                   RETURNING attempts""",
                (digest(key), seconds),
            ).fetchone()[0]
            denied |= count > limit
    if denied:
        raise EventError(429, "review_rate_limited", retry_after=seconds)


def login(settings, username, password, peer):
    throttle(settings, [("login-user:" + username, 10), ("login-peer:" + peer, 30)], 300)
    with connect(settings) as connection:
        connection.execute("DELETE FROM review_sessions WHERE expires_at < clock_timestamp()")
        with connection.cursor(row_factory=dict_row) as cursor:
            # Password resets and disabling accounts serialize against session creation.
            account = cursor.execute(
                "SELECT * FROM review_accounts WHERE username = %s FOR UPDATE", (username,)
            ).fetchone()
        valid = verify_password(password, account["password_hash"] if account else DUMMY_HASH)
        if not valid or not account or account["disabled"]:
            raise EventError(401, "invalid_credentials")
        if not allowed_connectors(settings, account):
            raise EventError(403, "approval_not_allowed")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        connection.execute(
            """INSERT INTO review_sessions (token_hash, username, csrf_token, expires_at)
               VALUES (%s, %s, %s, clock_timestamp() + %s * interval '1 second')""",
            (digest(token), username, csrf, settings.review_session_seconds),
        )
    return token


def authenticate(settings, token):
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise EventError(401, "session_required")
    with connect(settings) as connection, connection.cursor(row_factory=dict_row) as cursor:
        account = cursor.execute(
            """SELECT a.username, a.tenant_id, a.user_id, a.connector_ids, s.csrf_token
               FROM review_sessions s JOIN review_accounts a USING (username)
               WHERE s.token_hash = %s AND s.expires_at > clock_timestamp() AND NOT a.disabled""",
            (digest(token),),
        ).fetchone()
    if account is None:
        raise EventError(401, "session_required")
    account["connector_ids"] = allowed_connectors(settings, account)
    if not account["connector_ids"]:
        raise EventError(403, "approval_not_allowed")
    throttle(settings, [("session:" + account["username"], 120)], 60)
    return account


def logout(settings, token):
    with connect(settings) as connection:
        connection.execute("DELETE FROM review_sessions WHERE token_hash = %s", (digest(token),))
