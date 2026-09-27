"""Run the Slack connector separately from the API and AI worker."""

import argparse
import logging
import signal
from threading import Event

import psycopg
import structlog
from pydantic import ValidationError
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse

from assistops.config import Settings
from assistops.events import EventError
from assistops.observability import configure_logging
from assistops.slack.config import SlackSettings
from assistops.slack.delivery import deliver_once
from assistops.slack.ingress import accept
from assistops.slack.transport import SlackAPI

logger = structlog.get_logger()


def listener(settings, slack, bot_user_id):
    def receive(client, request):
        try:
            if request.type == "events_api":
                receipt = accept(request.payload, slack, settings, bot_user_id)
                if receipt:
                    logger.info(
                        "slack_event_received",
                        event_id=str(receipt.receipt_id),
                        duplicate=receipt.duplicate,
                    )
        except EventError as exc:
            logger.warning("slack_event_rejected", error_code=exc.code)
            if exc.status == 429:
                return
        except (ValidationError, ValueError, TypeError):
            logger.warning("slack_event_rejected", error_code="invalid_event")
        except Exception as exc:
            # No acknowledgement on a storage failure: Slack may redeliver the same event.
            logger.warning("slack_ingress_unavailable", error_type=type(exc).__name__)
            return
        client.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))

    return receive


def run(check=False):
    settings, slack = Settings(), SlackSettings()
    slack.connector(settings)
    api = SlackAPI(slack)
    socket = None
    try:
        identity = api.call("auth.test", {})
        if identity.get("team_id") != slack.team_id or not identity.get("bot_id"):
            raise ValueError("Slack bot does not belong to the configured workspace")
        # SDK exceptions can contain requests; only our redacted structured logs are exported.
        sdk_logger = logging.getLogger("assistops.slack.sdk")
        sdk_logger.handlers = [logging.NullHandler()]
        sdk_logger.propagate = False
        web = WebClient(
            token=slack.bot_token.get_secret_value(),
            timeout=10,
            retry_handlers=[],
            logger=sdk_logger,
        )
        if check:
            web.apps_connections_open(app_token=slack.app_token.get_secret_value())
            logger.info(
                "slack_credentials_verified", team_id=slack.team_id, bot_user_id=identity["user_id"]
            )
            return
        stop = Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        socket = SocketModeClient(
            app_token=slack.app_token.get_secret_value(),
            web_client=web,
            logger=sdk_logger,
            concurrency=2,
        )
        socket.socket_mode_request_listeners.append(listener(settings, slack, identity["user_id"]))
        socket.connect()
        logger.info("slack_connected", team_id=slack.team_id, channel_id=slack.channel_id)
        # One sender per process, paced to Slack's per-channel posting rate.
        while not stop.wait(1):
            try:
                deliver_once(settings, slack, api)
            except psycopg.Error as exc:
                logger.warning("slack_storage_unavailable", error_type=type(exc).__name__)
            except Exception as exc:
                logger.error("slack_delivery_unavailable", error_type=type(exc).__name__)
    finally:
        if socket:
            socket.close()
        api.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Verify tokens without receiving events"
    )
    args = parser.parse_args()
    configure_logging()
    try:
        run(check=args.check)
    except Exception as exc:
        logger.error("slack_connector_stopped", error_type=type(exc).__name__)
        raise SystemExit(1) from None
