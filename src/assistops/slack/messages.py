"""Render recorded results as plain Slack text with trusted navigation links."""

import re
from uuid import UUID


def render(row, slack):
    result = row["result"] or {}
    if row["status"] == "failed":
        text = "La demande n’a pas pu être traitée. Un opérateur peut consulter son suivi."
    elif row["expired"]:
        text = "La proposition a expiré sans décision. Aucun ticket n’a été créé."
    else:
        text = result.get("message") or {
            "awaiting_approval": "Le ticket est proposé et attend une validation humaine.",
            "ticket_pending": "Approbation enregistrée. Envoi vers Jira en cours.",
            "ticket_created": "Ticket créé après approbation.",
            "rejected": "Proposition refusée. Aucun ticket créé.",
            "expired": "La proposition a expiré. Aucun ticket créé.",
            "ticket_uncertain": "Résultat Jira incertain : vérification humaine nécessaire.",
            "ticket_failed": "La création du ticket a échoué.",
        }.get(result.get("outcome"), "Traitement terminé. Consultez le suivi de la demande.")
    document = result.get("supervisor", {}).get("document_answer") or result
    citations = document.get("citations") or []
    sources = []
    for citation in citations[:5]:
        sources.append(f"[{citation['id']}] {citation['title']} ({citation['document']})")
    if len(text) > 2700:
        text = text[:2650] + "\n[Réponse abrégée pour Slack.]"
    blocks = [{"type": "section", "text": {"type": "plain_text", "text": text}}]
    if sources:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": ("Sources :\n" + "\n".join(sources))[:1000],
                },
            }
        )
    if result.get("origin") in {"synthetic", "mixed"} or any(
        c.get("origin") == "synthetic" for c in citations
    ):
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "plain_text",
                        "text": (
                            "Environnement de test : documents, clients et factures synthétiques. "
                            "Un ticket Jira peut être réel."
                        ),
                    }
                ],
            }
        )
    buttons = []
    proposal = result.get("proposal")
    if proposal:
        identifier = str(UUID(proposal["id"]))
        buttons.append(
            {
                "type": "button",
                "action_id": "open_review",
                "text": {
                    "type": "plain_text",
                    "text": "Consulter la proposition",
                },
                "url": f"{slack.review_url}?proposal={identifier}",
            }
        )
    site = (proposal or {}).get("arguments", {}).get("ticket_target", {}).get("site", "")
    key = result.get("ticket_id") or ""
    if re.fullmatch(r"https://[a-z0-9-]+\.atlassian\.net", site) and re.fullmatch(
        r"[A-Z][A-Z0-9_]*-[0-9]+", key
    ):
        buttons.append(
            {
                "type": "button",
                "action_id": "open_jira",
                "text": {
                    "type": "plain_text",
                    "text": f"Ouvrir {key}",
                },
                "url": f"{site}/browse/{key}",
            }
        )
    if buttons:
        blocks.append({"type": "actions", "elements": buttons})
    # Fallback text is also escaped: model output must never mention a user or an entire channel.
    fallback = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return {"text": fallback, "blocks": blocks, "mrkdwn": False, "parse": "none"}
