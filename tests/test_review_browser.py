"""Real browser and HTTP server, with synthetic tools in an isolated PostgreSQL schema."""

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from test_business import TICKET, dispatch
from test_review_ui import PASSWORD

from assistops.main import create_app
from assistops.storage import connect

playwright = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.integration


@pytest.fixture
def review_server(review_db):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
        review_db.review_ui_origin = origin
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(review_db), lifespan="off", log_config=None, access_log=False, ws="none"
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            yield origin
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def test_browser_login_review_cancel_approve_history_and_logout(review_db, review_server):
    dispatch(review_db)
    with playwright.sync_playwright() as manager:
        browser = manager.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(review_server + "/review")
        page.get_by_label("Identifiant", exact=True).fill("reviewer")
        page.get_by_label("Mot de passe", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Se connecter").click()
        page.locator(".proposal-row").click()
        playwright.expect(page.locator("#description")).to_have_text(TICKET["description"])
        playwright.expect(page.locator("#destination")).to_contain_text("Simulation locale")
        # Only fictional records are captured; no session tokens appear on this screen.
        Path(".cache").mkdir(exist_ok=True)
        page.screenshot(path=".cache/review-ui.png", full_page=True)
        page.get_by_role("button", name="Approuver la simulation…").click()
        page.get_by_role("button", name="Annuler").click()
        with connect(review_db) as connection:
            assert (
                connection.execute("SELECT status FROM ticket_proposals").fetchone()[0] == "pending"
            )
        page.get_by_role("button", name="Approuver la simulation…").click()
        page.get_by_role("button", name="Confirmer l’approbation").click()
        playwright.expect(page.locator("#delivery")).to_contain_text("simulateur local")
        page.get_by_label("Filtrer les propositions").select_option("all")
        playwright.expect(page.locator(".proposal-row")).to_have_count(1)
        page.get_by_role("button", name="Déconnexion").click()
        playwright.expect(page.locator("#login-view")).to_be_visible()
        assert page.request.get(review_server + "/review/api/proposals").status == 401
        assert errors == []
        browser.close()


def test_mobile_browser_renders_untrusted_content_as_text_and_rejects(review_db, review_server):
    untrusted = '<img src=x onerror="window.injected=true">'
    dispatch(
        review_db, {**TICKET, "subject": untrusted, "description": "<script>alert(1)</script>"}
    )
    with playwright.sync_playwright() as manager:
        browser = manager.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        page.goto(review_server + "/review")
        page.get_by_label("Identifiant", exact=True).fill("reviewer")
        page.get_by_label("Mot de passe", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Se connecter").click()
        page.locator(".proposal-row").click()
        playwright.expect(page.locator("#subject")).to_have_text(untrusted)
        assert page.locator("#subject img").count() == 0
        assert page.evaluate("window.injected === undefined")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_role("button", name="Refuser", exact=True).click()
        page.get_by_role("button", name="Confirmer le refus").click()
        playwright.expect(page.locator("#delivery")).to_contain_text("Proposition refusée")
        browser.close()
    with connect(review_db) as connection:
        assert connection.execute("SELECT count(*) FROM synthetic_tickets").fetchone()[0] == 0
