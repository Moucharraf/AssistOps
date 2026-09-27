+++
document_id = "secondary-billing-disputes"
title = "Contestation de facture — espace Boréal"
version = 1
tenant_id = "boreal"
language = "fr"
category = "billing"
owner = "Finance fictive"
status = "active"
effective_from = 2026-01-01
allowed_roles = ["customer","billing_admin","support_agent","support_lead","finance","security","it_admin"]
origin = "synthetic"
synthetic_reason = "Scénario original fictif pour tester recherche, versions et permissions sans données personnelles réelles."
external_sources = []
+++

# Contestation de facture — espace Boréal

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Périmètre séparé

Boréal Services est un second client entièrement fictif d’Asteria Cloud. Ce document appartient exclusivement au tenant boreal. Il ne doit pas être utilisé pour répondre aux utilisateurs du tenant demo, même si la question emploie exactement les mêmes mots.

## Règle propre au tenant

Pour le tenant boreal, la convention fictive prévoit un délai de contestation de 45 jours calendaires après émission de la facture. Le contact de facturation recueille le numéro du document, les lignes contestées et le motif, puis transmet le dossier par le portail de ce tenant.

Cette convention ne modifie aucune politique du tenant demo. Elle n’est pas un modèle de contrat réel et ne doit pas être interprétée comme un droit universel applicable à tous les clients.

## Réponse du support

Le support vérifie le périmètre de l’utilisateur avant de consulter les données de facture. Une référence appartenant à un autre espace ne peut pas être copiée dans un ticket local. Les justificatifs sont limités aux éléments utiles et ne contiennent pas de numéro de carte complet.

## Utilisation dans les tests

Ce document est volontairement très proche du guide de contestation principal. Il sert à démontrer que les filtres de tenant doivent être appliqués avant de présenter une source au modèle, et que la similarité vectorielle ne peut jamais tenir lieu d’autorisation.

