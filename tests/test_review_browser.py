"""Real browser and HTTP server, with synthetic tools in an isolated PostgreSQL schema."""

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from psycopg.types.json import Jsonb
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
    proposal = dispatch(review_db)[2].result["proposal"]
    with playwright.sync_playwright() as manager:
        browser = manager.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(review_server + "/review?proposal=" + proposal["id"])
        page.get_by_label("Identifiant", exact=True).fill("reviewer")
        page.get_by_label("Mot de passe", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Se connecter").click()
        playwright.expect(page.locator("#proposal-id")).to_have_text(proposal["id"])
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


def test_background_refresh_preserves_layout_focus_and_updates_expiry(review_db, review_server):
    dispatch(review_db)
    with playwright.sync_playwright() as manager:
        browser = manager.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(review_server + "/review")
        page.get_by_label("Identifiant", exact=True).fill("reviewer")
        page.get_by_label("Mot de passe", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Se connecter").click()
        page.locator(".proposal-row").click()
        playwright.expect(page.locator("#decision-actions")).to_be_visible()
        # Finish initial rendering before observing the same refresh used by the timer.
        page.evaluate("async () => { await loadList(); }")
        result = page.evaluate("""async () => {
            const row = document.querySelector('.proposal-row');
            row.focus();
            window.scrollTo(0, document.body.scrollHeight);
            const top = window.scrollY;
            const changes = [];
            const observer = new MutationObserver(records => changes.push(...records));
            observer.observe(document.querySelector('#workspace'), {
                subtree: true, attributes: true, childList: true, characterData: true
            });
            await refresh();
            changes.push(...observer.takeRecords());
            observer.disconnect();
            return {
                mutations: changes.length,
                sameRow: row === document.querySelector('.proposal-row'),
                focused: document.activeElement === row,
                scrollDelta: window.scrollY - top,
                actionsVisible: !document.querySelector('#decision-actions').hidden
            };
        }""")
        assert result == {
            "mutations": 0,
            "sameRow": True,
            "focused": True,
            "scrollDelta": 0,
            "actionsVisible": True,
        }
        with connect(review_db) as connection:
            connection.execute("UPDATE ticket_proposals SET expires_at = now() - interval '1s'")
        page.evaluate("async () => { await refresh(); }")
        playwright.expect(page.locator("#detail-status")).to_have_text("Expirée")
        playwright.expect(page.locator("#decision-actions")).to_be_hidden()
        playwright.expect(page.locator(".proposal-row")).to_have_count(0)
        browser.close()


def test_review_shows_stored_evidence_and_preserves_it_after_decision(review_db, review_server):
    request, _, job = dispatch(review_db)
    evidence = {
        "document_answer": {
            "message": "Vous pouvez contester sous 30 jours. [1]",
            "citations": [
                {
                    "id": 1,
                    "title": "Procédure fictive",
                    "origin": "synthetic",
                    "quote": '<img src=x onerror="window.injected=true">',
                }
            ],
        },
        "read_result": {
            "outcome": "read_completed",
            "data": {
                "invoice_id": "INV-001",
                "amount_minor": 4900,
                "currency": "EUR",
                "status": "unpaid",
            },
        },
    }
    with connect(review_db) as connection:
        connection.execute(
            "UPDATE event_jobs SET result = %s", (Jsonb({**job.result, "supervisor": evidence}),)
        )
    with playwright.sync_playwright() as manager:
        browser = manager.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(review_server + "/review")
        page.get_by_label("Identifiant", exact=True).fill("reviewer")
        page.get_by_label("Mot de passe", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Se connecter").click()
        page.locator(".proposal-row").click()
        page.locator("#request-context summary").click()
        playwright.expect(page.locator("#request-message")).to_have_text(request.message)
        playwright.expect(page.locator("#invoice-evidence")).to_contain_text(
            "49,00 EUR · Non payée"
        )
        page.locator("#document-context summary").click()
        playwright.expect(page.locator("#document-answer")).to_have_text(
            evidence["document_answer"]["message"]
        )
        playwright.expect(page.locator("#document-sources")).to_contain_text("Document synthétique")
        assert page.locator("#document-sources img").count() == 0
        assert page.evaluate("window.injected === undefined")
        page.evaluate("async () => { await refresh(); }")
        assert page.locator("#document-context").evaluate("el => el.open")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=".cache/review-context.png", full_page=True)
        page.get_by_role("button", name="Refuser", exact=True).click()
        page.get_by_role("button", name="Confirmer le refus").click()
        playwright.expect(page.locator("#delivery")).to_contain_text("Proposition refusée")
        playwright.expect(page.locator("#document-answer")).to_have_text(
            evidence["document_answer"]["message"]
        )
        browser.close()
